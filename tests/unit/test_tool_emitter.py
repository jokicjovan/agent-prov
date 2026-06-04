"""Tests for ToolInvocationEmitter — field extraction, hash determinism, schema shape.

Covers:
  Unit tests: emit output shape, tool name/version extraction, agent_id derivation,
              hash properties, parent_record_id chaining.
  Integration tests: ProvenanceMiddleware on_tool_start/on_tool_end round-trip;
                     mixed step + tool sequence with correct record chaining.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from agent_prov._frames import _NodeFrame, _ToolFrame
from agent_prov._hashing import hash_content
from agent_prov.core import ProvenanceMiddleware
from agent_prov.tool_emitter import (
    _derive_agent_id,
    _extract_tool_name,
    _extract_tool_version,
    emit_tool_invocation,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class StubSession:
    pipeline_id: str = "00000000-0000-0000-0000-000000000001"
    session_id: str = "00000000-0000-0000-0000-000000000002"
    protocol_version: str = "0.1.0"
    last_record_id: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)

    def add_record(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        self.last_record_id = record["record_id"]


def _make_tool_frame(**overrides: Any) -> _ToolFrame:
    defaults = dict(
        run_id=uuid4(),
        parent_run_id=None,
        timestamp_start="2026-01-01T00:00:00.000000Z",
        serialized={"name": "web_search", "kwargs": {}},
        input_str='{"query": "EU AI Act Article 12"}',
        metadata={},
    )
    defaults.update(overrides)
    return _ToolFrame(**defaults)


FAKE_OUTPUT = "Here are the top results for EU AI Act Article 12..."


# ---------------------------------------------------------------------------
# Unit tests — emit_tool_invocation output shape
# ---------------------------------------------------------------------------


def test_emit_produces_all_required_fields():
    session = StubSession()
    frame = _make_tool_frame()
    emit_tool_invocation(frame, FAKE_OUTPUT, session, {})

    assert len(session.records) == 1
    r = session.records[0]

    assert r["record_type"] == "tool_invocation"
    assert r["protocol_version"] == "0.1.0"
    assert UUID_RE.match(r["record_id"])
    assert r["pipeline_id"] == session.pipeline_id
    assert r["session_id"] == session.session_id
    assert isinstance(r["tool_name"], str) and len(r["tool_name"]) > 0
    assert isinstance(r["tool_version"], str) and len(r["tool_version"]) > 0
    assert SHA256_RE.match(r["input_hash"])
    assert SHA256_RE.match(r["output_hash"])
    assert r["timestamp_start"] == frame.timestamp_start
    assert r["timestamp_end"] > r["timestamp_start"]
    assert r["reference_data_id"] is None
    assert r["parent_record_id"] is None


def test_emit_wires_parent_record_id_from_session():
    session = StubSession(last_record_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    emit_tool_invocation(_make_tool_frame(), FAKE_OUTPUT, session, {})
    assert session.records[0]["parent_record_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_sequential_tool_calls_chain_parent_record_ids():
    session = StubSession()
    emit_tool_invocation(_make_tool_frame(), FAKE_OUTPUT, session, {})
    first_id = session.records[0]["record_id"]

    emit_tool_invocation(_make_tool_frame(), FAKE_OUTPUT, session, {})
    assert session.records[1]["parent_record_id"] == first_id


# ---------------------------------------------------------------------------
# Unit tests — tool name extraction
# ---------------------------------------------------------------------------


def test_tool_name_from_serialized_name():
    frame = _make_tool_frame(serialized={"name": "sql_query", "kwargs": {}})
    assert _extract_tool_name(frame) == "sql_query"


def test_tool_name_falls_back_to_unknown_when_serialized_has_no_name():
    frame = _make_tool_frame(serialized={})
    assert _extract_tool_name(frame) == "unknown"


def test_tool_name_falls_back_to_unknown_when_serialized_is_empty_dict():
    frame = _make_tool_frame(serialized={"kwargs": {"foo": "bar"}})
    assert _extract_tool_name(frame) == "unknown"


# ---------------------------------------------------------------------------
# Unit tests — tool version extraction
# ---------------------------------------------------------------------------


def test_tool_version_from_serialized_kwargs():
    frame = _make_tool_frame(serialized={"name": "web_search", "kwargs": {"version": "2.1.0"}})
    assert _extract_tool_version(frame) == "2.1.0"


def test_tool_version_from_metadata():
    frame = _make_tool_frame(
        serialized={"name": "web_search", "kwargs": {}},
        metadata={"tool_version": "v3-beta"},
    )
    assert _extract_tool_version(frame) == "v3-beta"


def test_tool_version_kwargs_takes_precedence_over_metadata():
    frame = _make_tool_frame(
        serialized={"name": "web_search", "kwargs": {"version": "1.0.0"}},
        metadata={"tool_version": "2.0.0"},
    )
    assert _extract_tool_version(frame) == "1.0.0"


def test_tool_version_falls_back_to_unversioned():
    frame = _make_tool_frame(serialized={"name": "web_search", "kwargs": {}}, metadata={})
    assert _extract_tool_version(frame) == "unversioned"


def test_tool_version_fallback_logs_warning(caplog):
    frame = _make_tool_frame(serialized={"name": "web_search", "kwargs": {}}, metadata={})
    with caplog.at_level(logging.WARNING, logger="middleware.tool_emitter"):
        _extract_tool_version(frame)
    assert any(
        rec.levelno == logging.WARNING and "web_search" in rec.getMessage()
        for rec in caplog.records
    )


def test_tool_version_no_warning_when_version_present(caplog):
    frame = _make_tool_frame(serialized={"name": "web_search", "kwargs": {"version": "2.1.0"}})
    with caplog.at_level(logging.WARNING, logger="middleware.tool_emitter"):
        _extract_tool_version(frame)
    assert not caplog.records


# ---------------------------------------------------------------------------
# Unit tests — agent_id derivation
# ---------------------------------------------------------------------------


def test_agent_id_derived_from_parent_node():
    parent_run_id = uuid4()
    nodes = {
        parent_run_id: _NodeFrame(
            run_id=parent_run_id,
            parent_run_id=None,
            node_name="researcher",
            timestamp_start="2026-01-01T00:00:00.000000Z",
            inputs={},
        )
    }
    frame = _make_tool_frame(parent_run_id=parent_run_id)
    assert _derive_agent_id(frame, nodes) == "researcher"


def test_agent_id_falls_back_to_str_run_id_when_node_not_found():
    parent_run_id = uuid4()
    frame = _make_tool_frame(parent_run_id=parent_run_id)
    assert _derive_agent_id(frame, {}) == str(parent_run_id)


def test_agent_id_is_unknown_when_no_parent():
    frame = _make_tool_frame(parent_run_id=None)
    assert _derive_agent_id(frame, {}) == "unknown"


# ---------------------------------------------------------------------------
# Unit tests — hash properties
# ---------------------------------------------------------------------------


def test_input_hash_is_deterministic():
    frame = _make_tool_frame(input_str='{"query": "test"}')
    session = StubSession()
    emit_tool_invocation(frame, FAKE_OUTPUT, session, {})
    h1 = session.records[0]["input_hash"]

    session2 = StubSession()
    emit_tool_invocation(frame, FAKE_OUTPUT, session2, {})
    h2 = session2.records[0]["input_hash"]

    assert h1 == h2
    assert SHA256_RE.match(h1)


def test_different_tool_inputs_produce_different_hashes():
    h1 = hash_content('{"query": "foo"}')
    h2 = hash_content('{"query": "bar"}')
    assert h1 != h2


# ---------------------------------------------------------------------------
# Integration tests — ProvenanceMiddleware lifecycle
# ---------------------------------------------------------------------------


def test_middleware_tool_start_end_emits_record():
    session = StubSession()
    mw = ProvenanceMiddleware(session)

    run_id = uuid4()
    mw.on_tool_start(
        serialized={"name": "web_search", "kwargs": {"version": "1.0.0"}},
        input_str='{"query": "provenance"}',
        run_id=run_id,
    )
    assert mw.in_flight["tools"] == 1

    mw.on_tool_end(output="Result text", run_id=run_id)

    assert mw.in_flight["tools"] == 0
    assert len(session.records) == 1
    r = session.records[0]
    assert r["record_type"] == "tool_invocation"
    assert r["tool_name"] == "web_search"
    assert r["tool_version"] == "1.0.0"
    assert SHA256_RE.match(r["input_hash"])
    assert SHA256_RE.match(r["output_hash"])


def test_middleware_unmatched_tool_end_is_silently_ignored():
    session = StubSession()
    mw = ProvenanceMiddleware(session)
    mw.on_tool_end(output="orphan", run_id=uuid4())
    assert len(session.records) == 0


def test_middleware_step_then_tool_chains_records():
    """Agent step followed by tool call: tool record's parent_record_id == step record_id."""
    session = StubSession()
    mw = ProvenanceMiddleware(session)

    step_run_id = uuid4()
    mw.on_chat_model_start(
        serialized={"name": "ChatOpenAI", "kwargs": {"model": "gpt-4o"}},
        messages=[[{"type": "human", "content": "Search for something"}]],
        run_id=step_run_id,
        metadata={"ls_model_name": "gpt-4o"},
    )
    mw.on_llm_end(
        response={"generations": [[{"text": "I will search now"}]], "llm_output": {}},
        run_id=step_run_id,
    )
    assert len(session.records) == 1
    step_record_id = session.records[0]["record_id"]

    tool_run_id = uuid4()
    mw.on_tool_start(
        serialized={"name": "web_search", "kwargs": {}},
        input_str='{"query": "EU AI Act"}',
        run_id=tool_run_id,
    )
    mw.on_tool_end(output="Search results...", run_id=tool_run_id)

    assert len(session.records) == 2
    assert session.records[1]["record_type"] == "tool_invocation"
    assert session.records[1]["parent_record_id"] == step_record_id
