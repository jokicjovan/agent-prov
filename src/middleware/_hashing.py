"""Canonical-JSON serialization, content hashing, and record timestamps.

Leaf module: depends only on the standard library and imports nothing from
``middleware`` itself, so both the middleware (``core``) and the emitters can
import it at load time without forming a cycle.

``canonical_json_sha256`` defines the protocol's canonical hash form;
``hash_content`` is the convenience wrapper the emitters and ``HumanReview``
call; ``_now_iso8601`` stamps the UTC timestamps that records carry.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def _now_iso8601() -> str:
    """UTC ISO 8601 timestamp with `Z` suffix (matches schema `iso8601_timestamp`)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json_sha256(obj: Any) -> str:
    """Return the SHA-256 hex digest of *obj* serialized as canonical JSON.

    Canonical form:
      - object keys sorted lexicographically by Unicode code point
      - no insignificant whitespace (compact separators)
      - UTF-8 encoded, non-ASCII characters preserved (not \\uXXXX-escaped)
      - NaN/Infinity rejected (`allow_nan=False`) — non-portable in JSON and a
        provenance hash should fail loudly rather than digest unrepresentable
        floats.
      - Unknown types fall back to ``str(obj)`` (`default=str`) as a last-resort
        serializer so callers do not have to pre-normalize every conceivable
        value (e.g. ``UUID``, ``datetime``).

    Intentionally close to but not strictly RFC 8785 (JCS): Python's default
    number formatting differs from JCS in edge cases (e.g. integer-valued
    floats). Adopting a full JCS library is noted as future work.
    """
    canonical = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hash_content(obj: Any) -> str:
    """Canonical SHA-256 of *obj*, first normalised to JSON-compatible form.

    Unwraps Pydantic / LangChain message objects (anything with ``model_dump``
    or ``dict``) recursively, then delegates to :func:`canonical_json_sha256`.
    Use this for emitter inputs (LLM messages, tool outputs, reviewer-supplied
    content) where the value may not already be pure JSON.
    """
    return canonical_json_sha256(_to_serializable(obj))


def _to_serializable(obj: Any) -> Any:
    """Recursively unwrap Pydantic / LangChain objects into JSON primitives."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict") and callable(obj.dict):
        return obj.dict()
    if isinstance(obj, list):
        return [_to_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    return obj
