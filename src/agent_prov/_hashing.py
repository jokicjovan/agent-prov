"""Canonical-JSON serialization, content hashing, and record timestamps.

Framework-neutral leaf module: depends only on the standard library and
``rfc8785`` and imports nothing else in the package, so the session (its record
factory), ``HumanReview``, ``bundle_generator``, and any adapter can import it at
load time without forming a cycle.

``canonical_json_sha256`` defines the protocol's canonical hash form;
``hash_content`` is the convenience wrapper the session factory and
``HumanReview`` call; ``_now_iso8601`` stamps the UTC timestamps that records
carry.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import rfc8785


def _now_iso8601() -> str:
    """UTC ISO 8601 timestamp with `Z` suffix (matches schema `iso8601_timestamp`)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json_sha256(obj: Any) -> str:
    """Return the SHA-256 hex digest of *obj* serialized as canonical JSON.

    Canonicalization follows RFC 8785 (JSON Canonicalization Scheme): object
    keys sorted by Unicode code point, no insignificant whitespace, UTF-8
    output, and ECMAScript number formatting (so e.g. ``1.0`` and ``1`` digest
    identically). NaN/Infinity are rejected. Using a conformant JCS
    implementation means any independent verifier following RFC 8785 reproduces
    these digests byte-for-byte, rather than having to match this reference
    implementation's incidental quirks.

    *obj* must already be pure JSON primitives — ``rfc8785.dumps`` rejects
    anything else. This is the direct entry point for data that is already
    JSON-shaped (e.g. a fully assembled bundle in ``compute_bundle_hash``).
    Callers holding richer objects (LangChain messages, ``UUID``, ``datetime``)
    should use :func:`hash_content`, which normalises first.
    """
    return hashlib.sha256(rfc8785.dumps(obj)).hexdigest()


def hash_content(obj: Any) -> str:
    """Canonical SHA-256 of *obj*, normalised to JSON-compatible form first.

    Passes *obj* through :func:`_to_serializable` — which recursively unwraps
    Pydantic / LangChain objects and stringifies non-JSON leaves (``UUID``,
    ``datetime``, …) — then delegates to :func:`canonical_json_sha256`. Use
    this for emitter inputs (LLM messages, tool outputs, reviewer-supplied
    content) where the value may not already be pure JSON.
    """
    return canonical_json_sha256(_to_serializable(obj))


def _to_serializable(obj: Any) -> Any:
    """Recursively reduce *obj* to JSON primitives that ``rfc8785`` accepts.

    Unwraps Pydantic / LangChain objects (anything with ``model_dump`` or
    ``dict``) and recurses into the result; coerces mapping keys to strings;
    and stringifies any leaf that is not a JSON scalar (``UUID``, ``datetime``,
    ``Decimal``, …), matching the old ``json.dumps(default=str)`` fallback.
    """
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    if hasattr(obj, "model_dump"):
        return _to_serializable(obj.model_dump())
    if hasattr(obj, "dict") and callable(obj.dict):
        return _to_serializable(obj.dict())
    if isinstance(obj, dict):
        return {str(k): _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(item) for item in obj]
    return str(obj)
