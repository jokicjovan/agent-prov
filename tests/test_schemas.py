"""Schema validation and bundle-hash unit tests.

Twelve test cases covering:
  1-4  Happy-path validation for each of the four record schemas.
  5    Missing required field rejected (schema-level).
  6    additionalProperties: false rejects an unknown field (schema-level).
  7    Invalid sha256_hex pattern rejected (schema-level).
  8    Wrong record_type discriminator rejected (schema-level).
  9    HITL conditional: 'edited' requires output_after_hash != output_before_hash (unit-test layer).
  10   HITL conditional: 'rejected'/'escalated' require output_after_hash is null (unit-test layer).
  11   timestamp_end >= timestamp_start enforced (unit-test layer).
  12   canonical_json_sha256 + compute_bundle_hash properties:
        determinism, key-order independence, content sensitivity, bundle_hash exclusion.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from middleware.bundle_generator import canonical_json_sha256, compute_bundle_hash


# ---------------------------------------------------------------------------
# Schema loading & cross-schema $ref registry
# ---------------------------------------------------------------------------

SCHEMAS_DIR = pathlib.Path(__file__).resolve().parent.parent / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


AGENT_STEP_SCHEMA = _load("agent_step.schema.json")
TOOL_INVOCATION_SCHEMA = _load("tool_invocation.schema.json")
HUMAN_INTERVENTION_SCHEMA = _load("human_intervention.schema.json")
PIPELINE_BUNDLE_SCHEMA = _load("pipeline_bundle.schema.json")

REGISTRY = Registry().with_resources(
    [
        (AGENT_STEP_SCHEMA["$id"], Resource.from_contents(AGENT_STEP_SCHEMA)),
        (TOOL_INVOCATION_SCHEMA["$id"], Resource.from_contents(TOOL_INVOCATION_SCHEMA)),
        (HUMAN_INTERVENTION_SCHEMA["$id"], Resource.from_contents(HUMAN_INTERVENTION_SCHEMA)),
        (PIPELINE_BUNDLE_SCHEMA["$id"], Resource.from_contents(PIPELINE_BUNDLE_SCHEMA)),
    ]
)


def _validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema, registry=REGISTRY)


def _is_valid(schema: dict, instance: Any) -> bool:
    return _validator(schema).is_valid(instance)


# ---------------------------------------------------------------------------
# Fixtures (record builders)
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "0.1.0"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
UUID_AGENT_STEP = "11111111-1111-1111-1111-111111111111"
UUID_TOOL = "22222222-2222-2222-2222-222222222222"
UUID_HITL = "33333333-3333-3333-3333-333333333333"
UUID_PIPELINE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UUID_SESSION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
UUID_BUNDLE = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TS_START = "2026-05-09T10:00:00Z"
TS_END = "2026-05-09T10:00:01Z"
TS_BEFORE_START = "2026-05-09T09:59:59Z"


def make_agent_step(**overrides: Any) -> dict:
    record = {
        "record_id": UUID_AGENT_STEP,
        "record_type": "agent_step",
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_id": UUID_PIPELINE,
        "session_id": UUID_SESSION,
        "agent_id": "researcher-agent",
        "model_id": "claude-opus-4-7",
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


def make_tool_invocation(**overrides: Any) -> dict:
    record = {
        "record_id": UUID_TOOL,
        "record_type": "tool_invocation",
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_id": UUID_PIPELINE,
        "session_id": UUID_SESSION,
        "agent_id": "researcher-agent",
        "tool_name": "web_search",
        "tool_version": "1.0.0",
        "timestamp_start": TS_START,
        "timestamp_end": TS_END,
        "input_hash": HASH_A,
        "output_hash": HASH_B,
        "reference_data_id": None,
        "parent_record_id": UUID_AGENT_STEP,
    }
    record.update(overrides)
    return record


def make_human_intervention(action: str = "approved", **overrides: Any) -> dict:
    if action == "approved":
        before, after = HASH_A, HASH_A
    elif action == "edited":
        before, after = HASH_A, HASH_B
    else:  # rejected / escalated
        before, after = HASH_A, None
    record = {
        "record_id": UUID_HITL,
        "record_type": "human_intervention",
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_id": UUID_PIPELINE,
        "session_id": UUID_SESSION,
        "reviewer_id": ["reviewer-007"],
        "reviewer_role": "editor",
        "action_type": action,
        "output_before_hash": before,
        "output_after_hash": after,
        "intervention_timestamp": TS_END,
        "parent_record_id": UUID_AGENT_STEP,
    }
    record.update(overrides)
    return record


def make_bundle(records: list[dict] | None = None, **overrides: Any) -> dict:
    if records is None:
        records = [make_agent_step(), make_human_intervention("approved")]
    bundle = {
        "bundle_id": UUID_BUNDLE,
        "record_type": "pipeline_bundle",
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_id": UUID_PIPELINE,
        "session_id": UUID_SESSION,
        "created_at": TS_END,
        "disclosure_presented": True,
        "records": records,
        "bundle_hash": HASH_C,
    }
    bundle.update(overrides)
    bundle["bundle_hash"] = compute_bundle_hash(bundle)
    return bundle


# ---------------------------------------------------------------------------
# Conditional validators (rules deferred from the schema layer)
# ---------------------------------------------------------------------------


def assert_hitl_consistent(record: dict) -> None:
    a = record["action_type"]
    before = record["output_before_hash"]
    after = record["output_after_hash"]
    if a == "approved":
        assert after == before, "approved: output_after_hash must equal output_before_hash"
    elif a == "edited":
        assert after is not None and after != before, (
            "edited: output_after_hash must be non-null and differ from output_before_hash"
        )
    elif a in ("rejected", "escalated"):
        assert after is None, f"{a}: output_after_hash must be null"
    else:
        raise AssertionError(f"unknown action_type: {a}")


def assert_timestamps_ordered(record: dict) -> None:
    if "timestamp_start" in record and "timestamp_end" in record:
        assert record["timestamp_end"] >= record["timestamp_start"], (
            "timestamp_end must be >= timestamp_start"
        )


# ---------------------------------------------------------------------------
# Tests 1-4 — happy-path schema validation for each record type
# ---------------------------------------------------------------------------


def test_01_agent_step_happy_path_validates():
    assert _is_valid(AGENT_STEP_SCHEMA, make_agent_step())


def test_02_tool_invocation_happy_path_validates():
    assert _is_valid(TOOL_INVOCATION_SCHEMA, make_tool_invocation())


def test_03_human_intervention_happy_path_validates_for_each_action_type():
    for action in ("approved", "rejected", "edited", "escalated"):
        record = make_human_intervention(action)
        assert _is_valid(HUMAN_INTERVENTION_SCHEMA, record), action
        assert_hitl_consistent(record)


def test_04_pipeline_bundle_happy_path_validates():
    bundle = make_bundle(
        records=[
            make_agent_step(),
            make_tool_invocation(parent_record_id=UUID_AGENT_STEP),
            make_human_intervention("edited", parent_record_id=UUID_AGENT_STEP),
        ]
    )
    assert _is_valid(PIPELINE_BUNDLE_SCHEMA, bundle)


# ---------------------------------------------------------------------------
# Tests 5-8 — schema-level negative cases
# ---------------------------------------------------------------------------


def test_05_missing_required_field_is_rejected():
    record = make_agent_step()
    del record["model_id"]
    assert not _is_valid(AGENT_STEP_SCHEMA, record)


def test_06_additional_properties_false_rejects_unknown_field():
    record = make_agent_step()
    record["unknown_extra_field"] = "should-be-rejected"
    assert not _is_valid(AGENT_STEP_SCHEMA, record)


def test_07_invalid_sha256_hex_pattern_is_rejected():
    record = make_agent_step(input_hash="NOT_A_VALID_HASH")
    assert not _is_valid(AGENT_STEP_SCHEMA, record)
    record_uppercase = make_agent_step(input_hash="A" * 64)
    assert not _is_valid(AGENT_STEP_SCHEMA, record_uppercase), (
        "uppercase hex must be rejected — protocol uses lowercase canonical form"
    )


def test_08_wrong_record_type_discriminator_is_rejected():
    record = make_agent_step(record_type="tool_invocation")
    assert not _is_valid(AGENT_STEP_SCHEMA, record)


# ---------------------------------------------------------------------------
# Tests 9-11 — conditional rules deferred from the schema layer
# ---------------------------------------------------------------------------


def test_09_hitl_edited_requires_after_hash_to_differ_from_before():
    bad = make_human_intervention("edited", output_after_hash=HASH_A)
    assert _is_valid(HUMAN_INTERVENTION_SCHEMA, bad), (
        "schema alone accepts this; the conditional belongs in the application layer"
    )
    with pytest.raises(AssertionError):
        assert_hitl_consistent(bad)


def test_10_hitl_rejected_or_escalated_requires_null_after_hash():
    for action in ("rejected", "escalated"):
        bad = make_human_intervention(action, output_after_hash=HASH_B)
        assert _is_valid(HUMAN_INTERVENTION_SCHEMA, bad), action
        with pytest.raises(AssertionError):
            assert_hitl_consistent(bad)


def test_11_timestamp_end_before_timestamp_start_is_rejected_at_unit_layer():
    bad = make_agent_step(timestamp_end=TS_BEFORE_START)
    assert _is_valid(AGENT_STEP_SCHEMA, bad), (
        "schema alone accepts this; the ordering constraint belongs in the application layer"
    )
    with pytest.raises(AssertionError):
        assert_timestamps_ordered(bad)


# ---------------------------------------------------------------------------
# Test 12 — canonical_json_sha256 + compute_bundle_hash properties
# ---------------------------------------------------------------------------


def test_12_canonical_hash_properties():
    obj_a = {"b": 2, "a": 1, "c": [3, 2, 1]}
    obj_a_reordered = {"c": [3, 2, 1], "a": 1, "b": 2}
    obj_b = {"b": 2, "a": 1, "c": [3, 2, 0]}

    # determinism: same input twice → same hash
    assert canonical_json_sha256(obj_a) == canonical_json_sha256(obj_a)

    # key-order independence: insertion order must not affect the hash
    assert canonical_json_sha256(obj_a) == canonical_json_sha256(obj_a_reordered)

    # content sensitivity: changing one element must change the hash
    assert canonical_json_sha256(obj_a) != canonical_json_sha256(obj_b)

    # bundle_hash exclusion: compute_bundle_hash ignores any pre-existing
    # bundle_hash field, so the value computed before and after assignment matches
    bundle = make_bundle()
    digest_with_hash = compute_bundle_hash(bundle)
    bundle_no_hash = {k: v for k, v in bundle.items() if k != "bundle_hash"}
    digest_without_hash = compute_bundle_hash(bundle_no_hash)
    assert digest_with_hash == digest_without_hash
    assert bundle["bundle_hash"] == digest_with_hash, (
        "make_bundle must seal the bundle with a bundle_hash matching compute_bundle_hash"
    )

    # tamper detection: mutating any record breaks the seal
    tampered = copy.deepcopy(bundle)
    tampered["records"][0]["output_hash"] = HASH_C
    assert compute_bundle_hash(tampered) != bundle["bundle_hash"]
