"""Tests for the independent bundle verifier (agent_prov.verify).

Covers verify_bundle across each check it performs, the all-failures-collected
behaviour, and the CLI entry point. Bundles are built through BundleGenerator so
the tests never depend on demos/ artifacts.

  1   A freshly sealed bundle verifies (ok=True, no errors).
  2   A tampered bundle_hash is detected.
  3   A missing bundle_hash is detected.
  4   A dangling parent_record_id is detected.
  5   A forward parent reference is detected.
  6   A non-null parent on the head record is detected.
  7   A duplicate record_id is detected.
  8   A pipeline_id/session_id mismatch against the bundle is detected.
  9   A schema-invalid record is reported via the validation surface.
  10  Multiple simultaneous problems are all collected.
  11  A non-dict input is rejected without raising.
  12  CLI returns 0 and prints OK for a good bundle.
  13  CLI returns 1 and prints failures for a tampered bundle.
"""

from __future__ import annotations

import json
from typing import Any

from agent_prov.bundle_generator import BundleGenerator, compute_bundle_hash
from agent_prov.session import PipelineSession
from agent_prov.verify import VerificationResult, verify_bundle
from agent_prov.verify.__main__ import _cli


def _sealed_bundle() -> dict[str, Any]:
    """A two-record bundle (agent_step -> tool_invocation) sealed for real."""
    session = PipelineSession()
    session.add_agent_step(
        agent_id="researcher",
        model_id="claude-opus-4-8",
        model_version="20260101",
        timestamp_start="2026-05-11T10:00:00Z",
        input=["question"],
        output=["answer"],
    )
    session.add_tool_invocation(
        agent_id="researcher",
        tool_name="web_search",
        tool_version="1.0.0",
        timestamp_start="2026-05-11T10:00:01Z",
        input={"query": "x"},
        output={"hits": 3},
    )
    return BundleGenerator(session).generate()


def _reseal(bundle: dict[str, Any]) -> dict[str, Any]:
    """Recompute bundle_hash after mutating records, so only the targeted defect
    under test fails (not an incidental hash mismatch)."""
    bundle["bundle_hash"] = ""
    bundle["bundle_hash"] = compute_bundle_hash(bundle)
    return bundle


def test_01_valid_bundle_verifies():
    assert verify_bundle(_sealed_bundle()) == VerificationResult(ok=True, errors=())


def test_02_tampered_bundle_hash_detected():
    bundle = _sealed_bundle()
    bundle["bundle_hash"] = "0" * 64
    result = verify_bundle(bundle)
    assert not result.ok
    assert any("bundle_hash mismatch" in e for e in result.errors)


def test_03_missing_bundle_hash_detected():
    bundle = _sealed_bundle()
    bundle["bundle_hash"] = ""
    result = verify_bundle(bundle)
    assert not result.ok
    assert any("bundle_hash is missing" in e for e in result.errors)


def test_04_dangling_parent_detected():
    bundle = _sealed_bundle()
    bundle["records"][1]["parent_record_id"] = "99999999-9999-9999-9999-999999999999"
    result = verify_bundle(_reseal(bundle))
    assert not result.ok
    assert any("does not reference any earlier record" in e for e in result.errors)


def test_05_forward_parent_reference_detected():
    bundle = _sealed_bundle()
    # Head record points at the second (later) record — a forward reference.
    bundle["records"][0]["parent_record_id"] = bundle["records"][1]["record_id"]
    result = verify_bundle(_reseal(bundle))
    assert not result.ok
    assert any("head record must have no parent" in e for e in result.errors)


def test_06_non_null_head_parent_detected():
    bundle = _sealed_bundle()
    bundle["records"][0]["parent_record_id"] = "11111111-1111-1111-1111-111111111111"
    result = verify_bundle(_reseal(bundle))
    assert not result.ok
    assert any("head record must have no parent" in e for e in result.errors)


def test_07_duplicate_record_id_detected():
    bundle = _sealed_bundle()
    bundle["records"][1]["record_id"] = bundle["records"][0]["record_id"]
    # Fix parent so only the duplicate fails, not a forward/dangling parent.
    bundle["records"][1]["parent_record_id"] = bundle["records"][0]["record_id"]
    result = verify_bundle(_reseal(bundle))
    assert not result.ok
    assert any("duplicate record_id" in e for e in result.errors)


def test_08_identifier_mismatch_detected():
    bundle = _sealed_bundle()
    bundle["records"][0]["session_id"] = "00000000-0000-0000-0000-000000000000"
    result = verify_bundle(_reseal(bundle))
    assert not result.ok
    assert any("session_id" in e and "does not match bundle" in e for e in result.errors)


def test_09_schema_invalid_record_reported():
    bundle = _sealed_bundle()
    del bundle["records"][0]["model_id"]  # required field
    result = verify_bundle(_reseal(bundle))
    assert not result.ok
    assert any("schema/conditional validation failed" in e for e in result.errors)


def test_10_multiple_problems_all_collected():
    bundle = _sealed_bundle()
    bundle["records"][0]["parent_record_id"] = "99999999-9999-9999-9999-999999999999"
    bundle["bundle_hash"] = "0" * 64  # do NOT reseal: leave the hash wrong too
    result = verify_bundle(bundle)
    assert not result.ok
    assert any("bundle_hash mismatch" in e for e in result.errors)
    assert any("head record must have no parent" in e for e in result.errors)


def test_11_non_dict_input_rejected_without_raising():
    result = verify_bundle(["not", "a", "bundle"])
    assert not result.ok
    assert any("must be a JSON object" in e for e in result.errors)


def test_12_cli_returns_zero_for_good_bundle(tmp_path, capsys):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(_sealed_bundle()), encoding="utf-8")
    assert _cli([str(path)]) == 0
    assert "OK: bundle verified" in capsys.readouterr().out


def test_13_cli_returns_one_for_tampered_bundle(tmp_path, capsys):
    bundle = _sealed_bundle()
    bundle["bundle_hash"] = "0" * 64
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    assert _cli([str(path)]) == 1
    assert "FAILED" in capsys.readouterr().err


def test_14_curated_top_level_api_is_importable():
    import agent_prov

    for name in (
        "PipelineSession",
        "BundleGenerator",
        "compute_bundle_hash",
        "SessionProtocol",
        "now_iso8601",
        "validate_record",
        "validate_bundle",
        "ProtocolValidationError",
        "verify_bundle",
        "VerificationResult",
    ):
        assert hasattr(agent_prov, name), f"agent_prov.{name} should be re-exported"
    # The adapter and reporting surfaces stay behind their extras — not top-level.
    assert not hasattr(agent_prov, "ProvenanceMiddleware")
    assert not hasattr(agent_prov, "ComplianceReport")
