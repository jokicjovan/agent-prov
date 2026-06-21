"""Lifecycle frame types for the LangChain provenance middleware.

A *frame* is a short-lived bucket that holds the payload of a callback
``*_start`` event until its matching ``*_end`` event arrives. The middleware
(``middleware``) opens and closes frames; the emitters (``step_emitter``,
``tool_emitter``) read them and project their LangChain-specific fields
(``serialized`` / ``messages`` / ``input_str``) before handing primitives to the
session's record factory.

Keeping the frame dataclasses in this leaf module — imported by both
``middleware`` and the emitters, importing nothing from them in return — is what
lets every module in the adapter resolve its imports at load time. A shared
definition in ``middleware`` would instead force ``middleware`` and the emitters
into a circular import.
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
