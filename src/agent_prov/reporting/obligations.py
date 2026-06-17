"""EU AI Act obligation mapping for provenance records.

`OBLIGATION_MAP` is the single source of truth linking each record-type
field to the Act clause(s) it substantiates; `CLAUSE_DESCRIPTION` carries
the prose for each clause.
"""

from __future__ import annotations

from typing import Any


OBLIGATION_MAP: dict[str, dict[str, list[str]]] = {
    "agent_step": {
        "timestamp_start": ["Art. 12(3)(a)"],
        "timestamp_end": ["Art. 12(3)(a)"],
        "model_id": ["Art. 12(2)(b)", "Art. 14(4)(a)"],
        "model_version": ["Art. 12(2)(b)", "Art. 14(4)(a)"],
        "input_hash": ["Art. 12(3)(c)"],
        "output_hash": ["Art. 12(2)(c)"],
        "status": ["Art. 12(2)(a)"],
        "reference_data_id": ["Art. 12(3)(b)"],
        "pipeline_id": ["Art. 12(2)(c)"],
        "session_id": ["Art. 12(2)(c)"],
    },
    "tool_invocation": {
        "timestamp_start": ["Art. 12(3)(a)"],
        "timestamp_end": ["Art. 12(3)(a)"],
        "input_hash": ["Art. 12(3)(c)"],
        "output_hash": ["Art. 12(2)(c)"],
        "status": ["Art. 12(2)(a)"],
        "reference_data_id": ["Art. 12(3)(b)"],
        "pipeline_id": ["Art. 12(2)(c)"],
        "session_id": ["Art. 12(2)(c)"],
    },
    "human_intervention": {
        "reviewer_id": ["Art. 12(3)(d)", "Art. 14(5)"],
        "action_type": ["Art. 14(4)(d)", "Art. 14(4)(e)", "Art. 50(4) exception"],
        "output_before_hash": ["Art. 14(4)(c)"],
        "output_after_hash": ["Art. 14(4)(d)"],
        "intervention_timestamp": ["Art. 14(4)(e)"],
        "justification_hash": ["Art. 14(4)(c)"],
        "pipeline_id": ["Art. 12(2)(c)"],
        "session_id": ["Art. 12(2)(c)"],
    },
    "pipeline_bundle": {
        "disclosure_presented": ["Art. 50(1)"],
        "outcome": ["Art. 12(2)(a)"],
        "bundle_hash": ["Art. 12(1)"],
        "pipeline_id": ["Art. 12(2)(c)"],
        "session_id": ["Art. 12(2)(c)"],
    },
}


CLAUSE_DESCRIPTION: dict[str, str] = {
    "Art. 12(1)": "Logs are technically enabled with evidentiary integrity",
    "Art. 12(2)(a)": "Recording of events relevant to risk situations and malfunctions",
    "Art. 12(2)(b)": "Post-market monitoring - model identity and version",
    "Art. 12(2)(c)": "Operational monitoring - pipeline linkage and output integrity",
    "Art. 12(3)(a)": "Start and end time of each use",
    "Art. 12(3)(b)": "Reference database consulted",
    "Art. 12(3)(c)": "Input data that produced a result",
    "Art. 12(3)(d)": "Identity of natural persons who verified results",
    "Art. 14(4)(a)": "Oversight: capabilities and limitations of the system",
    "Art. 14(4)(c)": "Oversight: correct interpretation of system output",
    "Art. 14(4)(d)": "Oversight: ability to disregard, override, or reverse output",
    "Art. 14(4)(e)": "Oversight: intervene or halt via a stop mechanism",
    "Art. 14(5)": "Biometric ID: at least two-person verification",
    "Art. 50(1)": "User informed they are interacting with an AI system",
    "Art. 50(4) exception": "AI-generated text exempted by editorial human review",
}


def _field_present(record: dict[str, Any], field: str) -> bool:
    """A field substantiates its mapped clauses only when populated.

    For booleans this means True (a `disclosure_presented: false` records
    that the obligation was *not* met, so it must not be counted as
    satisfying it).
    """
    if field not in record:
        return False
    value = record[field]
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, list, dict)) and len(value) == 0:
        return False
    return True
