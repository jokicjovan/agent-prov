"""Tests for AgentStepEmitter — field extraction, hash determinism, schema shape."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from agent_prov.adapters.langchain._frames import (
    _NodeFrame,
    _StepFrame,
    _derive_agent_id,
)
from agent_prov._hashing import hash_content
from agent_prov.adapters.langchain.step_emitter import (
    _extract_model_id,
    _extract_model_version,
    emit_agent_step,
    emit_agent_step_error,
)
from agent_prov.session import PipelineSession
from agent_prov.validation import validate_record

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


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
    session = PipelineSession()
    frame = _make_frame()
    emit_agent_step(frame, FAKE_RESPONSE, session, {})

    assert len(session.records) == 1
    r = session.records[0]

    assert r["record_type"] == "agent_step"
    assert r["protocol_version"] == session.protocol_version
    assert UUID_RE.match(r["record_id"])
    assert r["pipeline_id"] == session.pipeline_id
    assert r["session_id"] == session.session_id
    assert SHA256_RE.match(r["input_hash"])
    assert SHA256_RE.match(r["output_hash"])
    assert r["timestamp_start"] == frame.timestamp_start
    assert r["timestamp_end"] > r["timestamp_start"]
    assert r["reference_data_id"] is None
    assert r["parent_record_id"] is None
    assert r["status"] == "success"
    assert "error" not in r
    assert isinstance(r["agent_id"], str) and len(r["agent_id"]) > 0
    assert isinstance(r["model_id"], str) and len(r["model_id"]) > 0
    assert isinstance(r["model_version"], str) and len(r["model_version"]) > 0


def test_emit_error_produces_valid_failure_record():
    session = PipelineSession()
    frame = _make_frame()
    emit_agent_step_error(frame, TimeoutError("provider timed out"), session, {})

    assert len(session.records) == 1
    r = session.records[0]

    assert r["status"] == "error"
    assert "output_hash" not in r
    assert r["error"]["type"] == "TimeoutError"
    assert r["error"]["source"] == "provider"
    assert SHA256_RE.match(r["error"]["message_hash"])
    # input/identity/timing are still captured on a failed step
    assert SHA256_RE.match(r["input_hash"])
    assert r["timestamp_start"] == frame.timestamp_start
    assert isinstance(r["model_id"], str) and len(r["model_id"]) > 0
    # the failure record passes the full validation surface (schema + conditional)
    validate_record(r)


def test_emit_error_chains_parent_record_id_like_a_normal_step():
    session = PipelineSession()
    emit_agent_step(_make_frame(), FAKE_RESPONSE, session, {})
    first_id = session.records[0]["record_id"]
    emit_agent_step_error(_make_frame(), ValueError("boom"), session, {})
    assert session.records[1]["parent_record_id"] == first_id


def test_emit_wires_parent_record_id_from_session():
    session = PipelineSession()
    session.last_record_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    emit_agent_step(_make_frame(), FAKE_RESPONSE, session, {})
    assert session.records[0]["parent_record_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_sequential_steps_chain_parent_record_ids():
    session = PipelineSession()
    emit_agent_step(_make_frame(), FAKE_RESPONSE, session, {})
    first_id = session.records[0]["record_id"]

    emit_agent_step(_make_frame(), FAKE_RESPONSE, session, {})
    assert session.records[1]["parent_record_id"] == first_id


def test_reference_data_id_passed_through_from_metadata():
    """A RAG corpus id supplied via metadata lands on the record (Art. 12(3)(b))."""
    session = PipelineSession()
    frame = _make_frame(metadata={"ls_model_name": "gpt-4o", "reference_data_id": "corpus-v3"})
    emit_agent_step(frame, FAKE_RESPONSE, session, {})
    r = session.records[0]
    assert r["reference_data_id"] == "corpus-v3"
    validate_record(r)


def test_reference_data_id_defaults_to_none_without_metadata():
    """No reference data consulted -> null, the schema's documented default."""
    session = PipelineSession()
    emit_agent_step(_make_frame(metadata={}), FAKE_RESPONSE, session, {})
    assert session.records[0]["reference_data_id"] is None


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
    h1 = hash_content({"b": 2, "a": 1})
    h2 = hash_content({"a": 1, "b": 2})
    assert h1 == h2
    assert SHA256_RE.match(h1)


def test_different_inputs_produce_different_hashes():
    h1 = hash_content("hello")
    h2 = hash_content("world")
    assert h1 != h2


# --- output_hash determinism -------------------------------------------------
# emit_agent_step must hash the *semantic* model output, not the full response
# envelope: LangChain stamps a fresh runtime id on every generated message, so
# hashing the envelope makes an identical answer digest differently each run.


def _llm_result(content: str, *, message_id: str, tool_calls: Any = None) -> LLMResult:
    """Build an LLMResult shaped like a real chat-model response."""
    message = AIMessage(content=content, id=message_id, tool_calls=tool_calls or [])
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_output_hash_is_stable_across_runtime_message_ids():
    """Same content, different LangChain-assigned message id -> same output_hash."""
    session_a, session_b = PipelineSession(), PipelineSession()
    emit_agent_step(_make_frame(), _llm_result("identical answer", message_id="run--aaaaaaaa-0"), session_a, {})
    emit_agent_step(_make_frame(), _llm_result("identical answer", message_id="run--bbbbbbbb-0"), session_b, {})
    assert session_a.records[0]["output_hash"] == session_b.records[0]["output_hash"]


