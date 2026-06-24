"""Detached bundle signing -- the tamper-*proof*, attributable layer over the seal.

The ``bundle_hash`` (see :mod:`agent_prov.verify`) makes a bundle
tamper-*evident*: recompute and compare detects modification. But anyone can
recompute that hash, so an editor can re-seal a modified bundle and it looks
valid again. A signature closes that gap. It can only be produced by the holder
of a private key, so a third party (an auditor) gets two guarantees the hash
alone cannot:

* **non-repudiation** -- the seal is attributable to a specific key holder, and
* **forgery resistance** -- a modified bundle cannot be re-signed without the key.

This strengthens the EU AI Act Art. 12(1) evidentiary-integrity claim: logs an
auditor can independently verify and attribute, not merely a mutable record set.

The design follows established provenance-signing practice (in-toto / SLSA /
DSSE / Sigstore):

* **detached** -- the signature is a separate envelope, not embedded in the
  bundle, so the bundle stays byte-stable and independently hashable;
* **asymmetric** (Ed25519) -- a verifier needs only the public key, never a
  shared secret, and the signature attributes authorship; and
* **bound payload** -- the signature covers ``{payload_type, algorithm,
  signed_hash}`` canonicalized via the same RFC 8785 path used for hashing, not
  the bare digest string, so a signature cannot be lifted and replayed in a
  different context.

This module lives behind the ``agent-prov[signing]`` extra (it needs
``cryptography``); the protocol core stays crypto-free. Import from
``agent_prov.signing``; the top-level ``agent_prov`` package deliberately does
not re-export these names.

Run it from the command line::

    python -m agent_prov.signing keygen --out-private priv.pem --out-public pub.pem
    python -m agent_prov.signing sign bundle.json --key priv.pem -o bundle.json.sig
    python -m agent_prov.signing verify bundle.json bundle.json.sig --key pub.pem
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from agent_prov._hashing import canonical_json_bytes, now_iso8601
from agent_prov.bundle_generator import compute_bundle_hash

__all__ = [
    "ALGORITHM",
    "PAYLOAD_TYPE",
    "ENVELOPE_VERSION",
    "BundleSignatureError",
    "SignatureVerificationResult",
    "generate_keypair",
    "sign_bundle",
    "verify_signature",
    "load_private_key",
    "load_public_key",
]

ALGORITHM = "ed25519"
PAYLOAD_TYPE = "application/vnd.agent-prov.bundle-seal+json"
ENVELOPE_VERSION = "v1"


class BundleSignatureError(Exception):
    """Raised for malformed keys or signing/loading failures (not verification).

    Verification of a bad bundle or signature is reported through
    :class:`SignatureVerificationResult`, never by raising. This exception is for
    operations that cannot meaningfully continue: an unreadable key file, an
    inconsistent bundle handed to :func:`sign_bundle`, etc.
    """


@dataclass(frozen=True)
class SignatureVerificationResult:
    """Outcome of :func:`verify_signature`.

    ``ok`` is True only when ``errors`` is empty. ``errors`` lists every failure
    found (human-readable, one string per problem), mirroring
    :class:`agent_prov.verify.VerificationResult`.
    """

    ok: bool
    errors: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------- keys


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Return a fresh ``(private_key, public_key)`` Ed25519 pair."""
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def load_private_key(data: bytes) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from PEM (PKCS#8) bytes."""
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError) as exc:
        raise BundleSignatureError(f"could not load private key: {exc}") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise BundleSignatureError(
            f"expected an Ed25519 private key, got {type(key).__name__}"
        )
    return key


def load_public_key(data: bytes) -> Ed25519PublicKey:
    """Load an Ed25519 public key from PEM (SubjectPublicKeyInfo) bytes."""
    try:
        key = serialization.load_pem_public_key(data)
    except (ValueError, TypeError) as exc:
        raise BundleSignatureError(f"could not load public key: {exc}") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise BundleSignatureError(
            f"expected an Ed25519 public key, got {type(key).__name__}"
        )
    return key


# --------------------------------------------------------------- sign


def _signed_payload_bytes(bundle_hash: str) -> bytes:
    """Canonical bytes of the bound payload that the signature actually covers.

    Binds the payload type and algorithm to the digest so the signature is not
    transferable to another context (DSSE-style pre-authentication encoding).
    """
    return canonical_json_bytes(
        {
            "payload_type": PAYLOAD_TYPE,
            "algorithm": ALGORITHM,
            "signed_hash": bundle_hash,
        }
    )


