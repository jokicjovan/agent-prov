"""Tool Invocation Record emitter.

Extracts tool identity, content hashes, and agent_id from a completed
_ToolFrame / tool output pair, assembles a Tool Invocation Record, and
hands it to the PipelineSession via session.add_record().
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from agent_prov._frames import SessionProtocol, _NodeFrame, _ToolFrame
from agent_prov._hashing import _now_iso8601, hash_content

logger = logging.getLogger(__name__)

# Sentinel written to tool_version when no version can be resolved. It satisfies
# the schema's minLength constraint and keeps an uninstrumented tool from
# crashing the pipeline, but it carries no drift-detection signal — so the
# fallback is logged at WARNING level rather than applied silently. Deployments
# that care about version drift should supply an explicit tool_version.
_UNVERSIONED = "unversioned"


def emit_tool_invocation(
    frame: _ToolFrame,
    output: Any,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build a successful Tool Invocation Record from a matched tool call pair."""
    record = _base_record(frame, session, nodes)
    record["status"] = "success"
    record["output_hash"] = hash_content(output)
    session.add_record(record)


def emit_tool_invocation_error(
    frame: _ToolFrame,
    error: BaseException,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build a Tool Invocation Record for a tool call that raised before returning.

    A failed tool call is an auditable event (EU AI Act Art. 12(2)(a)): the
    record carries the same identity, tool, input, and timing as a successful
    call, but ``output_hash`` is null and the failure is described by
    ``error_type`` / ``error_hash``.
    """
    record = _base_record(frame, session, nodes)
    record["status"] = "error"
    record["error"] = {
        "type": type(error).__name__,
        "message_hash": hash_content(str(error)),
        "source": "tool",
    }
    session.add_record(record)


def _base_record(
    frame: _ToolFrame,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> dict[str, Any]:
    """Fields shared by the success and error Tool Invocation Records."""
    return {
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
        "reference_data_id": None,
        "parent_record_id": getattr(session, "last_record_id", None),
    }


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
    logger.warning(
        "No tool_version for tool %r; recording %r. Drift detection for this "
        "tool is degraded -- supply an explicit version via the serialized "
        "'version' kwarg or a 'tool_version' metadata key.",
        _extract_tool_name(frame),
        _UNVERSIONED,
    )
    return _UNVERSIONED


def _derive_agent_id(frame: _ToolFrame, nodes: dict[UUID, _NodeFrame]) -> str:
    if frame.parent_run_id is not None and frame.parent_run_id in nodes:
        return nodes[frame.parent_run_id].node_name
    if frame.parent_run_id is not None:
        return str(frame.parent_run_id)
    return "unknown"
