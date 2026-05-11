"""Tests for AgentStepEmitter — field extraction, hash determinism, schema shape."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from middleware.core import _NodeFrame, _StepFrame
from middleware.step_emitter import (
    _derive_agent_id,
    _extract_model_id,
    _extract_model_version,
    _hash_obj,
    emit_agent_step,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


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


def _make_frame(**overrides: Any) -> _StepFrame:
    defaults = dict(
        run_id=uuid4(),
        parent_run_id=None,
        timestamp_start="2026-01-01T00:00:00.000000Z",
        serialized={"name": "ChatOpenAI", "kwargs": {"model": "gpt-4o"}},
        messages=[[{"type": "human", "content": "What is the EU AI Act?"}]],
        metadata={"ls_model_name": "gpt-4o"},
    )
    defaults.update(overrides)
    return _StepFrame(**defaults)


FAKE_RESPONSE = {"generations": [[{"text": "The EU AI Act is..."}]], "llm_output": {}}


def test_emit_produces_all_required_fields():
    session = StubSession()
    frame = _make_frame()
    emit_agent_step(frame, FAKE_RESPONSE, session, {})

    assert len(session.records) == 1
    r = session.records[0]

    assert r["record_type"] == "agent_step"
    assert r["protocol_version"] == "0.1.0"
    assert UUID_RE.match(r["record_id"])
    assert r["pipeline_id"] == session.pipeline_id
    assert r["session_id"] == session.session_id
    assert SHA256_RE.match(r["input_hash"])
    assert SHA256_RE.match(r["output_hash"])
    assert r["timestamp_start"] == frame.timestamp_start
    assert r["timestamp_end"] > r["timestamp_start"]
    assert r["reference_data_id"] is None
    assert r["parent_record_id"] is None
    assert isinstance(r["agent_id"], str) and len(r["agent_id"]) > 0
    assert isinstance(r["model_id"], str) and len(r["model_id"]) > 0
    assert isinstance(r["model_version"], str) and len(r["model_version"]) > 0


def test_emit_wires_parent_record_id_from_session():
    session = StubSession(last_record_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    emit_agent_step(_make_frame(), FAKE_RESPONSE, session, {})
    assert session.records[0]["parent_record_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_sequential_steps_chain_parent_record_ids():
    session = StubSession()
    emit_agent_step(_make_frame(), FAKE_RESPONSE, session, {})
    first_id = session.records[0]["record_id"]

    emit_agent_step(_make_frame(), FAKE_RESPONSE, session, {})
    assert session.records[1]["parent_record_id"] == first_id


def test_model_id_from_ls_model_name_metadata():
    frame = _make_frame(
        metadata={"ls_model_name": "claude-opus-4-7"},
        serialized={"name": "ChatAnthropic"},
    )
    assert _extract_model_id(frame) == "claude-opus-4-7"


def test_model_id_falls_back_to_serialized_kwargs_model():
    frame = _make_frame(
        metadata={},
        serialized={"name": "ChatOpenAI", "kwargs": {"model": "gpt-4o-mini"}},
    )
    assert _extract_model_id(frame) == "gpt-4o-mini"


def test_model_id_falls_back_to_serialized_kwargs_model_name():
    frame = _make_frame(
        metadata={},
        serialized={"kwargs": {"model_name": "text-embedding-3-small"}},
    )
    assert _extract_model_id(frame) == "text-embedding-3-small"


def test_model_id_falls_back_to_serialized_name():
    frame = _make_frame(metadata={}, serialized={"name": "CustomLLM"})
    assert _extract_model_id(frame) == "CustomLLM"


def test_model_version_uses_explicit_kwarg_when_present():
    frame = _make_frame(
        metadata={},
        serialized={"kwargs": {"model": "gpt-4o", "model_version": "2024-11-20"}},
    )
    assert _extract_model_version(frame) == "2024-11-20"


def test_model_version_falls_back_to_model_id():
    frame = _make_frame(
        metadata={"ls_model_name": "gpt-4o"},
        serialized={},
    )
    assert _extract_model_version(frame) == "gpt-4o"


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
    frame = _make_frame(parent_run_id=parent_run_id)
    assert _derive_agent_id(frame, nodes) == "researcher"


def test_agent_id_falls_back_to_str_run_id_when_node_not_found():
    parent_run_id = uuid4()
    frame = _make_frame(parent_run_id=parent_run_id)
    assert _derive_agent_id(frame, {}) == str(parent_run_id)


def test_agent_id_is_unknown_when_no_parent():
    frame = _make_frame(parent_run_id=None)
    assert _derive_agent_id(frame, {}) == "unknown"


def test_hash_is_deterministic_and_order_independent():
    h1 = _hash_obj({"b": 2, "a": 1})
    h2 = _hash_obj({"a": 1, "b": 2})
    assert h1 == h2
    assert SHA256_RE.match(h1)


def test_different_inputs_produce_different_hashes():
    h1 = _hash_obj("hello")
    h2 = _hash_obj("world")
    assert h1 != h2
