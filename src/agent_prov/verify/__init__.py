"""Independent bundle verifier — the auditor-facing entry point.

A sealed Pipeline Bundle is only useful as evidence if a third party can
*recompute* its guarantees without trusting the producer. This module is that
recomputation, gathered into one public call:

* **schema + conditional rules** — delegated to the single validation surface
  (:func:`agent_prov.validation.validate_bundle`),
* **bundle_hash** — recompute the canonical-JSON SHA-256 with ``bundle_hash``
  excluded and compare against the stored seal (tamper evidence),
* **parent-chain integrity** — referential integrity of ``parent_record_id``:
  the head record has no parent and every other parent reference points at a
  record that appears earlier in the bundle, and
* **internal consistency** — ``pipeline_id`` / ``session_id`` are uniform across
  the bundle and its records, and no two records share a ``record_id``.

:func:`verify_bundle` collects *all* failures rather than stopping at the first
one, so an auditor sees the complete picture in a single pass. It is read-only
and never mutates the bundle.

Run it from the command line::

    python -m agent_prov.verify path/to/bundle.json
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_prov.bundle_generator import compute_bundle_hash
from agent_prov.validation import ProtocolValidationError, validate_bundle


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of :func:`verify_bundle`.

    ``ok`` is True only when ``errors`` is empty. ``errors`` lists every failure
    found across all checks (human-readable, one string per problem).
    """

    ok: bool
    errors: tuple[str, ...] = field(default_factory=tuple)


def verify_bundle(bundle: Any) -> VerificationResult:
    """Recompute every integrity guarantee of a sealed Pipeline Bundle.

    Returns a :class:`VerificationResult`; never raises for an invalid bundle
    (validation failures are reported as ``errors``, not exceptions).
    """
    errors: list[str] = []

    if not isinstance(bundle, dict):
        return VerificationResult(
            ok=False,
            errors=(f"bundle must be a JSON object, got {type(bundle).__name__}",),
        )

    # 1. Schema + conditional rules, via the single validation surface.
    try:
        validate_bundle(bundle)
    except ProtocolValidationError as exc:
        errors.append(f"schema/conditional validation failed: {exc}")

    # 2. bundle_hash seal — recompute and compare.
    errors.extend(_check_bundle_hash(bundle))

    records = bundle.get("records")
    if isinstance(records, list):
        # 3. parent-chain referential integrity.
        errors.extend(_check_parent_chain(records))
        # 4. internal consistency of identifiers.
        errors.extend(_check_consistency(bundle, records))

    return VerificationResult(ok=not errors, errors=tuple(errors))


# --------------------------------------------------------------- checks


def _check_bundle_hash(bundle: dict[str, Any]) -> list[str]:
    stored = bundle.get("bundle_hash")
    if not stored:
        return ["bundle_hash is missing or empty"]
    recomputed = compute_bundle_hash(bundle)
    if recomputed != stored:
        return [
            "bundle_hash mismatch: bundle has been modified since sealing "
            f"(stored {stored!r}, recomputed {recomputed!r})"
        ]
    return []


def _check_parent_chain(records: list[Any]) -> list[str]:
    """Referential integrity of parent_record_id across the record list.

    The head record must have no parent; every other ``parent_record_id``, when
    present, must reference a ``record_id`` that appears *earlier* in the list.
    This catches dangling references (parent that names no record) and forward
    references (parent that names a later record), without enforcing strict
    linear chaining — emission-order linearity is a known approximation that
    does not hold under parallel branches.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue  # structural validation already flagged this
        parent = rec.get("parent_record_id")
        if i == 0:
            if parent is not None:
                errors.append(
                    f"records[0]: head record must have no parent, got {parent!r}"
                )
        elif parent is not None and parent not in seen:
            errors.append(
                f"records[{i}]: parent_record_id {parent!r} does not reference "
                "any earlier record"
            )
        rid = rec.get("record_id")
        if isinstance(rid, str):
            if rid in seen:
                errors.append(f"records[{i}]: duplicate record_id {rid!r}")
            seen.add(rid)
    return errors


def _check_consistency(bundle: dict[str, Any], records: list[Any]) -> list[str]:
    """pipeline_id / session_id must be uniform across the bundle and records."""
    errors: list[str] = []
    for key in ("pipeline_id", "session_id"):
        expected = bundle.get(key)
        for i, rec in enumerate(records):
            if isinstance(rec, dict) and rec.get(key) != expected:
                errors.append(
                    f"records[{i}]: {key} {rec.get(key)!r} does not match "
                    f"bundle {key} {expected!r}"
                )
    return errors
