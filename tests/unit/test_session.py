"""Tests for PipelineSession - ID generation, record accumulation, parent-chain
wiring, and the framework-neutral record factory.

Test cases covering:
  1-2  UUID generation for pipeline_id and session_id.
  3    Custom pipeline_id is used verbatim; session_id is still fresh.
  4    Two instances share pipeline_id but get distinct session_ids.
  5-6  Protocol version: default and custom.
  7    last_record_id is None before any record is added.
  8-9  add_record appends records and updates last_record_id.
  10   Records accumulate in insertion order.
  11   last_record_id always tracks the most recently added record.
  12   __len__ mirrors len(session.records).
  13   SessionProtocol interface - required attributes are all present.
  14   Integration: ProvenanceMiddleware + PipelineSession round-trip emits
       a valid, parent-chained record sequence.
  15   Construction rejects a pipeline_id that is not a lowercase UUID.
  16   Construction rejects a protocol_version that is not valid semver.
  17-24 Record factory: add_agent_step / add_tool_invocation (and _error
       variants) assemble, hash, bind status, parent-chain, and validate.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest

from agent_prov._hashing import hash_content
from agent_prov.adapters.langchain import ProvenanceMiddleware
from agent_prov.session import PipelineSession, _DEFAULT_PROTOCOL_VERSION
from agent_prov.validation import validate_record


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
FIXED_PIPELINE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


# ---------------------------------------------------------------------------
# Tests 1-2 - UUID generation
# ---------------------------------------------------------------------------


def test_01_default_pipeline_id_is_a_valid_lowercase_uuid():
    session = PipelineSession()
    assert UUID_RE.match(session.pipeline_id), session.pipeline_id


def test_02_default_session_id_is_a_valid_lowercase_uuid():
    session = PipelineSession()
    assert UUID_RE.match(session.session_id), session.session_id


# ---------------------------------------------------------------------------
# Tests 3-4 - custom pipeline_id / session uniqueness
# ---------------------------------------------------------------------------


def test_03_custom_pipeline_id_is_used_verbatim_and_session_id_is_fresh():
    session = PipelineSession(pipeline_id=FIXED_PIPELINE_ID)
    assert session.pipeline_id == FIXED_PIPELINE_ID
    assert UUID_RE.match(session.session_id)
    assert session.session_id != FIXED_PIPELINE_ID


def test_04_two_instances_with_same_pipeline_id_get_distinct_session_ids():
    a = PipelineSession(pipeline_id=FIXED_PIPELINE_ID)
    b = PipelineSession(pipeline_id=FIXED_PIPELINE_ID)
    assert a.session_id != b.session_id


# ---------------------------------------------------------------------------
# Tests 5-6 - protocol version
# ---------------------------------------------------------------------------


def test_05_default_protocol_version_matches_module_constant():
    session = PipelineSession()
    assert session.protocol_version == _DEFAULT_PROTOCOL_VERSION


def test_06_custom_protocol_version_is_respected():
    session = PipelineSession(protocol_version="1.2.3")
    assert session.protocol_version == "1.2.3"


# ---------------------------------------------------------------------------
# Test 7 - initial state
# ---------------------------------------------------------------------------


def test_07_last_record_id_is_none_before_any_record_is_added():
    session = PipelineSession()
    assert session.last_record_id is None
    assert session.records == []


# ---------------------------------------------------------------------------
# Tests 8-9 - add_record basic behaviour
# ---------------------------------------------------------------------------


def _make_record(record_id: str) -> dict[str, Any]:
    return {"record_id": record_id, "record_type": "agent_step", "payload": "x"}


def test_08_add_record_appends_to_records_list():
    session = PipelineSession()
    rec = _make_record("11111111-1111-1111-1111-111111111111")
    session.add_record(rec)
    assert len(session.records) == 1
    assert session.records[0] is rec


def test_09_add_record_updates_last_record_id_to_the_new_record_id():
    session = PipelineSession()
    rec_id = "11111111-1111-1111-1111-111111111111"
    session.add_record(_make_record(rec_id))
    assert session.last_record_id == rec_id


# ---------------------------------------------------------------------------
# Test 10 - insertion order
# ---------------------------------------------------------------------------


def test_10_records_accumulate_in_insertion_order():
    session = PipelineSession()
    ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    ]
    for rid in ids:
        session.add_record(_make_record(rid))
    assert [r["record_id"] for r in session.records] == ids


# ---------------------------------------------------------------------------
# Test 11 - last_record_id always points to most recent
# ---------------------------------------------------------------------------


def test_11_last_record_id_always_tracks_the_most_recent_record():
    session = PipelineSession()
    for i, rid in enumerate(["aaaa" * 8, "bbbb" * 8, "cccc" * 8]):
        rid_full = f"{rid[:8]}-{rid[8:12]}-{rid[12:16]}-{rid[16:20]}-{rid[20:32]}"
        session.add_record(_make_record(rid_full))
        assert session.last_record_id == rid_full


# ---------------------------------------------------------------------------
# Test 12 - __len__
# ---------------------------------------------------------------------------


def test_12_len_mirrors_records_list_length():
    session = PipelineSession()
    assert len(session) == 0
    session.add_record(_make_record("11111111-1111-1111-1111-111111111111"))
    assert len(session) == 1
    session.add_record(_make_record("22222222-2222-2222-2222-222222222222"))
    assert len(session) == 2


# ---------------------------------------------------------------------------
# Test 13 - SessionProtocol interface
# ---------------------------------------------------------------------------


def test_13_session_satisfies_session_protocol_interface():
    from agent_prov.session import SessionProtocol

    session = PipelineSession()
    # Structural conformance to the interface the middleware depends on.
    assert isinstance(session, SessionProtocol)
    # The attributes the protocol declares must also have the expected types.
    assert isinstance(session.pipeline_id, str)
    assert isinstance(session.session_id, str)
    assert isinstance(session.protocol_version, str)
    assert callable(session.add_record)


# ---------------------------------------------------------------------------
# Test 14 - integration with ProvenanceMiddleware
# ---------------------------------------------------------------------------


def test_14_integration_middleware_emits_records_into_session_with_parent_chaining():
    """ProvenanceMiddleware + PipelineSession: two LLM calls produce two records
    where the second record's parent_record_id equals the first record's record_id.
    """
    session = PipelineSession(pipeline_id=FIXED_PIPELINE_ID)
    mw = ProvenanceMiddleware(session)

    node_run_id = uuid4()
    mw.on_chain_start(
        serialized={"name": "researcher"},
        inputs={"topic": "AI Act"},
        run_id=node_run_id,
    )

    # First LLM call
    run_a = uuid4()
    mw.on_chat_model_start(
        serialized={"name": "ChatOpenAI", "kwargs": {"model": "gpt-4o"}},
        messages=[[{"type": "human", "content": "What is the EU AI Act?"}]],
        run_id=run_a,
        parent_run_id=node_run_id,
        metadata={"ls_model_name": "gpt-4o"},
    )
    mw.on_llm_end(
        response={"generations": [[{"text": "The EU AI Act is ..."}]]},
        run_id=run_a,
    )

    assert len(session) == 1
    first_record = session.records[0]
    assert first_record["record_type"] == "agent_step"
    assert first_record["pipeline_id"] == FIXED_PIPELINE_ID
    assert first_record["agent_id"] == "researcher"
    assert first_record["model_id"] == "gpt-4o"
    assert SHA256_RE.match(first_record["input_hash"])
    assert SHA256_RE.match(first_record["output_hash"])
    assert first_record["parent_record_id"] is None  # first record has no parent

    # Second LLM call - parent_record_id must point to the first record
    run_b = uuid4()
    mw.on_chat_model_start(
        serialized={"name": "ChatOpenAI", "kwargs": {"model": "gpt-4o"}},
        messages=[[{"type": "human", "content": "Summarise Article 12."}]],
        run_id=run_b,
        parent_run_id=node_run_id,
        metadata={"ls_model_name": "gpt-4o"},
    )
    mw.on_llm_end(
        response={"generations": [[{"text": "Article 12 requires ..."}]]},
        run_id=run_b,
    )

    assert len(session) == 2
    second_record = session.records[1]
    assert second_record["parent_record_id"] == first_record["record_id"]

    mw.on_chain_end(outputs={}, run_id=node_run_id)
    assert mw.in_flight == {"nodes": 0, "steps": 0, "tools": 0}


# ---------------------------------------------------------------------------
# Tests 15-16 - input validation at construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_pipeline_id",
    [
        "research-pipeline-v1",                          # arbitrary slug - the documented footgun
        "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",          # uppercase UUID - protocol mandates lowercase
        "aaaaaaaa-aaaa-aaaa-aaaa",                       # truncated
        "",                                              # empty
    ],
)
def test_15_construction_rejects_non_uuid_pipeline_id(bad_pipeline_id: str):
    with pytest.raises(ValueError, match="pipeline_id"):
        PipelineSession(pipeline_id=bad_pipeline_id)


@pytest.mark.parametrize(
    "bad_version",
    [
        "1",            # not three components
        "1.2",          # not three components
        "v1.2.3",       # leading "v"
        "1.2.3.4",      # too many components
        "01.2.3",       # leading zero in major
        "",             # empty
    ],
)
def test_16_construction_rejects_non_semver_protocol_version(bad_version: str):
    with pytest.raises(ValueError, match="protocol_version"):
        PipelineSession(protocol_version=bad_version)


# ---------------------------------------------------------------------------
# Tests 17-24 - framework-neutral record factory (add_agent_step /
# add_tool_invocation and their _error variants). These exercise the assembly,
# hashing, status binding, and parent-chaining that adapters delegate to.
# ---------------------------------------------------------------------------


_STEP_KW = dict(
    agent_id="researcher",
    model_id="gpt-4o",
    model_version="gpt-4o-2024-11-20",
    timestamp_start="2026-01-01T00:00:00.000000Z",
)
_TOOL_KW = dict(
    agent_id="researcher",
    tool_name="web_search",
    tool_version="1.0.0",
    timestamp_start="2026-01-01T00:00:00.000000Z",
)


def test_17_add_agent_step_assembles_appends_and_validates():
    session = PipelineSession()
    record = session.add_agent_step(**_STEP_KW, input="prompt", output="answer")

    assert session.records == [record]              # appended
    assert session.last_record_id == record["record_id"]
    assert record["record_type"] == "agent_step"
    assert record["protocol_version"] == session.protocol_version
    assert record["pipeline_id"] == session.pipeline_id
    assert record["session_id"] == session.session_id
    assert record["agent_id"] == "researcher"
    assert record["model_id"] == "gpt-4o"
    assert record["status"] == "success"
    assert SHA256_RE.match(record["input_hash"])
    assert SHA256_RE.match(record["output_hash"])
    assert "error" not in record
    assert record["timestamp_end"] >= record["timestamp_start"]
    assert record["reference_data_id"] is None
    validate_record(record)


def test_18_add_agent_step_hashes_match_hash_content():
    session = PipelineSession()
    record = session.add_agent_step(**_STEP_KW, input="prompt", output="answer")
    assert record["input_hash"] == hash_content("prompt")
    assert record["output_hash"] == hash_content("answer")


def test_19_add_agent_step_error_binds_status_and_error_object():
    session = PipelineSession()
    record = session.add_agent_step_error(
        **_STEP_KW, input="prompt", error_type="TimeoutError",
        error_message="provider timed out",
    )
    assert record["status"] == "error"
    assert "output_hash" not in record
    assert record["error"] == {
        "type": "TimeoutError",
        "source": "provider",
        "message_hash": hash_content("provider timed out"),
    }
    validate_record(record)


def test_20_add_agent_step_error_includes_retryable_only_when_set():
    session = PipelineSession()
    with_flag = session.add_agent_step_error(
        **_STEP_KW, input="p", error_type="E", error_message="m", retryable=True
    )
    assert with_flag["error"]["retryable"] is True

    without_flag = session.add_agent_step_error(
        **_STEP_KW, input="p", error_type="E", error_message="m"
    )
    assert "retryable" not in without_flag["error"]


def test_21_add_tool_invocation_assembles_appends_and_validates():
    session = PipelineSession()
    record = session.add_tool_invocation(
        **_TOOL_KW, input='{"q": "x"}', output="results"
    )
    assert session.records == [record]
    assert record["record_type"] == "tool_invocation"
    assert record["tool_name"] == "web_search"
    assert record["tool_version"] == "1.0.0"
    assert record["status"] == "success"
    assert record["input_hash"] == hash_content('{"q": "x"}')
    assert record["output_hash"] == hash_content("results")
    validate_record(record)


def test_22_add_tool_invocation_error_sources_from_tool_boundary():
    session = PipelineSession()
    record = session.add_tool_invocation_error(
        **_TOOL_KW, input='{"q": "x"}', error_type="ConnectionError",
        error_message="refused",
    )
    assert record["status"] == "error"
    assert "output_hash" not in record
    assert record["error"]["source"] == "tool"
    assert record["error"]["type"] == "ConnectionError"
    validate_record(record)


def test_23_factory_chains_parent_record_id_across_record_types():
    session = PipelineSession()
    step = session.add_agent_step(**_STEP_KW, input="p", output="a")
    assert step["parent_record_id"] is None

    tool = session.add_tool_invocation(**_TOOL_KW, input="i", output="o")
    assert tool["parent_record_id"] == step["record_id"]

    failed = session.add_agent_step_error(
        **_STEP_KW, input="p", error_type="E", error_message="m"
    )
    assert failed["parent_record_id"] == tool["record_id"]


def test_24_factory_passes_reference_data_id_through():
    session = PipelineSession()
    record = session.add_agent_step(
        **_STEP_KW, input="p", output="a", reference_data_id="corpus-v3"
    )
    assert record["reference_data_id"] == "corpus-v3"
    validate_record(record)


def test_25_factory_attaches_runtime_metadata_when_supplied():
    session = PipelineSession()
    meta = {"run_id": "run-123", "message_id": "msg-9"}
    record = session.add_agent_step(
        **_STEP_KW, input="p", output="a", runtime_metadata=meta
    )
    assert record["runtime_metadata"] == meta
    # runtime_metadata is a side field: it does not perturb the content hash
    assert record["input_hash"] == hash_content("p")
    assert record["output_hash"] == hash_content("a")
    validate_record(record)


def test_26_factory_omits_runtime_metadata_when_absent_or_empty():
    session = PipelineSession()
    default = session.add_agent_step(**_STEP_KW, input="p", output="a")
    empty = session.add_tool_invocation(
        **_TOOL_KW, input="i", output="o", runtime_metadata={}
    )
    assert "runtime_metadata" not in default
    assert "runtime_metadata" not in empty
