"""Tests for the single validation surface (middleware.validation).

Covers validate_record (structural + conditional, per record type) and
validate_bundle (bundle structure + per-record conditionals), plus the
unified ProtocolValidationError exception type.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_prov.bundle_generator import compute_bundle_hash
from agent_prov.validation import (
    ProtocolValidationError,
    validate_bundle,
    validate_record,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
UUID_AGENT = "11111111-1111-1111-1111-111111111111"
UUID_PIPELINE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UUID_SESSION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
UUID_BUNDLE = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TS_START = "2026-05-09T10:00:00Z"
TS_END = "2026-05-09T10:00:01Z"


def make_agent_step(**overrides: Any) -> dict:
    record = {
        "record_id": UUID_AGENT,
        "record_type": "agent_step",
        "protocol_version": "0.1.0",
        "pipeline_id": UUID_PIPELINE,
        "session_id": UUID_SESSION,
        "agent_id": "researcher",
        "model_id": "claude-opus-4-8",
        "model_version": "20260101",
        "timestamp_start": TS_START,
        "timestamp_end": TS_END,
        "input_hash": HASH_A,
        "output_hash": HASH_B,
        "reference_data_id": None,
        "parent_record_id": None,
    }
    record.update(overrides)
    return record


def make_hitl(action: str = "approved", **overrides: Any) -> dict:
    after = {"approved": HASH_A, "edited": HASH_B}.get(action, None)
    record = {
        "record_id": "33333333-3333-3333-3333-333333333333",
        "record_type": "human_intervention",
        "protocol_version": "0.1.0",
        "pipeline_id": UUID_PIPELINE,
        "session_id": UUID_SESSION,
        "reviewer_id": ["reviewer-007"],
        "reviewer_role": "editor",
        "action_type": action,
        "output_before_hash": HASH_A,
        "output_after_hash": after,
        "intervention_timestamp": TS_END,
        "parent_record_id": UUID_AGENT,
    }
    record.update(overrides)
    return record


def make_bundle(records: list[dict]) -> dict:
    bundle = {
        "bundle_id": UUID_BUNDLE,
        "record_type": "pipeline_bundle",
        "protocol_version": "0.1.0",
        "pipeline_id": UUID_PIPELINE,
        "session_id": UUID_SESSION,
        "created_at": TS_END,
        "disclosure_presented": True,
        "records": records,
        "bundle_hash": "",
    }
    bundle["bundle_hash"] = compute_bundle_hash(bundle)
    return bundle


# --------------------------------------------------------------- validate_record


def test_validate_record_accepts_valid_records():
    for action in ("approved", "edited", "rejected", "escalated"):
        validate_record(make_hitl(action))
    validate_record(make_agent_step())


def test_validate_record_rejects_structural_error():
    bad = make_agent_step()
    del bad["model_id"]
    with pytest.raises(ProtocolValidationError):
        validate_record(bad)


def test_validate_record_rejects_conditional_error():
    with pytest.raises(ProtocolValidationError):
        validate_record(make_agent_step(timestamp_end="2026-05-09T09:00:00Z"))
    with pytest.raises(ProtocolValidationError):
        validate_record(make_hitl("rejected", output_after_hash=HASH_B))


def test_validate_record_rejects_unknown_record_type():
    with pytest.raises(ProtocolValidationError):
        validate_record(make_agent_step(record_type="not_a_record"))


def test_validate_record_rejects_non_dict():
    with pytest.raises(ProtocolValidationError):
        validate_record(["not", "a", "record"])


# --------------------------------------------------------------- validate_bundle


def test_validate_bundle_accepts_valid_bundle():
    validate_bundle(make_bundle([make_agent_step(), make_hitl("approved")]))


def test_validate_bundle_rejects_structural_error():
    bundle = make_bundle([make_agent_step()])
    del bundle["disclosure_presented"]
    with pytest.raises(ProtocolValidationError):
        validate_bundle(bundle)


def test_validate_bundle_rejects_record_conditional_error_with_index():
    # Structurally valid records, but the second one breaks a conditional rule.
    good = make_agent_step()
    bad = make_hitl("approved", output_after_hash=HASH_B)  # approved must equal before
    bundle = make_bundle([good, bad])
    with pytest.raises(ProtocolValidationError, match=r"records\[1\]"):
        validate_bundle(bundle)
