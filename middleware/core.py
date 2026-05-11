"""ProvenanceMiddleware — LangChain callback handler that drives record emission.

The middleware subscribes to LangGraph/LangChain lifecycle events (node, chat
model, tool) and routes them to per-run-id state buckets. The buckets are
drained by emitter helpers (`step_emitter`, `tool_emitter`) that complete
the record and hand it to the `PipelineSession`.

This module owns only the lifecycle wiring: opening a bucket on `*_start`,
closing it on `*_end`, and surfacing the matched start/end pair to the
emitter. Field extraction (model identity, hashes, agent_id derivation)
lives in the emitter modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler


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


class ProvenanceMiddleware(BaseCallbackHandler):
    """Callback handler that opens lifecycle frames and surfaces matched pairs.

    Pass an instance into `graph.invoke(state, config={"callbacks": [mw]})`
    or attach it on the model/tool at construction time.
    """

    def __init__(self, session: SessionProtocol) -> None:
        self.session = session
        self._nodes: dict[UUID, _NodeFrame] = {}
        self._steps: dict[UUID, _StepFrame] = {}
        self._tools: dict[UUID, _ToolFrame] = {}

    # ------------------------------------------------------------------ nodes

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        node_name = (
            (serialized or {}).get("name")
            or (kwargs.get("name") if isinstance(kwargs.get("name"), str) else None)
            or "unknown"
        )
        self._nodes[run_id] = _NodeFrame(
            run_id=run_id,
            parent_run_id=parent_run_id,
            node_name=node_name,
            timestamp_start=_now_iso8601(),
            inputs=inputs or {},
        )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._nodes.pop(run_id, None)

    # ------------------------------------------------------------ agent steps

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._steps[run_id] = _StepFrame(
            run_id=run_id,
            parent_run_id=parent_run_id,
            timestamp_start=_now_iso8601(),
            serialized=serialized or {},
            messages=messages or [],
            metadata=metadata or {},
        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        frame = self._steps.pop(run_id, None)
        if frame is None:
            return
        self._on_step_complete(frame, response)

    def _on_step_complete(self, frame: _StepFrame, response: Any) -> None:
        """Hand the matched start/end pair to the Agent Step emitter."""
        from middleware.step_emitter import emit_agent_step  # late import avoids circularity

        emit_agent_step(frame, response, self.session, self._nodes)

    # ------------------------------------------------------------------ tools

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._tools[run_id] = _ToolFrame(
            run_id=run_id,
            parent_run_id=parent_run_id,
            timestamp_start=_now_iso8601(),
            serialized=serialized or {},
            input_str=input_str or "",
            metadata=metadata or {},
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        frame = self._tools.pop(run_id, None)
        if frame is None:
            return
        self._on_tool_complete(frame, output)

    def _on_tool_complete(self, frame: _ToolFrame, output: Any) -> None:
        """Hand the matched start/end pair to the Tool Invocation emitter."""
        from middleware.tool_emitter import emit_tool_invocation  # late import avoids circularity

        emit_tool_invocation(frame, output, self.session, self._nodes)

    # --------------------------------------------------------------- helpers

    @property
    def in_flight(self) -> dict[str, int]:
        """Counts of unmatched `*_start` events — useful for tests."""
        return {
            "nodes": len(self._nodes),
            "steps": len(self._steps),
            "tools": len(self._tools),
        }


def _now_iso8601() -> str:
    """UTC ISO 8601 timestamp with `Z` suffix (matches schema `iso8601_timestamp`)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
