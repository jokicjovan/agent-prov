"""Lifecycle frame types for the LangChain provenance middleware.

A *frame* is a short-lived bucket that holds the payload of a callback
``*_start`` event until its matching ``*_end`` event arrives. The middleware
(``middleware``) opens and closes frames; the emitters (``step_emitter``,
``tool_emitter``) read them and project their LangChain-specific fields
(``serialized`` / ``messages`` / ``input_str``) before handing primitives to the
session's record factory.

Keeping the frame dataclasses in this leaf module - imported by both
``middleware`` and the emitters, importing nothing from them in return - is what
lets every module in the adapter resolve its imports at load time. A shared
definition in ``middleware`` would instead force ``middleware`` and the emitters
into a circular import.

This module also exposes ``_derive_agent_id``, the resolver both emitters use to
turn a frame's enclosing node into an ``agent_id`` - it lives here because it
operates purely on the frame types and is shared by the two emitters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass
class _NodeFrame:
    """Lifecycle bucket for an `on_chain_start`/`on_chain_end` pair (LangGraph node)."""

    run_id: UUID
    parent_run_id: UUID | None
    node_name: str
    timestamp_start: str
    inputs: dict[str, Any]


@dataclass
class _StepFrame:
    """Lifecycle bucket for an `on_chat_model_start`/`on_llm_end` pair."""

    run_id: UUID
    parent_run_id: UUID | None
    timestamp_start: str
    serialized: dict[str, Any]
    messages: list[list[Any]]
    metadata: dict[str, Any]


@dataclass
class _ToolFrame:
    """Lifecycle bucket for an `on_tool_start`/`on_tool_end` pair."""

    run_id: UUID
    parent_run_id: UUID | None
    timestamp_start: str
    serialized: dict[str, Any]
    input_str: str
    metadata: dict[str, Any]


def _derive_agent_id(
    frame: _StepFrame | _ToolFrame,
    nodes: dict[UUID, _NodeFrame],
) -> str:
    """Resolve the ``agent_id`` for a step or tool frame from its enclosing node.

    A model or tool call runs inside a graph node, and the node's name is the
    agent_id. Resolve it by looking up the frame's ``parent_run_id`` in the
    still-open ``nodes`` map; fall back to the raw parent id, then ``"unknown"``,
    so the field stays a schema-valid non-empty string under unusual graph shapes.
    """
    if frame.parent_run_id is not None and frame.parent_run_id in nodes:
        return nodes[frame.parent_run_id].node_name
    if frame.parent_run_id is not None:
        return str(frame.parent_run_id)
    return "unknown"
