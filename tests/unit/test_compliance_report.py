"""Tests for reporting.compliance_report.

Covers:
  1   OBLIGATION_MAP keys match the four declared record_types.
  2   Every clause referenced by OBLIGATION_MAP has a CLAUSE_DESCRIPTION entry.
  3   Constructor rejects non-dict input.
  4   Constructor rejects a non-pipeline_bundle dict.
  5   Constructor rejects a bundle missing 'records'.
  6   coverage() returns a key for every clause in CLAUSE_DESCRIPTION.
  7   coverage() lists the bundle_id under Art. 50(1) when disclosure_presented is true.
  8   coverage() includes Art. 14(4)(c)/(d)/(e) for a bundle carrying HITL records.
  9   coverage() omits Art. 50(1) when disclosure_presented is false.
  10  Null-valued field (reference_data_id) does not satisfy its mapped clause.
  11  Empty reviewer_id array does not satisfy Art. 12(3)(d) / Art. 14(5).
  12  to_pdf writes a non-empty %PDF-prefixed file.
  13  CLI: `python -m reporting bundle.json out.pdf` produces a PDF.

Fixtures are constructed inline from literal constants so the tests do not
depend on demo artifacts (which are regenerated whenever a demo changes).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Any

import pytest

from reporting import ComplianceReport
from reporting.obligations import CLAUSE_DESCRIPTION, OBLIGATION_MAP


PROTOCOL_VERSION = "0.1.0"
BUNDLE_ID = "7f4bcd85-a2ea-4392-89fb-30fee99b2f8b"
PIPELINE_ID = "951e06e5-f3b3-443f-ba1e-45e9416e1be3"
SESSION_ID = "00801809-0aef-484f-a16c-0072cf9c84a5"

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_BEFORE = "c" * 64
HASH_AFTER = "d" * 64
HASH_JUSTIFICATION = "e" * 64
BUNDLE_HASH = "f" * 64


# ---------------------------------------------------------------------------
# Record / bundle builders -- each call returns a fresh, independent dict
# ---------------------------------------------------------------------------


def _agent_step(record_id: str, agent_id: str, **overrides: Any) -> dict[str, Any]:
    record = {
        "record_id": record_id,
        "record_type": "agent_step",
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_id": PIPELINE_ID,
        "session_id": SESSION_ID,
        "agent_id": agent_id,
        "model_id": "fake-model",
        "model_version": "fake-model",
        "timestamp_start": "2026-05-19T15:20:31.165824Z",
        "timestamp_end": "2026-05-19T15:20:31.166667Z",
        "input_hash": HASH_A,
        "output_hash": HASH_B,
        "reference_data_id": None,
        "parent_record_id": None,
    }
    record.update(overrides)
    return record


def _tool_invocation(record_id: str, **overrides: Any) -> dict[str, Any]:
    record = {
        "record_id": record_id,
        "record_type": "tool_invocation",
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_id": PIPELINE_ID,
        "session_id": SESSION_ID,
        "agent_id": "researcher",
        "tool_name": "web_search",
        "tool_version": "unversioned",
        "timestamp_start": "2026-05-19T15:20:31.165824Z",
        "timestamp_end": "2026-05-19T15:20:31.166667Z",
        "input_hash": HASH_A,
        "output_hash": HASH_B,
        "reference_data_id": None,
        "parent_record_id": None,
    }
    record.update(overrides)
    return record


def _human_intervention(
    record_id: str, *, action_type: str = "edited", **overrides: Any
) -> dict[str, Any]:
    record = {
        "record_id": record_id,
        "record_type": "human_intervention",
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_id": PIPELINE_ID,
        "session_id": SESSION_ID,
        "reviewer_id": ["reviewer:editor-01"],
        "reviewer_role": "editor",
        "action_type": action_type,
        "output_before_hash": HASH_BEFORE,
        "output_after_hash": HASH_AFTER,
        "intervention_timestamp": "2026-05-19T15:20:31.167137Z",
        "parent_record_id": None,
        "justification_hash": HASH_JUSTIFICATION,
    }
    record.update(overrides)
    return record


def _bundle(records: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    bundle = {
        "bundle_id": BUNDLE_ID,
        "record_type": "pipeline_bundle",
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_id": PIPELINE_ID,
        "session_id": SESSION_ID,
        "created_at": "2026-05-19T15:20:31.168895Z",
        "disclosure_presented": True,
        "records": records,
        "bundle_hash": BUNDLE_HASH,
    }
    bundle.update(overrides)
    return bundle


@pytest.fixture
def doc_review_bundle() -> dict[str, Any]:
    """A summarize -> HITL(edit) -> finalize -> HITL(approve) bundle."""
    return _bundle(
        [
            _agent_step("7492c13e-b1a6-4b10-968b-47e76dadb452", "summarizer"),
            _human_intervention(
                "decfafe1-9524-42c3-b293-f6dae180ca4a", action_type="edited"
            ),
            _agent_step("73b207e4-ad57-430d-92da-41fcfb57abaf", "finalizer"),
            _human_intervention(
                "8b226e3b-83b0-4685-b4b7-783502031168",
                action_type="approved",
                reviewer_id=["reviewer:compliance-07"],
                reviewer_role="compliance_officer",
                output_after_hash=HASH_BEFORE,
            ),
        ]
    )


@pytest.fixture
def research_bundle() -> dict[str, Any]:
    """A tool_invocation + two agent_step bundle, no HITL, no reference data."""
    return _bundle(
        [
            _tool_invocation("1a2b3c4d-0001-4000-8000-000000000001"),
            _agent_step("1a2b3c4d-0002-4000-8000-000000000002", "researcher"),
            _agent_step("1a2b3c4d-0003-4000-8000-000000000003", "writer"),
        ]
    )


def test_obligation_map_covers_all_record_types() -> None:
    assert set(OBLIGATION_MAP) == {
        "agent_step",
        "tool_invocation",
        "human_intervention",
        "pipeline_bundle",
    }


def test_every_mapped_clause_has_a_description() -> None:
    referenced = {
        clause
        for record_type in OBLIGATION_MAP.values()
        for clauses in record_type.values()
        for clause in clauses
    }
    missing = referenced - set(CLAUSE_DESCRIPTION)
    assert not missing, f"clauses missing from CLAUSE_DESCRIPTION: {missing}"


def test_constructor_rejects_non_dict() -> None:
    with pytest.raises(TypeError):
        ComplianceReport([])  # type: ignore[arg-type]


def test_constructor_rejects_wrong_record_type() -> None:
    with pytest.raises(ValueError, match="pipeline_bundle"):
        ComplianceReport({"record_type": "agent_step", "records": []})


def test_constructor_rejects_missing_records(doc_review_bundle: dict) -> None:
    bundle = {k: v for k, v in doc_review_bundle.items() if k != "records"}
    with pytest.raises(ValueError, match="records"):
        ComplianceReport(bundle)


def test_coverage_has_every_clause(doc_review_bundle: dict) -> None:
    coverage = ComplianceReport(doc_review_bundle).coverage()
    assert set(coverage) == set(CLAUSE_DESCRIPTION)


def test_coverage_links_disclosure_to_art_50_1(doc_review_bundle: dict) -> None:
    assert doc_review_bundle["disclosure_presented"] is True
    coverage = ComplianceReport(doc_review_bundle).coverage()
    assert doc_review_bundle["bundle_id"] in coverage["Art. 50(1)"]


def test_coverage_picks_up_hitl_clauses(doc_review_bundle: dict) -> None:
    coverage = ComplianceReport(doc_review_bundle).coverage()
    for clause in ("Art. 14(4)(c)", "Art. 14(4)(d)", "Art. 14(4)(e)"):
        assert coverage[clause], f"{clause} should be satisfied by HITL records"


def test_disclosure_false_drops_art_50_1(doc_review_bundle: dict) -> None:
    bundle = dict(doc_review_bundle)
    bundle["disclosure_presented"] = False
    coverage = ComplianceReport(bundle).coverage()
    assert bundle["bundle_id"] not in coverage["Art. 50(1)"]


def test_null_reference_data_id_does_not_satisfy_clause(research_bundle: dict) -> None:
    coverage = ComplianceReport(research_bundle).coverage()
    for record in research_bundle["records"]:
        if record.get("reference_data_id") is None:
            assert record["record_id"] not in coverage["Art. 12(3)(b)"], (
                "null reference_data_id should not satisfy Art. 12(3)(b)"
            )


def test_empty_reviewer_id_does_not_satisfy_clauses(doc_review_bundle: dict) -> None:
    bundle = json.loads(json.dumps(doc_review_bundle))
    hitl = next(r for r in bundle["records"] if r["record_type"] == "human_intervention")
    hitl["reviewer_id"] = []
    coverage = ComplianceReport(bundle).coverage()
    assert hitl["record_id"] not in coverage["Art. 12(3)(d)"]
    assert hitl["record_id"] not in coverage["Art. 14(5)"]


def test_to_pdf_writes_pdf_file(tmp_path: pathlib.Path, doc_review_bundle: dict) -> None:
    out = tmp_path / "report.pdf"
    returned = ComplianceReport(doc_review_bundle).to_pdf(out)
    assert returned == out.resolve()
    assert out.exists()
    header = out.read_bytes()[:5]
    assert header == b"%PDF-", f"file does not start with %PDF- (got {header!r})"
    assert out.stat().st_size > 1000


def test_cli_renders_pdf(tmp_path: pathlib.Path, doc_review_bundle: dict) -> None:
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(doc_review_bundle), encoding="utf-8")
    out = tmp_path / "cli_report.pdf"
    result = subprocess.run(
        [sys.executable, "-m", "reporting", str(bundle_path), str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF-")