def sign_bundle(
    bundle: dict[str, Any],
    private_key: Ed25519PrivateKey,
    *,
    signed_at: str | None = None,
) -> dict[str, Any]:
    """Sign a sealed bundle and return a detached signature envelope.

    The bundle's stored ``bundle_hash`` is recomputed and confirmed first, so a
    stale or inconsistent seal is never signed.

    Raises:
        BundleSignatureError: if the bundle has no ``bundle_hash`` or its stored
            seal does not match a recomputation (sign the bundle as sealed).
    """
    stored = bundle.get("bundle_hash")
    if not stored:
        raise BundleSignatureError("bundle has no bundle_hash to sign; seal it first")
    recomputed = compute_bundle_hash(bundle)
    if recomputed != stored:
        raise BundleSignatureError(
            "refusing to sign an inconsistent seal: stored bundle_hash "
            f"{stored!r} does not match recomputed {recomputed!r}"
        )

    signature = private_key.sign(_signed_payload_bytes(stored))
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "agent_prov_signature": ENVELOPE_VERSION,
        "payload_type": PAYLOAD_TYPE,
        "algorithm": ALGORITHM,
        "signed_hash": stored,
        "public_key": base64.b64encode(public_raw).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
        "signed_at": signed_at if signed_at is not None else now_iso8601(),
    }


# --------------------------------------------------------------- verify


def verify_signature(
    bundle: dict[str, Any],
    envelope: dict[str, Any],
    *,
    public_key: Ed25519PublicKey | None = None,
) -> SignatureVerificationResult:
    """Verify a detached signature envelope against its bundle.

    Recomputes the bundle seal and checks the signature over the bound payload.
    When *public_key* is omitted, the key embedded in the envelope is used (trust
    on first use): this proves the bundle was signed by *that* key, but not whose
    key it is -- pass a trusted *public_key* to also bind authorship. Collects
    all failures; never raises for a bad bundle or envelope.
    """
    errors: list[str] = []

    if not isinstance(bundle, dict):
        return SignatureVerificationResult(
            ok=False,
            errors=(f"bundle must be a JSON object, got {type(bundle).__name__}",),
        )
    if not isinstance(envelope, dict):
        return SignatureVerificationResult(
            ok=False,
            errors=(f"signature must be a JSON object, got {type(envelope).__name__}",),
        )

    # 1. Envelope shape and supported algorithm.
    if envelope.get("payload_type") != PAYLOAD_TYPE:
        errors.append(
            f"unexpected payload_type {envelope.get('payload_type')!r} "
            f"(expected {PAYLOAD_TYPE!r})"
        )
    if envelope.get("algorithm") != ALGORITHM:
        errors.append(
            f"unsupported algorithm {envelope.get('algorithm')!r} "
            f"(expected {ALGORITHM!r})"
        )

    # 2. signed_hash must match the bundle's recomputed seal (tamper evidence).
    stored = bundle.get("bundle_hash")
    signed_hash = envelope.get("signed_hash")
    if not stored:
        errors.append("bundle has no bundle_hash to verify against")
    else:
        recomputed = compute_bundle_hash(bundle)
        if recomputed != stored:
            errors.append(
                "bundle_hash mismatch: bundle has been modified since sealing "
                f"(stored {stored!r}, recomputed {recomputed!r})"
            )
        if signed_hash != recomputed:
            errors.append(
                f"signed_hash {signed_hash!r} does not match the bundle's "
                f"seal {recomputed!r}: this signature is for a different bundle"
            )

    # 3. Resolve the verifying key.
    key = public_key
    if key is None:
        key = _key_from_envelope(envelope, errors)

    # 4. Signature must validate over the reconstructed bound payload. Only
    #    attempt this once a signed_hash and a key are available.
    if key is not None and isinstance(signed_hash, str):
        signature = _decode_b64(envelope.get("signature"), "signature", errors)
        if signature is not None:
            try:
                key.verify(signature, _signed_payload_bytes(signed_hash))
            except InvalidSignature:
                errors.append("signature is invalid for the signed payload and key")

    return SignatureVerificationResult(ok=not errors, errors=tuple(errors))


def _key_from_envelope(
    envelope: dict[str, Any], errors: list[str]
) -> Ed25519PublicKey | None:
    raw = _decode_b64(envelope.get("public_key"), "public_key", errors)
    if raw is None:
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        errors.append(f"embedded public_key is not a valid Ed25519 key: {exc}")
        return None


def _decode_b64(value: Any, field_name: str, errors: list[str]) -> bytes | None:
    if not isinstance(value, str):
        errors.append(f"{field_name} is missing or not a string")
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        errors.append(f"{field_name} is not valid base64: {exc}")
        return None
