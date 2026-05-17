"""Tests for HumanReview — decision capture, hash conventions, schema shape.

Covers:
  Decision API: approved / edited / rejected / escalated branches each produce
                a schema-valid record with the right output_after_hash convention.
  Error cases: no decision committed, double decision, edit-equals-before,
                missing parent record, empty reviewer fields.
  Plumbing:    justification hashing (optional), parent_record_id wiring,
                body exception suppresses emission, ISO 8601 timestamp format.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from middleware.core import hash_content
from middleware.hitl import HITLError, HumanReview


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$")


# ---------------------------------------------------------------------------
# Schema validator (cross-$ref aware, mirrors test_schemas.py setup)
# ---------------------------------------------------------------------------

SCHEMAS_DIR = pathlib.Path(__file__).resolve().parent.parent / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


HUMAN_INTERVENTION_SCHEMA = _load("human_intervention.schema.json")
REGISTRY = Registry().with_resources(
    [(HUMAN_INTERVENTION_SCHEMA["$id"], Resource.from_contents(HUMAN_INTERVENTION_SCHEMA))]
)
HITL_VALIDATOR = Draft202012Validator(HUMAN_INTERVENTION_SCHEMA, registry=REGISTRY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class StubSession:
    pipeline_id: str = "11111111-1111-1111-1111-111111111111"
    session_id: str = "22222222-2222-2222-2222-222222222222"
    protocol_version: str = "0.1.0"
    last_record_id: str | None = "33333333-3333-3333-3333-333333333333"
    records: list[dict[str, Any]] = field(default_factory=list)

    def add_record(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        self.last_record_id = record["record_id"]


BEFORE = {"summary": "Draft summary of EU AI Act Art. 12 obligations."}
EDITED = {"summary": "Final summary of EU AI Act Art. 12 obligations (edited)."}


def _make_review(session: StubSession, **overrides: Any) -> HumanReview:
    defaults: dict[str, Any] = dict(
        session=session,
        reviewer_id=["alice@example.com"],
        reviewer_role="editor",
        output_before=BEFORE,
    )
    defaults.update(overrides)
    return HumanReview(**defaults)


# ---------------------------------------------------------------------------
# Decision branches — output shape + schema validity
# ---------------------------------------------------------------------------


def test_approve_emits_schema_valid_record_with_after_equal_to_before():
    session = StubSession()
    with _make_review(session) as review:
        review.approve()

    assert len(session.records) == 1
    r = session.records[0]
    HITL_VALIDATOR.validate(r)

    assert r["record_type"] == "human_intervention"
    assert r["action_type"] == "approved"
    assert r["output_before_hash"] == r["output_after_hash"]
    assert r["output_before_hash"] == hash_content(BEFORE)
    assert UUID_RE.match(r["record_id"])
    assert SHA256_RE.match(r["output_before_hash"])
    assert "justification_hash" not in r
    assert review.record is r


def test_edit_emits_record_with_distinct_after_hash():
    session = StubSession()
    with _make_review(session) as review:
        review.edit(EDITED)

    r = session.records[0]
    HITL_VALIDATOR.validate(r)

    assert r["action_type"] == "edited"
    assert r["output_before_hash"] == hash_content(BEFORE)
    assert r["output_after_hash"] == hash_content(EDITED)
    assert r["output_after_hash"] != r["output_before_hash"]


def test_reject_emits_record_with_null_after_hash():
    session = StubSession()
    with _make_review(session) as review:
        review.reject()

    r = session.records[0]
    HITL_VALIDATOR.validate(r)
    assert r["action_type"] == "rejected"
    assert r["output_after_hash"] is None


def test_escalate_emits_record_with_null_after_hash():
    session = StubSession()
    with _make_review(session) as review:
        review.escalate()

    r = session.records[0]
    HITL_VALIDATOR.validate(r)
    assert r["action_type"] == "escalated"
    assert r["output_after_hash"] is None


# ---------------------------------------------------------------------------
# Justification (optional)
# ---------------------------------------------------------------------------


def test_justification_is_hashed_when_supplied():
    session = StubSession()
    rationale = "Edited to remove unsupported claim about Art. 12(4)."
    with _make_review(session) as review:
        review.edit(EDITED, justification=rationale)

    r = session.records[0]
    HITL_VALIDATOR.validate(r)
    assert r["justification_hash"] == hash_content(rationale)
    assert SHA256_RE.match(r["justification_hash"])


def test_justification_omitted_when_not_supplied():
    session = StubSession()
    with _make_review(session) as review:
        review.reject()

    assert "justification_hash" not in session.records[0]


# ---------------------------------------------------------------------------
# Parent record wiring
# ---------------------------------------------------------------------------


def test_parent_record_id_taken_from_session_last_record():
    session = StubSession(last_record_id="44444444-4444-4444-4444-444444444444")
    with _make_review(session) as review:
        review.approve()

    assert session.records[0]["parent_record_id"] == "44444444-4444-4444-4444-444444444444"


def test_emission_fails_when_no_prior_record_exists():
    session = StubSession(last_record_id=None)
    with pytest.raises(HITLError, match="non-null parent_record_id"):
        with _make_review(session) as review:
            review.approve()
    assert session.records == []


# ---------------------------------------------------------------------------
# Flow violations
# ---------------------------------------------------------------------------


def test_no_decision_raises_on_exit():
    session = StubSession()
    with pytest.raises(HITLError, match="without a decision"):
        with _make_review(session):
            pass
    assert session.records == []


def test_double_decision_raises():
    session = StubSession()
    with pytest.raises(HITLError, match="already committed"):
        with _make_review(session) as review:
            review.approve()
            review.reject()


def test_edit_with_unchanged_content_raises():
    session = StubSession()
    with pytest.raises(HITLError, match="output_after to differ"):
        with _make_review(session) as review:
            review.edit(BEFORE)
    assert session.records == []


def test_body_exception_suppresses_emission():
    session = StubSession()
    with pytest.raises(ValueError):
        with _make_review(session) as review:
            review.approve()
            raise ValueError("reviewer changed their mind")
    # Decision was committed but the body raised — no record should leak out.
    assert session.records == []


# ---------------------------------------------------------------------------
# Constructor guards
# ---------------------------------------------------------------------------


def test_empty_reviewer_id_rejected():
    session = StubSession()
    with pytest.raises(HITLError, match="reviewer_id"):
        HumanReview(
            session=session,
            reviewer_id=[],
            reviewer_role="editor",
            output_before=BEFORE,
        )


def test_empty_reviewer_role_rejected():
    session = StubSession()
    with pytest.raises(HITLError, match="reviewer_role"):
        HumanReview(
            session=session,
            reviewer_id=["alice@example.com"],
            reviewer_role="",
            output_before=BEFORE,
        )


def test_multiple_reviewers_preserved_in_record():
    session = StubSession()
    reviewers = ["alice@example.com", "bob@example.com"]
    with HumanReview(
        session=session,
        reviewer_id=reviewers,
        reviewer_role="compliance_officer",
        output_before=BEFORE,
    ) as review:
        review.approve()

    r = session.records[0]
    HITL_VALIDATOR.validate(r)
    assert r["reviewer_id"] == reviewers
    assert r["reviewer_role"] == "compliance_officer"


# ---------------------------------------------------------------------------
# Timestamp + session metadata
# ---------------------------------------------------------------------------


def test_intervention_timestamp_is_iso8601_utc():
    session = StubSession()
    with _make_review(session) as review:
        review.approve()

    ts = session.records[0]["intervention_timestamp"]
    assert ISO8601_RE.match(ts), ts


def test_record_inherits_session_identifiers_and_protocol_version():
    session = StubSession(
        pipeline_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        protocol_version="0.1.0",
    )
    with _make_review(session) as review:
        review.approve()

    r = session.records[0]
    assert r["pipeline_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert r["session_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert r["protocol_version"] == "0.1.0"


def test_session_last_record_id_advances_after_emission():
    session = StubSession(last_record_id="33333333-3333-3333-3333-333333333333")
    with _make_review(session) as review:
        review.approve()

    new_record_id = session.records[0]["record_id"]
    assert session.last_record_id == new_record_id
    assert session.last_record_id != "33333333-3333-3333-3333-333333333333"
