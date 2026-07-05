"""Single validation surface for protocol records and bundles.

Validity has two mechanisms that cannot be merged into one - JSON Schema
expresses structure (required fields, types, patterns, enums) but cannot
compare two field *values* to each other. This module composes both behind one
entry point so callers and tests go through a single door:

* structural validation against the JSON Schema files (``jsonschema``, Draft
  2020-12), and
* the conditional rules JSON Schema cannot express:
    - ``action_type`` <-> ``output_after_hash`` on Human Intervention records, and
    - ``timestamp_end >= timestamp_start`` on Agent Step / Tool Invocation.

``validate_record`` validates a single record; ``validate_bundle`` validates a
bundle and every record it carries. Both raise :class:`ProtocolValidationError`
on the first failure, so there is one exception type to catch regardless of
which mechanism rejected the input.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# Read via importlib.resources so schemas resolve in both an editable checkout
# and an installed wheel.
_SCHEMAS_PACKAGE = "agent_prov.schemas"

_SCHEMA_FILES = {
    "agent_step": "agent_step.schema.json",
    "tool_invocation": "tool_invocation.schema.json",
    "human_intervention": "human_intervention.schema.json",
    "pipeline_bundle": "pipeline_bundle.schema.json",
}

# record_type values that name a standalone record (everything except the bundle).
_RECORD_TYPES = frozenset(_SCHEMA_FILES) - {"pipeline_bundle"}


def _load(name: str) -> dict[str, Any]:
    text = resources.files(_SCHEMAS_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    return json.loads(text)


# Loaded schemas keyed by record_type, plus a registry wiring the cross-schema
# $ref the Pipeline Bundle uses to validate each record by $id. Exposed (no
# underscore) so the test-fixture layer can reuse them rather than re-loading.
SCHEMAS: dict[str, dict[str, Any]] = {
    rtype: _load(fname) for rtype, fname in _SCHEMA_FILES.items()
}

REGISTRY: Registry = Registry().with_resources(
    [(schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values()]
)

_VALIDATORS: dict[str, Draft202012Validator] = {
    rtype: Draft202012Validator(schema, registry=REGISTRY)
    for rtype, schema in SCHEMAS.items()
}


class ProtocolValidationError(ValueError):
    """Raised when a record or bundle fails structural or conditional validation."""


def validate_record(record: Any) -> None:
    """Validate a single provenance record. Raises :class:`ProtocolValidationError`.

    Runs structural validation against the schema for the record's
    ``record_type``, then the conditional rules that JSON Schema cannot express.
    """
    if not isinstance(record, dict):
        raise ProtocolValidationError(f"record must be a JSON object, got {type(record).__name__}")
    rtype = record.get("record_type")
    if rtype not in _RECORD_TYPES:
        raise ProtocolValidationError(
            f"record_type must be one of {sorted(_RECORD_TYPES)}; got {rtype!r}"
        )
    _run_schema(rtype, record)
    _check_conditionals(record)


def validate_bundle(bundle: Any) -> None:
    """Validate a Pipeline Bundle and every record it carries.

    Raises :class:`ProtocolValidationError`. The bundle schema validates each
    record's *structure* via ``$ref``, so this only adds the per-record
    conditional rules on top of the bundle's structural validation.
    """
    if not isinstance(bundle, dict):
        raise ProtocolValidationError(f"bundle must be a JSON object, got {type(bundle).__name__}")
    _run_schema("pipeline_bundle", bundle)
    for i, rec in enumerate(bundle.get("records", [])):
        try:
            _check_conditionals(rec)
        except ProtocolValidationError as exc:
            raise ProtocolValidationError(f"records[{i}]: {exc}") from exc


# --------------------------------------------------------------- mechanisms


def _run_schema(record_type: str, instance: dict[str, Any]) -> None:
    """Structural validation against the JSON Schema for *record_type*."""
    errors = sorted(_VALIDATORS[record_type].iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        joined = "; ".join(f"{list(e.path) or '<root>'}: {e.message}" for e in errors)
        raise ProtocolValidationError(f"{record_type} schema validation failed: {joined}")


def _check_conditionals(record: dict[str, Any]) -> None:
    """Value-to-value rules JSON Schema cannot express; dispatched on record_type."""
    rtype = record.get("record_type")
    if rtype in ("agent_step", "tool_invocation"):
        _check_timestamps_ordered(record)
        _check_status_consistent(record)
    elif rtype == "human_intervention":
        _check_hitl_consistent(record)


def _check_timestamps_ordered(record: dict[str, Any]) -> None:
    start, end = record.get("timestamp_start"), record.get("timestamp_end")
    # ISO 8601 UTC strings ('...Z', fixed precision) compare correctly lexically.
    if start is not None and end is not None and end < start:
        raise ProtocolValidationError(
            f"timestamp_end ({end!r}) must be >= timestamp_start ({start!r})"
        )


def _check_status_consistent(record: dict[str, Any]) -> None:
    """Bind status to the presence of output_hash / error on Agent Step / Tool Invocation.

    The schema requires status and validates the shape of output_hash and the
    error object; this rule enforces which of the two is present for each status
    (a value-to-presence comparison JSON Schema cannot express):

    * status 'success' -> output_hash present, error absent.
    * status 'error'   -> output_hash absent, error present.
    """
    status = record.get("status")
    has_output = record.get("output_hash") is not None
    has_error = record.get("error") is not None
    if status == "success":
        if not has_output:
            raise ProtocolValidationError("status 'success': output_hash must be present")
        if has_error:
            raise ProtocolValidationError("status 'success': error must be absent")
    elif status == "error":
        if has_output:
            raise ProtocolValidationError(
                "status 'error': output_hash must be absent (a failed step has no output)"
            )
        if not has_error:
            raise ProtocolValidationError("status 'error': error detail must be present")


def _check_hitl_consistent(record: dict[str, Any]) -> None:
    action = record["action_type"]
    before, after = record["output_before_hash"], record["output_after_hash"]
    if action == "approved":
        if after != before:
            raise ProtocolValidationError(
                "approved: output_after_hash must equal output_before_hash"
            )
    elif action == "edited":
        if after is None or after == before:
            raise ProtocolValidationError(
                "edited: output_after_hash must be non-null and differ from output_before_hash"
            )
    elif action in ("rejected", "escalated"):
        if after is not None:
            raise ProtocolValidationError(f"{action}: output_after_hash must be null")
