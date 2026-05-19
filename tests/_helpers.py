"""Shared schema/validator/HITL helpers used by both unit and integration tests.

Lives at ``tests/_helpers.py`` so test files under ``tests/unit/`` and
``tests/integration/`` can import it via ``from _helpers import ...`` once
``tests/`` is on the pytest pythonpath (see ``pyproject.toml``).
"""

from __future__ import annotations

import json
import pathlib

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


SCHEMAS_DIR = pathlib.Path(__file__).resolve().parent.parent / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


AGENT_STEP_SCHEMA = _load("agent_step.schema.json")
TOOL_INVOCATION_SCHEMA = _load("tool_invocation.schema.json")
HUMAN_INTERVENTION_SCHEMA = _load("human_intervention.schema.json")
PIPELINE_BUNDLE_SCHEMA = _load("pipeline_bundle.schema.json")

REGISTRY = Registry().with_resources(
    [
        (AGENT_STEP_SCHEMA["$id"], Resource.from_contents(AGENT_STEP_SCHEMA)),
        (TOOL_INVOCATION_SCHEMA["$id"], Resource.from_contents(TOOL_INVOCATION_SCHEMA)),
        (HUMAN_INTERVENTION_SCHEMA["$id"], Resource.from_contents(HUMAN_INTERVENTION_SCHEMA)),
        (PIPELINE_BUNDLE_SCHEMA["$id"], Resource.from_contents(PIPELINE_BUNDLE_SCHEMA)),
    ]
)


def validator(schema: dict) -> Draft202012Validator:
    """Return a Draft202012 validator wired to the cross-schema $ref registry."""
    return Draft202012Validator(schema, registry=REGISTRY)


def is_valid(schema: dict, instance: object) -> bool:
    return validator(schema).is_valid(instance)


def assert_hitl_consistent(record: dict) -> None:
    """Enforce the action_type ↔ output_after_hash conventions documented on the HITL schema."""
    a = record["action_type"]
    before = record["output_before_hash"]
    after = record["output_after_hash"]
    if a == "approved":
        assert after == before, "approved: output_after_hash must equal output_before_hash"
    elif a == "edited":
        assert after is not None and after != before, (
            "edited: output_after_hash must be non-null and differ from output_before_hash"
        )
    elif a in ("rejected", "escalated"):
        assert after is None, f"{a}: output_after_hash must be null"
    else:
        raise AssertionError(f"unknown action_type: {a}")


def assert_timestamps_ordered(record: dict) -> None:
    if "timestamp_start" in record and "timestamp_end" in record:
        assert record["timestamp_end"] >= record["timestamp_start"], (
            "timestamp_end must be >= timestamp_start"
        )
