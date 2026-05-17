"""Agent Step Record emitter.

Extracts model identity, content hashes, and agent_id from a completed
_StepFrame / LLM response pair, assembles an Agent Step Record, and
hands it to the PipelineSession via session.add_record().
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from middleware.core import (
    SessionProtocol,
    _NodeFrame,
    _StepFrame,
    _now_iso8601,
    hash_content,
)


def emit_agent_step(
    frame: _StepFrame,
    response: Any,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build an Agent Step Record from a matched LLM call pair and add it to the session."""
    record = {
        "record_id": str(uuid4()),
        "record_type": "agent_step",
        "protocol_version": session.protocol_version,
        "pipeline_id": session.pipeline_id,
        "session_id": session.session_id,
        "agent_id": _derive_agent_id(frame, nodes),
        "model_id": _extract_model_id(frame),
        "model_version": _extract_model_version(frame),
        "timestamp_start": frame.timestamp_start,
        "timestamp_end": _now_iso8601(),
        "input_hash": hash_content(frame.messages),
        "output_hash": hash_content(response),
        "reference_data_id": None,
        "parent_record_id": getattr(session, "last_record_id", None),
    }
    session.add_record(record)


# ------------------------------------------------------------------ extraction


def _extract_model_id(frame: _StepFrame) -> str:
    # LangSmith standard metadata key — most reliable source
    if name := frame.metadata.get("ls_model_name"):
        return str(name)
    # Provider-specific serialized kwargs
    kwargs = frame.serialized.get("kwargs", {})
    for key in ("model", "model_name"):
        if val := kwargs.get(key):
            return str(val)
    # Fall back to the class name (e.g. "ChatOpenAI") — coarse but non-empty
    return frame.serialized.get("name", "unknown") or "unknown"


def _extract_model_version(frame: _StepFrame) -> str:
    kwargs = frame.serialized.get("kwargs", {})
    if v := kwargs.get("model_version"):
        return str(v)
    # When no distinct version is available the model_id string serves as both
    # identifier and version (e.g. "gpt-4o-2024-11-20" or "claude-opus-4-7").
    return _extract_model_id(frame)


def _derive_agent_id(frame: _StepFrame, nodes: dict[UUID, _NodeFrame]) -> str:
    if frame.parent_run_id is not None and frame.parent_run_id in nodes:
        return nodes[frame.parent_run_id].node_name
    if frame.parent_run_id is not None:
        return str(frame.parent_run_id)
    return "unknown"
