"""Tests for detached bundle signing (agent_prov.signing).

Covers sign/verify roundtrips, forgery resistance (tamper detection), key
binding, malformed-envelope handling, and the CLI. Bundles are built through
BundleGenerator so the tests never depend on demos/ artifacts.

  1   A freshly signed bundle verifies with the embedded key.
  2   A signed bundle verifies against an explicitly supplied public key.
  3   Tampering with a record after signing is detected.
  4   Verifying against the wrong public key fails.
  5   A corrupted signature is rejected.
  6   A malformed envelope is reported, not raised.
  7   A wrong-bundle signature (signed_hash mismatch) is detected.
  8   sign_bundle refuses an inconsistent seal.
  9   sign_bundle refuses a bundle with no seal.
  10  Keypair PEM round-trips through the loaders.
  11  Multiple problems are all collected.
  12  CLI keygen -> sign -> verify round-trips (exit 0).
  13  CLI verify returns 1 for a tampered bundle.
"""

from __future__ import annotations

import base64
import copy
import json
from typing import Any

import pytest

from cryptography.hazmat.primitives import serialization

from agent_prov.bundle_generator import BundleGenerator, compute_bundle_hash
from agent_prov.session import PipelineSession
from agent_prov.signing import (
    BundleSignatureError,
    SignatureVerificationResult,
    generate_keypair,
    load_private_key,
    load_public_key,
    sign_bundle,
    verify_signature,
)
from agent_prov.signing.__main__ import _cli


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
    """Recompute bundle_hash after mutating records (an honest re-seal)."""
    bundle["bundle_hash"] = ""
    bundle["bundle_hash"] = compute_bundle_hash(bundle)
    return bundle


def _private_pem(private_key) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_pem(public_key) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def test_01_signed_bundle_verifies_with_embedded_key():
    bundle = _sealed_bundle()
    private_key, _ = generate_keypair()
    envelope = sign_bundle(bundle, private_key)
    assert verify_signature(bundle, envelope) == SignatureVerificationResult(
        ok=True, errors=()
    )


def test_02_signed_bundle_verifies_with_supplied_key():
    bundle = _sealed_bundle()
    private_key, public_key = generate_keypair()
    envelope = sign_bundle(bundle, private_key)
    result = verify_signature(bundle, envelope, public_key=public_key)
    assert result.ok


def test_03_tampered_record_detected():
    bundle = _sealed_bundle()
    private_key, _ = generate_keypair()
    envelope = sign_bundle(bundle, private_key)
    # Edit a record and honestly re-seal: bundle_hash now differs from the seal
    # the signature commits to, so verification must fail.
    bundle["records"][0]["model_id"] = "claude-haiku-4-5"
    _reseal(bundle)
    result = verify_signature(bundle, envelope)
    assert not result.ok
    assert any("signed_hash" in e or "bundle_hash mismatch" in e for e in result.errors)


def test_04_wrong_public_key_rejected():
    bundle = _sealed_bundle()
    private_key, _ = generate_keypair()
    _, other_public = generate_keypair()
    envelope = sign_bundle(bundle, private_key)
    result = verify_signature(bundle, envelope, public_key=other_public)
    assert not result.ok
    assert any("signature is invalid" in e for e in result.errors)


def test_05_corrupted_signature_rejected():
    bundle = _sealed_bundle()
    private_key, _ = generate_keypair()
    envelope = sign_bundle(bundle, private_key)
    raw = bytearray(base64.b64decode(envelope["signature"]))
    raw[0] ^= 0xFF
    envelope["signature"] = base64.b64encode(bytes(raw)).decode("ascii")
    result = verify_signature(bundle, envelope)
    assert not result.ok
    assert any("signature is invalid" in e for e in result.errors)


def test_06_malformed_envelope_reported_not_raised():
    bundle = _sealed_bundle()
    result = verify_signature(bundle, {"algorithm": "rsa"})
    assert not result.ok
    assert any("unsupported algorithm" in e for e in result.errors)
    assert any("payload_type" in e for e in result.errors)


def test_07_signature_for_other_bundle_detected():
    private_key, _ = generate_keypair()
    bundle_a = _sealed_bundle()
    bundle_b = _sealed_bundle()  # different ids -> different seal
    envelope = sign_bundle(bundle_a, private_key)
    result = verify_signature(bundle_b, envelope)
    assert not result.ok
    assert any("different bundle" in e for e in result.errors)


def test_08_sign_refuses_inconsistent_seal():
    bundle = _sealed_bundle()
    bundle["records"][0]["model_id"] = "tampered"  # seal no longer matches
    private_key, _ = generate_keypair()
    with pytest.raises(BundleSignatureError, match="inconsistent seal"):
        sign_bundle(bundle, private_key)


def test_09_sign_refuses_unsealed_bundle():
    bundle = _sealed_bundle()
    bundle["bundle_hash"] = ""
    private_key, _ = generate_keypair()
    with pytest.raises(BundleSignatureError, match="no bundle_hash"):
        sign_bundle(bundle, private_key)


def test_10_keypair_pem_round_trip():
    private_key, public_key = generate_keypair()
    loaded_private = load_private_key(_private_pem(private_key))
    loaded_public = load_public_key(_public_pem(public_key))
    bundle = _sealed_bundle()
    envelope = sign_bundle(bundle, loaded_private)
    assert verify_signature(bundle, envelope, public_key=loaded_public).ok


def test_11_multiple_problems_all_collected():
    bundle = _sealed_bundle()
    envelope = {"algorithm": "rsa", "payload_type": "wrong", "signed_hash": "x"}
    result = verify_signature(bundle, envelope)
    assert not result.ok
    assert len(result.errors) >= 3


def test_12_cli_keygen_sign_verify_round_trip(tmp_path, capsys):
    priv = tmp_path / "priv.pem"
    pub = tmp_path / "pub.pem"
    bundle_path = tmp_path / "bundle.json"
    sig_path = tmp_path / "bundle.json.sig"
    bundle_path.write_text(json.dumps(_sealed_bundle()), encoding="utf-8")

    assert _cli(["keygen", "--out-private", str(priv), "--out-public", str(pub)]) == 0
    assert _cli(["sign", str(bundle_path), "--key", str(priv)]) == 0
    assert sig_path.exists()
    assert _cli(["verify", str(bundle_path), str(sig_path), "--key", str(pub)]) == 0
    assert "OK: signature verified" in capsys.readouterr().out


def test_13_cli_verify_fails_for_tampered_bundle(tmp_path, capsys):
    priv = tmp_path / "priv.pem"
    bundle_path = tmp_path / "bundle.json"
    sig_path = tmp_path / "bundle.json.sig"
    bundle = _sealed_bundle()
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    assert _cli(["keygen", "--out-private", str(priv)]) == 0
    assert _cli(["sign", str(bundle_path), "--key", str(priv)]) == 0

    tampered = copy.deepcopy(bundle)
    tampered["records"][0]["model_id"] = "claude-haiku-4-5"
    _reseal(tampered)
    bundle_path.write_text(json.dumps(tampered), encoding="utf-8")

    assert _cli(["verify", str(bundle_path), str(sig_path)]) == 1
    assert "FAILED" in capsys.readouterr().err