def test_output_hash_changes_with_content():
    """Different model output -> different output_hash."""
    session = PipelineSession()
    emit_agent_step(_make_frame(), _llm_result("answer one", message_id="run--a-0"), session, {})
    emit_agent_step(_make_frame(), _llm_result("answer two", message_id="run--a-0"), session, {})
    assert session.records[0]["output_hash"] != session.records[1]["output_hash"]


def test_output_hash_reflects_tool_calls_when_content_is_empty():
    """A tool-calling step carries no content; its tool call must still be hashed."""
    call_x = [{"name": "web_search", "args": {"query": "x"}, "id": "call_1", "type": "tool_call"}]
    call_y = [{"name": "web_search", "args": {"query": "y"}, "id": "call_2", "type": "tool_call"}]
    session = PipelineSession()
    emit_agent_step(_make_frame(), _llm_result("", message_id="run--a-0", tool_calls=call_x), session, {})
    emit_agent_step(_make_frame(), _llm_result("", message_id="run--a-0", tool_calls=call_y), session, {})
    assert session.records[0]["output_hash"] != session.records[1]["output_hash"]


def test_output_hash_ignores_runtime_tool_call_ids():
    """Tool-call ids are runtime-assigned; identical name/args -> same output_hash."""
    call_a = [{"name": "web_search", "args": {"query": "x"}, "id": "call_aaa", "type": "tool_call"}]
    call_b = [{"name": "web_search", "args": {"query": "x"}, "id": "call_bbb", "type": "tool_call"}]
    session = PipelineSession()
    emit_agent_step(_make_frame(), _llm_result("", message_id="run--a-0", tool_calls=call_a), session, {})
    emit_agent_step(_make_frame(), _llm_result("", message_id="run--a-0", tool_calls=call_b), session, {})
    assert session.records[0]["output_hash"] == session.records[1]["output_hash"]


# --- input_hash determinism --------------------------------------------------
# Symmetric with output_hash: the input projection must strip the same runtime
# identifiers, otherwise any multi-turn history (where a prior AIMessage with
# a fresh runtime id sits in the messages list) re-randomises input_hash on
# every replay even when nothing semantically changed.


def test_input_hash_is_stable_across_runtime_ai_message_ids():
    """Same conversation history, different LangChain-assigned ids -> same input_hash."""
    history_a = [[
        HumanMessage(content="hello"),
        AIMessage(content="hi back", id="run--aaaaaaaa-0"),
    ]]
    history_b = [[
        HumanMessage(content="hello"),
        AIMessage(content="hi back", id="run--bbbbbbbb-0"),
    ]]
    session_a, session_b = PipelineSession(), PipelineSession()
    emit_agent_step(_make_frame(messages=history_a), FAKE_RESPONSE, session_a, {})
    emit_agent_step(_make_frame(messages=history_b), FAKE_RESPONSE, session_b, {})
    assert session_a.records[0]["input_hash"] == session_b.records[0]["input_hash"]


def test_input_hash_is_stable_across_runtime_tool_call_ids():
    """Tool-call and tool-message correlation ids are runtime; semantically equal histories -> same input_hash."""
    call_a = [{"name": "web_search", "args": {"query": "x"}, "id": "call_aaa", "type": "tool_call"}]
    call_b = [{"name": "web_search", "args": {"query": "x"}, "id": "call_bbb", "type": "tool_call"}]
    history_a = [[
        HumanMessage(content="look it up"),
        AIMessage(content="", id="run--a-0", tool_calls=call_a),
        ToolMessage(content="result", tool_call_id="call_aaa", name="web_search"),
    ]]
    history_b = [[
        HumanMessage(content="look it up"),
        AIMessage(content="", id="run--b-0", tool_calls=call_b),
        ToolMessage(content="result", tool_call_id="call_bbb", name="web_search"),
    ]]
    session_a, session_b = PipelineSession(), PipelineSession()
    emit_agent_step(_make_frame(messages=history_a), FAKE_RESPONSE, session_a, {})
    emit_agent_step(_make_frame(messages=history_b), FAKE_RESPONSE, session_b, {})
    assert session_a.records[0]["input_hash"] == session_b.records[0]["input_hash"]


def test_input_hash_changes_when_content_changes():
    """Different message content -> different input_hash."""
    session = PipelineSession()
    emit_agent_step(_make_frame(messages=[[HumanMessage(content="one")]]), FAKE_RESPONSE, session, {})
    emit_agent_step(_make_frame(messages=[[HumanMessage(content="two")]]), FAKE_RESPONSE, session, {})
    assert session.records[0]["input_hash"] != session.records[1]["input_hash"]


def test_input_hash_distinguishes_human_from_ai_message():
    """type is part of the projection: identical content on different roles must not collide."""
    session = PipelineSession()
    emit_agent_step(_make_frame(messages=[[HumanMessage(content="same")]]), FAKE_RESPONSE, session, {})
    emit_agent_step(_make_frame(messages=[[AIMessage(content="same", id="run--a-0")]]), FAKE_RESPONSE, session, {})
    assert session.records[0]["input_hash"] != session.records[1]["input_hash"]
