"""Shared schema/validator helpers used by both unit and integration tests.

Lives at ``tests/_helpers.py`` so test files under ``tests/unit/`` and
``tests/integration/`` can import it via ``from _helpers import ...`` once
``tests/`` is on the pytest pythonpath (see ``pyproject.toml``).

The loaded schemas and cross-$ref registry are sourced from
``agent_prov.validation`` so there is a single place that loads and wires the
protocol schemas. The conditional rules (action_type ↔ output_after_hash,
timestamp ordering) also live there — tests call ``validate_record`` /
``validate_bundle`` rather than re-implementing them here. What remains below is
test ergonomics for *schema-only* structural checks, which the negative-path
tests use to show that a record is structurally valid yet rejected by a
conditional rule.
"""

from __future__ import annotations

from jsonschema import Draft202012Validator

from agent_prov.validation import REGISTRY, SCHEMAS

AGENT_STEP_SCHEMA = SCHEMAS["agent_step"]
TOOL_INVOCATION_SCHEMA = SCHEMAS["tool_invocation"]
HUMAN_INTERVENTION_SCHEMA = SCHEMAS["human_intervention"]
PIPELINE_BUNDLE_SCHEMA = SCHEMAS["pipeline_bundle"]


def validator(schema: dict) -> Draft202012Validator:
    """Return a Draft202012 validator wired to the cross-schema $ref registry."""
    return Draft202012Validator(schema, registry=REGISTRY)


def is_valid(schema: dict, instance: object) -> bool:
    """Schema-only (structural) validity — does not run the conditional rules."""
    return validator(schema).is_valid(instance)
