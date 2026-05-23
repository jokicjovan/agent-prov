"""Agent Step Record emitter.

Extracts model identity, content hashes, and agent_id from a completed
_StepFrame / LLM response pair, assembles an Agent Step Record, and
hands it to the PipelineSession via session.add_record().
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from middleware._frames import SessionProtocol, _NodeFrame, _StepFrame
from middleware._hashing import _now_iso8601, hash_content


def emit_agent_step(
    frame: _StepFrame,
    response: Any,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build an Agent Step Record from a matched LLM call pair and add it to the session."""
    record = {
        "record_id": str(uuid4()),
        "record_type": "agent_step",
        "protocol_version": session.protocol_version,
        "pipeline_id": session.pipeline_id,
        "session_id": session.session_id,
        "agent_id": _derive_agent_id(frame, nodes),
        "model_id": _extract_model_id(frame),
        "model_version": _extract_model_version(frame),
        "timestamp_start": frame.timestamp_start,
        "timestamp_end": _now_iso8601(),
        "input_hash": hash_content(frame.messages),
        "output_hash": hash_content(_semantic_output(response)),
        "reference_data_id": None,
        "parent_record_id": getattr(session, "last_record_id", None),
    }
    session.add_record(record)


# ------------------------------------------------------------- response payload


def _semantic_output(response: Any) -> Any:
    """Reduce an LLM response to its run-stable semantic payload for hashing.

    Hashing the full response object is not reproducible: LangChain stamps a
    fresh ``id`` on every generated message (and on every tool call), so an
    identical answer would digest differently on each run. This projection
    keeps only what is semantically the model's output — the message content
    and the name/args of any tool calls — and drops runtime identifiers and
    transport metadata, so identical output yields an identical ``output_hash``
    across runs. Tool calls are retained because a step that emits only a tool
    call carries no content, and hashing content alone would make every such
    step collide.

    Falls back to hashing the response whole if it has no recognisable
    ``generations`` structure — better an opaque digest than a dropped output.
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
                payload.append(
                    {
                        "content": _get(message, "content"),
                        "tool_calls": _normalize_tool_calls(_get(message, "tool_calls")),
                    }
                )
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
    # LangSmith standard metadata key — most reliable source
    if name := frame.metadata.get("ls_model_name"):
        return str(name)
    # Provider-specific serialized kwargs
    kwargs = frame.serialized.get("kwargs", {})
    for key in ("model", "model_name"):
        if val := kwargs.get(key):
            return str(val)
    # Fall back to the class name (e.g. "ChatOpenAI") — coarse but non-empty
    return frame.serialized.get("name", "unknown") or "unknown"


def _extract_model_version(frame: _StepFrame) -> str:
    kwargs = frame.serialized.get("kwargs", {})
    if v := kwargs.get("model_version"):
        return str(v)
    # When no distinct version is available the model_id string serves as both
    # identifier and version (e.g. "gpt-4o-2024-11-20" or "claude-opus-4-7").
    return _extract_model_id(frame)


def _derive_agent_id(frame: _StepFrame, nodes: dict[UUID, _NodeFrame]) -> str:
    if frame.parent_run_id is not None and frame.parent_run_id in nodes:
        return nodes[frame.parent_run_id].node_name
    if frame.parent_run_id is not None:
        return str(frame.parent_run_id)
    return "unknown"
