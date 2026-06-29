"""Agent Step Record emitter for the LangChain adapter.

Extracts model identity, the run-stable semantic projection of the input/output
messages, and agent_id from a completed ``_StepFrame`` / LLM response pair, then
hands those primitives to the session's record factory
(``session.add_agent_step`` / ``add_agent_step_error``). Record assembly and
hashing live in the session; this module owns only the LangChain-specific
extraction and message projection.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_prov.adapters.langchain._frames import (
    _NodeFrame,
    _StepFrame,
    _derive_agent_id,
)
from agent_prov.session import SessionProtocol


def emit_agent_step(
    frame: _StepFrame,
    response: Any,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build a successful Agent Step Record from a matched LLM call pair."""
    session.add_agent_step(
        agent_id=_derive_agent_id(frame, nodes),
        model_id=_extract_model_id(frame),
        model_version=_extract_model_version(frame),
        timestamp_start=frame.timestamp_start,
        input=_semantic_input(frame.messages),
        output=_semantic_output(response),
        reference_data_id=frame.metadata.get("reference_data_id"),
    )


def emit_agent_step_error(
    frame: _StepFrame,
    error: BaseException,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build an Agent Step Record for an LLM call that failed before completing.

    A failed step is itself an auditable event (EU AI Act Art. 12(2)(a)): the
    record carries the same identity, model, input, and timing as a successful
    step, but ``output_hash`` is absent and the failure is described by a
    structured ``error`` object sourced from the provider boundary.
    """
    session.add_agent_step_error(
        agent_id=_derive_agent_id(frame, nodes),
        model_id=_extract_model_id(frame),
        model_version=_extract_model_version(frame),
        timestamp_start=frame.timestamp_start,
        input=_semantic_input(frame.messages),
        error_type=type(error).__name__,
        error_message=str(error),
        source="provider",
    )


# ---------------------------------------------------------- semantic projection
#
# Hashing raw messages is not run-stable: LangChain stamps a fresh ``id`` on
# every generated ``AIMessage`` (and a fresh ``tool_call_id`` on every
# ``ToolMessage``). Replaying the same pipeline with the same prompt would then
# yield a different ``input_hash`` / ``output_hash`` on each run, even when
# nothing semantically changed - defeating the auditor's "did this input
# produce this output" check. The projection below keeps only the semantic
# fields (type, content, tool-call name/args, tool name on tool responses) and
# is applied symmetrically on both sides so a single conversation digests
# identically across runs.


def _semantic_message(msg: Any) -> dict[str, Any]:
    """Reduce a single chat message to its run-stable semantic payload.

    Keeps ``type`` (so HumanMessage / AIMessage / ToolMessage do not collide
    on identical content), ``content``, and any ``tool_calls`` (themselves
    projected to drop runtime ids). Includes a ToolMessage's ``name`` when
    present - the tool name is semantic and lets the auditor see which tool
    produced a given response.
    """
    payload: dict[str, Any] = {
        "type": _get(msg, "type"),
        "content": _get(msg, "content"),
        "tool_calls": _normalize_tool_calls(_get(msg, "tool_calls")),
    }
    name = _get(msg, "name")
    if name is not None:
        payload["name"] = name
    return payload


def _semantic_input(messages: Any) -> Any:
    """Project the batched LLM input messages to their run-stable shape.

    ``frame.messages`` follows LangChain's batched ``list[list[BaseMessage]]``
    convention; preserve that nesting so the digest distinguishes a batched
    call from a flat list of the same messages.
    """
    if not messages:
        return messages
    return [[_semantic_message(m) for m in batch] for batch in messages]


def _semantic_output(response: Any) -> Any:
    """Reduce an LLM response to its run-stable semantic payload.

    Falls back to hashing the response whole if it has no recognisable
    ``generations`` structure - better an opaque digest than a dropped output.
    """
    generations = _get(response, "generations")
    if not generations:
        return response
    payload: list[dict[str, Any]] = []
    for batch in generations:
        for generation in batch:
            message = _get(generation, "message")
            if message is None:
                payload.append({"text": _get(generation, "text")})
            else:
                payload.append(_semantic_message(message))
    return payload


def _normalize_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    """Keep only the semantic (name, args) of each tool call; drop runtime ids."""
    if not tool_calls:
        return []
    return [{"name": _get(tc, "name"), "args": _get(tc, "args")} for tc in tool_calls]


def _get(obj: Any, key: str) -> Any:
    """Read *key* from a mapping or an attribute-bearing object, else ``None``."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


# ------------------------------------------------------------------ extraction


def _extract_model_id(frame: _StepFrame) -> str:
    # LangSmith standard metadata key - most reliable source
    if name := frame.metadata.get("ls_model_name"):
        return str(name)
    # Provider-specific serialized kwargs
    kwargs = frame.serialized.get("kwargs", {})
    for key in ("model", "model_name"):
        if val := kwargs.get(key):
            return str(val)
    # Fall back to the class name (e.g. "ChatOpenAI") - coarse but non-empty
    return frame.serialized.get("name", "unknown") or "unknown"


def _extract_model_version(frame: _StepFrame) -> str:
    kwargs = frame.serialized.get("kwargs", {})
    if v := kwargs.get("model_version"):
        return str(v)
    # When no distinct version is available the model_id string serves as both
    # identifier and version (e.g. "gpt-4o-2024-11-20" or "claude-opus-4-7").
    return _extract_model_id(frame)
