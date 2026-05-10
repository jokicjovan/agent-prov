"""Bundle serialization and integrity-hash helpers.

Currently scoped to the canonical-JSON SHA-256 helpers used to compute and
verify `bundle_hash`. The full `BundleGenerator` class (session serialization,
file output, etc.) will wrap these helpers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_sha256(obj: Any) -> str:
    """Return the SHA-256 hex digest of *obj* serialized as canonical JSON.

    Canonical form:
      - object keys sorted lexicographically by Unicode code point
      - no insignificant whitespace (compact separators)
      - UTF-8 encoded, non-ASCII characters preserved (not \\uXXXX-escaped)

    This is intentionally close to but not strictly RFC 8785 (JCS):
    Python's default number formatting differs from JCS in edge cases
    (e.g. integer-valued floats). Adopting a full JCS library is noted as
    future work.
    """
    canonical = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_bundle_hash(bundle: dict) -> str:
    """Return the canonical-JSON SHA-256 of *bundle* with `bundle_hash` removed.

    Excluding the `bundle_hash` field is required to break the chicken-and-egg
    of self-containing the digest. Verification recomputes the same exclusion
    and compares against the stored value (see tests/test_schemas.py).
    """
    bundle_without_hash = {k: v for k, v in bundle.items() if k != "bundle_hash"}
    return canonical_json_sha256(bundle_without_hash)
