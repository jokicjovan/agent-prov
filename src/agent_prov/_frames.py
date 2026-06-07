"""Lifecycle frame types and the session seam for the provenance middleware.

A *frame* is a short-lived bucket that holds the payload of a callback
``*_start`` event until its matching ``*_end`` event arrives. The middleware
(``core``) opens and closes frames; the emitters (``step_emitter``,
``tool_emitter``) read them.

Keeping the frame dataclasses and the ``SessionProtocol`` seam in this leaf
module — imported by both ``core`` and the emitters, importing nothing from
``middleware`` itself — is what lets every module resolve its imports at load
time. A shared definition in ``core`` would instead force ``core`` and the
emitters into a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class SessionProtocol(Protocol):
    """Minimal interface the middleware needs from a `PipelineSession`."""

    pipeline_id: str
    session_id: str
    protocol_version: str

    def add_record(self, record: dict[str, Any]) -> None: ...


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
