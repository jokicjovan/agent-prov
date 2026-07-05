"""Independent bundle verifier - the auditor-facing entry point.

A sealed Pipeline Bundle is only useful as evidence if a third party can
*recompute* its guarantees without trusting the producer. This module is that
recomputation, gathered into one public call:

* **schema + conditional rules** - delegated to the single validation surface
  (:func:`agent_prov.validation.validate_bundle`),
* **bundle_hash** - recompute the canonical-JSON SHA-256 with ``bundle_hash``
  excluded and compare against the stored seal (tamper evidence),
* **parent-chain integrity** - referential integrity of ``parent_record_id``:
  the head record has no parent and every other parent reference points at a
  record that appears earlier in the bundle, and
* **internal consistency** - ``pipeline_id`` / ``session_id`` are uniform across
  the bundle and its records, and no two records share a ``record_id``, and
* **execution-interval concurrency** - a non-fatal *observation*, not a failure:
  records whose ``[timestamp_start, timestamp_end]`` intervals overlap
  demonstrably ran concurrently, so the chronological parent chain orders them
  sequentially only as an approximation. This is surfaced as a *warning* (it does
  not set ``ok`` False), because a parallel pipeline is a valid, untampered state
  the chronological cursor merely under-describes - truthful under-description in
  place of the confident false ordering the chain would otherwise assert.

:func:`verify_bundle` collects *all* failures rather than stopping at the first
one, so an auditor sees the complete picture in a single pass. It is read-only
and never mutates the bundle.

Run it from the command line::

    python -m agent_prov.verify path/to/bundle.json
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent_prov.bundle_generator import compute_bundle_hash
from agent_prov.validation import ProtocolValidationError, validate_bundle


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of :func:`verify_bundle`.

    ``ok`` is True only when ``errors`` is empty. ``errors`` lists every integrity
    failure found across all checks (human-readable, one string per problem).
    ``warnings`` lists non-fatal structural observations - currently execution
    intervals that overlap, i.e. records that ran concurrently - and deliberately
    does *not* affect ``ok``: a parallel pipeline is a valid, untampered bundle.
    """

    ok: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def verify_bundle(bundle: Any) -> VerificationResult:
    """Recompute every integrity guarantee of a sealed Pipeline Bundle.

    Returns a :class:`VerificationResult`; never raises for an invalid bundle
    (validation failures are reported as ``errors``, not exceptions).
    """
    errors: list[str] = []
    warnings: list[str] = []

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

    # 2. bundle_hash seal - recompute and compare.
    errors.extend(_check_bundle_hash(bundle))

    records = bundle.get("records")
    if isinstance(records, list):
        # 3. parent-chain referential integrity.
        errors.extend(_check_parent_chain(records))
        # 4. internal consistency of identifiers.
        errors.extend(_check_consistency(bundle, records))
        # 5. concurrency observation (non-fatal; populates warnings, not errors).
        warnings.extend(_check_concurrency(records))

    return VerificationResult(ok=not errors, errors=tuple(errors), warnings=tuple(warnings))


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
    linear chaining - emission-order linearity is a known approximation that
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


def _check_concurrency(records: list[Any]) -> list[str]:
    """Report records that ran concurrently, as non-fatal warnings.

    ``parent_record_id`` chains records in emission order, which asserts a purely
    sequential pipeline. That assertion is an approximation: two records whose
    ``[timestamp_start, timestamp_end]`` execution intervals overlap demonstrably
    ran at the same time. This check derives concurrency from those intervals
    alone - not from the parent chain, so it is robust however the chronological
    cursor happened to thread parallel branches - and groups every set of
    transitively-overlapping records into a concurrent *cluster*.

    Each cluster of two or more records yields one warning. Records without a full
    interval (e.g. the instantaneous Human Intervention Record, which carries only
    ``intervention_timestamp``) are excluded: a point event cannot be shown to
    overlap anything. Overlap is strict, so a clean sequential hand-off where one
    record ends exactly as the next begins is *not* reported as concurrency.
    """
    # (index, start, end) for every record that exposes a parseable interval.
    intervals: list[tuple[int, datetime, datetime]] = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        start = _parse_timestamp(rec.get("timestamp_start"))
        end = _parse_timestamp(rec.get("timestamp_end"))
        if start is not None and end is not None:
            intervals.append((i, start, end))

    if len(intervals) < 2:
        return []

    # Sweep in start order, growing a cluster while the next interval starts
    # before the running maximum end (transitive overlap = one concurrent region).
    intervals.sort(key=lambda t: t[1])
    warnings: list[str] = []
    cluster: list[int] = [intervals[0][0]]
    cluster_max_end = intervals[0][2]
    for index, start, end in intervals[1:]:
        if start < cluster_max_end:  # strict: touching endpoints is a hand-off
            cluster.append(index)
            if end > cluster_max_end:
                cluster_max_end = end
        else:
            warnings.extend(_concurrency_warning(cluster))
            cluster = [index]
            cluster_max_end = end
    warnings.extend(_concurrency_warning(cluster))
    return warnings


def _concurrency_warning(cluster: list[int]) -> list[str]:
    """One warning line for a concurrent cluster; empty for a lone record."""
    if len(cluster) < 2:
        return []
    positions = ", ".join(f"records[{i}]" for i in cluster)
    return [
        f"{positions} ran concurrently (execution intervals overlap); the "
        "chronological parent chain orders them sequentially, which is an "
        "approximation for this region"
    ]


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 timestamp to an aware ``datetime``, or ``None``.

    Schema-valid timestamps carry a timezone; a naive value (should not occur past
    validation) is treated as UTC so comparisons never mix aware and naive. An
    unparseable value returns ``None`` and is simply excluded from the concurrency
    scan - the schema layer owns rejecting a malformed timestamp.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
