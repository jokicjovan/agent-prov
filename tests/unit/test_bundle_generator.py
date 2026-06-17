"""Tests for BundleGenerator — session serialization, hash sealing, file output.

Fifteen test cases covering:
  1    generate() output validates against pipeline_bundle.schema.json.
  2    bundle_id is a fresh lowercase-hex UUID.
  3    record_type discriminator is "pipeline_bundle".
  4    protocol_version matches the session.
  5    pipeline_id matches the session.
  6    session_id matches the session.
  7    disclosure_presented defaults to False.
  8    disclosure_presented=True is propagated.
  9    records snapshot matches session.records exactly.
  10   bundle_hash verifies: recomputing compute_bundle_hash matches the stored value.
  11   Two generate() calls produce distinct bundle_id values.
  12   Empty session raises ValueError.
  13   to_file writes a readable JSON file whose content matches generate().
  14   to_file returns the same bundle dict that was written.
  15   Bundle with mixed record types (agent_step + tool_invocation) validates.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from _helpers import PIPELINE_BUNDLE_SCHEMA, validator
from agent_prov.bundle_generator import BundleGenerator, compute_bundle_hash
from agent_prov.session import PipelineSession


_BUNDLE_VALIDATOR = validator(PIPELINE_BUNDLE_SCHEMA)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

HASH_A = "a" * 64
HASH_B = "b" * 64
UUID_1 = "11111111-1111-1111-1111-111111111111"
UUID_2 = "22222222-2222-2222-2222-222222222222"


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------


def _agent_step(record_id: str, session: PipelineSession, **kw: Any) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "record_type": "agent_step",
        "protocol_version": session.protocol_version,
        "pipeline_id": session.pipeline_id,
        "session_id": session.session_id,
        "agent_id": "researcher",
        "model_id": "claude-opus-4-7",
        "model_version": "20260101",
        "timestamp_start": "2026-05-11T10:00:00Z",
        "timestamp_end": "2026-05-11T10:00:01Z",
        "input_hash": HASH_A,
        "output_hash": HASH_B,
        "status": "success",
        "reference_data_id": None,
        "parent_record_id": None,
        **kw,
    }


def _tool_invocation(record_id: str, session: PipelineSession, **kw: Any) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "record_type": "tool_invocation",
        "protocol_version": session.protocol_version,
        "pipeline_id": session.pipeline_id,
        "session_id": session.session_id,
        "agent_id": "researcher",
        "tool_name": "web_search",
        "tool_version": "1.0.0",
        "timestamp_start": "2026-05-11T10:00:01Z",
        "timestamp_end": "2026-05-11T10:00:02Z",
        "input_hash": HASH_A,
        "output_hash": HASH_B,
        "status": "success",
        "reference_data_id": None,
        "parent_record_id": UUID_1,
        **kw,
    }


def _session_with_one_step() -> PipelineSession:
    session = PipelineSession()
    session.add_record(_agent_step(UUID_1, session))
    return session


# ---------------------------------------------------------------------------
# Tests 1-11 — generate()
# ---------------------------------------------------------------------------


def test_01_generate_validates_against_pipeline_bundle_schema():
    bundle = BundleGenerator(_session_with_one_step()).generate()
    assert _BUNDLE_VALIDATOR.is_valid(bundle), list(_BUNDLE_VALIDATOR.iter_errors(bundle))


def test_02_bundle_id_is_a_fresh_lowercase_uuid():
    bundle = BundleGenerator(_session_with_one_step()).generate()
    assert UUID_RE.match(bundle["bundle_id"]), bundle["bundle_id"]


def test_03_record_type_discriminator_is_pipeline_bundle():
    bundle = BundleGenerator(_session_with_one_step()).generate()
    assert bundle["record_type"] == "pipeline_bundle"


def test_04_protocol_version_matches_session():
    session = PipelineSession(protocol_version="1.2.3")
    session.add_record(_agent_step(UUID_1, session))
    bundle = BundleGenerator(session).generate()
    assert bundle["protocol_version"] == "1.2.3"


def test_05_pipeline_id_matches_session():
    session = _session_with_one_step()
    bundle = BundleGenerator(session).generate()
    assert bundle["pipeline_id"] == session.pipeline_id


def test_06_session_id_matches_session():
    session = _session_with_one_step()
    bundle = BundleGenerator(session).generate()
    assert bundle["session_id"] == session.session_id


def test_07_disclosure_presented_defaults_to_false():
    bundle = BundleGenerator(_session_with_one_step()).generate()
    assert bundle["disclosure_presented"] is False


def test_08_disclosure_presented_true_is_propagated():
    bundle = BundleGenerator(_session_with_one_step(), disclosure_presented=True).generate()
    assert bundle["disclosure_presented"] is True


def test_09_records_snapshot_matches_session_records():
    session = PipelineSession()
    r1 = _agent_step(UUID_1, session)
    r2 = _agent_step(UUID_2, session, parent_record_id=UUID_1)
    session.add_record(r1)
    session.add_record(r2)
    bundle = BundleGenerator(session).generate()
    assert bundle["records"] == [r1, r2]


def test_10_bundle_hash_verifies_against_compute_bundle_hash():
    bundle = BundleGenerator(_session_with_one_step()).generate()
    expected = compute_bundle_hash(bundle)
    assert bundle["bundle_hash"] == expected


def test_11_two_generate_calls_produce_distinct_bundle_ids():
    gen = BundleGenerator(_session_with_one_step())
    a = gen.generate()
    b = gen.generate()
    assert a["bundle_id"] != b["bundle_id"]


# ---------------------------------------------------------------------------
# Test 12 — empty session guard
# ---------------------------------------------------------------------------


def test_12_empty_session_raises_value_error():
    with pytest.raises(ValueError, match="empty session"):
        BundleGenerator(PipelineSession()).generate()


# ---------------------------------------------------------------------------
# Tests 13-14 — to_file()
# ---------------------------------------------------------------------------


def test_13_to_file_writes_a_readable_json_file_matching_generate(tmp_path: pathlib.Path):
    session = _session_with_one_step()
    out = tmp_path / "bundle.json"
    BundleGenerator(session).to_file(out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert _BUNDLE_VALIDATOR.is_valid(written)
    assert written["pipeline_id"] == session.pipeline_id


def test_14_to_file_returns_the_same_bundle_written_to_disk(tmp_path: pathlib.Path):
    out = tmp_path / "bundle.json"
    returned = BundleGenerator(_session_with_one_step()).to_file(out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert returned == written


# ---------------------------------------------------------------------------
# Test 15 — mixed record types
# ---------------------------------------------------------------------------


def test_15_mixed_record_types_validate():
    session = PipelineSession()
    session.add_record(_agent_step(UUID_1, session))
    session.add_record(_tool_invocation(UUID_2, session))
    bundle = BundleGenerator(session).generate()
    assert _BUNDLE_VALIDATOR.is_valid(bundle), list(_BUNDLE_VALIDATOR.iter_errors(bundle))
