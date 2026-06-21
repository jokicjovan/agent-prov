"""ProvenanceMiddleware — LangChain callback handler that drives record emission.

The middleware subscribes to LangGraph/LangChain lifecycle events (node, chat
model, tool) and routes them to per-run-id state buckets. The buckets are
drained by emitter helpers (`step_emitter`, `tool_emitter`) that project the
LangChain-specific payload and hand the resulting primitives to the
`PipelineSession` record factory.

This module owns only the lifecycle wiring: opening a bucket on `*_start`,
closing it on `*_end`, and surfacing the matched start/end pair to the
emitter. Field extraction (model identity, hashes, agent_id derivation) lives
in the emitter modules; the lifecycle frame types live in `_frames`; the
`SessionProtocol` seam and canonical hashing live in the framework-neutral core.
Splitting those out keeps the import graph acyclic — `middleware` imports the
emitters at module load time, and the emitters import only the leaf modules.

Public surface: ``ProvenanceMiddleware``. Frame types are adapter-internal and
live in their own module.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from agent_prov._hashing import _now_iso8601
from agent_prov.adapters.langchain._frames import _NodeFrame, _StepFrame, _ToolFrame
from agent_prov.adapters.langchain.step_emitter import (
    emit_agent_step,
    emit_agent_step_error,
)
from agent_prov.adapters.langchain.tool_emitter import (
    emit_tool_invocation,
    emit_tool_invocation_error,
)
from agent_prov.session import SessionProtocol


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

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        # Nodes do not emit records (they only supply agent_id context); just
        # release the frame so a failed chain does not leak its bucket.
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

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        frame = self._steps.pop(run_id, None)
        if frame is None:
            return
        self._on_step_error(frame, error)

    def _on_step_complete(self, frame: _StepFrame, response: Any) -> None:
        """Hand the matched start/end pair to the Agent Step emitter."""
        emit_agent_step(frame, response, self.session, self._nodes)

    def _on_step_error(self, frame: _StepFrame, error: BaseException) -> None:
        """Hand a failed LLM call to the Agent Step error emitter."""
        emit_agent_step_error(frame, error, self.session, self._nodes)

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

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        frame = self._tools.pop(run_id, None)
        if frame is None:
            return
        self._on_tool_error(frame, error)

    def _on_tool_complete(self, frame: _ToolFrame, output: Any) -> None:
        """Hand the matched start/end pair to the Tool Invocation emitter."""
        emit_tool_invocation(frame, output, self.session, self._nodes)

    def _on_tool_error(self, frame: _ToolFrame, error: BaseException) -> None:
        """Hand a failed tool call to the Tool Invocation error emitter."""
        emit_tool_invocation_error(frame, error, self.session, self._nodes)

    # --------------------------------------------------------------- helpers

    @property
    def in_flight(self) -> dict[str, int]:
        """Counts of unmatched `*_start` events — useful for tests."""
        return {
            "nodes": len(self._nodes),
            "steps": len(self._steps),
            "tools": len(self._tools),
        }
