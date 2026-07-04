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

This module also exposes the helpers both emitters share: ``_derive_agent_id``,
the resolver that turns a frame's enclosing node into an ``agent_id``, and
``_runtime_metadata``, the builder for the non-hashed forensic side field. Both
live here because they operate purely on frame-level primitives and are used by
``step_emitter`` and ``tool_emitter`` alike, so neither owns them.
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


def _runtime_metadata(
    run_id: Any,
    tool_call_ids: dict[str, str] | None = None,
    message_id: Any = None,
) -> dict[str, Any]:
    """Assemble the non-hashed forensic side field shared by both emitters.

    Carries only the runtime identifiers the semantic projection keeps out of
    the content hashes so a record stays cross-referenceable with provider and
    framework logs: ``run_id`` (the framework execution id), ``message_id`` (the
    provider's response id), and ``tool_call_ids`` (the canonical-label -> real
    tool_call_id map). Each key is included only when it carries a non-empty
    value: a missing id, or an empty one a provider may emit, would otherwise
    fail the ``runtime_metadata`` schema (``minLength`` 1). The session factory
    drops the whole field when it ends up empty, so an all-absent side field
    never reaches the record.
    """
    meta: dict[str, Any] = {}
    if run_id:
        meta["run_id"] = str(run_id)
    if message_id:
        meta["message_id"] = str(message_id)
    if tool_call_ids:
        meta["tool_call_ids"] = tool_call_ids
    return meta
