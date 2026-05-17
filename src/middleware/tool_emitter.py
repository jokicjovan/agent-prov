"""Tool Invocation Record emitter.

Extracts tool identity, content hashes, and agent_id from a completed
_ToolFrame / tool output pair, assembles a Tool Invocation Record, and
hands it to the PipelineSession via session.add_record().
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from middleware.core import (
    SessionProtocol,
    _NodeFrame,
    _ToolFrame,
    _now_iso8601,
    hash_content,
)


def emit_tool_invocation(
    frame: _ToolFrame,
    output: Any,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build a Tool Invocation Record from a matched tool call pair and add it to the session."""
    record = {
        "record_id": str(uuid4()),
        "record_type": "tool_invocation",
        "protocol_version": session.protocol_version,
        "pipeline_id": session.pipeline_id,
        "session_id": session.session_id,
        "agent_id": _derive_agent_id(frame, nodes),
        "tool_name": _extract_tool_name(frame),
        "tool_version": _extract_tool_version(frame),
        "timestamp_start": frame.timestamp_start,
        "timestamp_end": _now_iso8601(),
        "input_hash": hash_content(frame.input_str),
        "output_hash": hash_content(output),
        "reference_data_id": None,
        "parent_record_id": getattr(session, "last_record_id", None),
    }
    session.add_record(record)


# ------------------------------------------------------------------ extraction


def _extract_tool_name(frame: _ToolFrame) -> str:
    if name := (frame.serialized or {}).get("name"):
        return str(name)
    return "unknown"


def _extract_tool_version(frame: _ToolFrame) -> str:
    # Explicit version declared in serialized kwargs — set by tool author
    if v := (frame.serialized or {}).get("kwargs", {}).get("version"):
        return str(v)
    # Version supplied via metadata by the caller
    if v := frame.metadata.get("tool_version"):
        return str(v)
    return "unversioned"


def _derive_agent_id(frame: _ToolFrame, nodes: dict[UUID, _NodeFrame]) -> str:
    if frame.parent_run_id is not None and frame.parent_run_id in nodes:
        return nodes[frame.parent_run_id].node_name
    if frame.parent_run_id is not None:
        return str(frame.parent_run_id)
    return "unknown"
