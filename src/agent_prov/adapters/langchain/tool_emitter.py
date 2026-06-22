"""Tool Invocation Record emitter for the LangChain adapter.

Extracts tool identity and the input string from a completed ``_ToolFrame`` /
tool output pair, then hands those primitives to the session's record factory
(``session.add_tool_invocation`` / ``add_tool_invocation_error``). Record
assembly and hashing live in the session; this module owns only the
LangChain-specific extraction.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from agent_prov.adapters.langchain._frames import (
    _NodeFrame,
    _ToolFrame,
    _derive_agent_id,
)
from agent_prov.session import SessionProtocol

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
    session.add_tool_invocation(
        agent_id=_derive_agent_id(frame, nodes),
        tool_name=_extract_tool_name(frame),
        tool_version=_extract_tool_version(frame),
        timestamp_start=frame.timestamp_start,
        input=frame.input_str,
        output=output,
        reference_data_id=frame.metadata.get("reference_data_id"),
    )


def emit_tool_invocation_error(
    frame: _ToolFrame,
    error: BaseException,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build a Tool Invocation Record for a tool call that raised before returning.

    A failed tool call is an auditable event (EU AI Act Art. 12(2)(a)): the
    record carries the same identity, tool, input, and timing as a successful
    call, but ``output_hash`` is absent and the failure is described by a
    structured ``error`` object sourced from the tool boundary.
    """
    session.add_tool_invocation_error(
        agent_id=_derive_agent_id(frame, nodes),
        tool_name=_extract_tool_name(frame),
        tool_version=_extract_tool_version(frame),
        timestamp_start=frame.timestamp_start,
        input=frame.input_str,
        error_type=type(error).__name__,
        error_message=str(error),
        source="tool",
    )


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
