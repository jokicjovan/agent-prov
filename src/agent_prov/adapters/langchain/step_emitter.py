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
    _runtime_metadata,
)
from agent_prov.session import SessionProtocol


def emit_agent_step(
    frame: _StepFrame,
    response: Any,
    session: SessionProtocol,
    nodes: dict[UUID, _NodeFrame],
) -> None:
    """Build a successful Agent Step Record from a matched LLM call pair."""
    # Project the output first, capturing the runtime ids it strips from the
    # hash (the tool-call label map and the response id), so runtime_metadata is
    # built from returned values rather than a projection side effect.
    projected_output, tool_call_ids, message_id = _project_output(response)
    session.add_agent_step(
        agent_id=_derive_agent_id(frame, nodes),
        model_id=_extract_model_id(frame),
        model_version=_extract_model_version(frame),
        timestamp_start=frame.timestamp_start,
        input=_semantic_input(frame.messages),
        output=projected_output,
        reference_data_id=frame.metadata.get("reference_data_id"),
        runtime_metadata=_runtime_metadata(frame.run_id, tool_call_ids, message_id),
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
        runtime_metadata=_runtime_metadata(frame.run_id),
    )


# ---------------------------------------------------------- semantic projection
#
# Hashing raw messages is not run-stable: LangChain stamps a fresh ``id`` on
# every generated ``AIMessage`` and a fresh ``tool_call_id`` on every tool call
# and ``ToolMessage``. Replaying the same pipeline with the same prompt would
# then yield a different ``input_hash`` / ``output_hash`` on each run, even when
# nothing semantically changed - defeating the auditor's "did this input produce
# this output" check.
#
# The projection keeps only the semantic fields (type, content, tool-call
# name/args, tool name on tool responses) and is applied symmetrically on both
# sides. For the identifiers that carry *correlation* - a tool call's id and the
# ``tool_call_id`` on the ``ToolMessage`` that answers it - stripping is not
# enough: it discards which result answered which call, and a step that fires
# several tool calls at once (or receives their results out of order) can no
# longer be told apart from a differently-wired one. Instead of stripping these
# correlation ids, the projection *rewrites* them to deterministic labels
# ("0", "1", "2", ...) assigned in order of first appearance within one
# projection scope (see ``_IdCanonicalizer``). The label is run-stable (it
# depends only on structure, not on the random runtime id) yet preserves the
# call-to-result edge inside the digest.
#
# The free-standing ``AIMessage.id`` correlates with nothing inside a step and
# is not reliably present across runs, so it is kept out of the hash entirely;
# its real runtime value is preserved in the non-hashed ``runtime_metadata``
# side field instead, alongside the label-to-real-id map for the tool calls.


class _IdCanonicalizer:
    """Assigns deterministic ``0, 1, 2, ...`` labels to runtime ids in one scope.

    A projection scope (the input message list, or the output generations) gets
    its own instance. The first distinct runtime id seen becomes ``"0"``, the
    next ``"1"``, and so on; the same runtime id always maps to the same label,
    so a tool call and the ``ToolMessage`` that references its ``tool_call_id``
    resolve to one label and their correlation survives into the hash.
    ``mapping`` records the inverse (label -> real id) for ``runtime_metadata``.
    """

    def __init__(self) -> None:
        self._labels: dict[str, str] = {}

    def canonical(self, runtime_id: Any) -> str | None:
        if not runtime_id:
            # None or an empty id: nothing to correlate, and an empty label
            # would fail the runtime_metadata schema (minLength 1). Treat it as
            # "no id" so it is omitted from both the hash and the id map.
            return None
        key = str(runtime_id)
        label = self._labels.get(key)
        if label is None:
            label = str(len(self._labels))
            self._labels[key] = label
        return label

    @property
    def mapping(self) -> dict[str, str]:
        """Inverse view: canonical label -> real runtime id, built on demand.

        Only the output scope reads this (to populate ``runtime_metadata``); the
        input scope needs the labels but never the inverse, so nothing is built
        for it.
        """
        return {label: real for real, label in self._labels.items()}


def _semantic_message(msg: Any, ids: _IdCanonicalizer) -> dict[str, Any]:
    """Reduce a single chat message to its run-stable semantic payload.

    Keeps ``type`` (so HumanMessage / AIMessage / ToolMessage do not collide on
    identical content), ``content``, and any ``tool_calls`` (themselves projected
    to canonical-label ids). Includes a ToolMessage's ``name`` when present - the
    tool name is semantic - and its ``tool_call_id`` rewritten through *ids*, so
    the edge back to the originating tool call is preserved in the digest.
    """
    payload: dict[str, Any] = {
        "type": _get(msg, "type"),
        "content": _get(msg, "content"),
        "tool_calls": _normalize_tool_calls(_get(msg, "tool_calls"), ids),
    }
    name = _get(msg, "name")
    if name is not None:
        payload["name"] = name
    tool_call_id = _get(msg, "tool_call_id")
    if tool_call_id is not None:
        payload["tool_call_id"] = ids.canonical(tool_call_id)
    return payload


def _semantic_input(messages: Any) -> Any:
    """Project the batched LLM input messages to their run-stable shape.

    ``frame.messages`` follows LangChain's batched ``list[list[BaseMessage]]``
    convention; preserve that nesting so the digest distinguishes a batched
    call from a flat list of the same messages. All messages share one
    canonicalizer scope so tool-call/tool-result correlation is resolved across
    the history; the scope is local because the input side only needs the
    labels, never the inverse label -> id map.
    """
    if not messages:
        return messages
    ids = _IdCanonicalizer()
    return [[_semantic_message(m, ids) for m in batch] for batch in messages]


def _project_output(response: Any) -> tuple[Any, dict[str, str], Any]:
    """Project an LLM response and collect the ids kept out of the hash.

    Walks the response once and returns ``(payload, tool_call_ids, message_id)``:

    * ``payload`` - the run-stable semantic view that gets hashed into
      ``output_hash`` (per generation, the message content and its tool calls
      with canonical-label ids).
    * ``tool_call_ids`` - the canonical-label -> real ``tool_call_id`` map for
      ``runtime_metadata``.
    * ``message_id`` - the provider's response id (first message carrying one),
      or ``None``. Kept out of the hash, preserved in ``runtime_metadata``.

    Falls back to hashing the response whole if it has no recognisable
    ``generations`` structure - better an opaque digest than a dropped output.
    """
    generations = _get(response, "generations")
    if not generations:
        return response, {}, None
    ids = _IdCanonicalizer()
    payload: list[dict[str, Any]] = []
    message_id: Any = None
    for batch in generations:
        for generation in batch:
            message = _get(generation, "message")
            if message is None:
                payload.append({"text": _get(generation, "text")})
                continue
            if message_id is None:
                message_id = _get(message, "id")
            payload.append(_semantic_message(message, ids))
    return payload, ids.mapping, message_id


def _normalize_tool_calls(tool_calls: Any, ids: _IdCanonicalizer) -> list[dict[str, Any]]:
    """Project each tool call to (name, args, canonical id); drop the raw id.

    The tool call's runtime ``id`` is rewritten to its canonical label through
    *ids* so the correlation to the answering ``ToolMessage`` is kept in the
    hash; the label is omitted when the call carries no id.
    """
    if not tool_calls:
        return []
    projected: list[dict[str, Any]] = []
    for tc in tool_calls:
        call: dict[str, Any] = {"name": _get(tc, "name"), "args": _get(tc, "args")}
        label = ids.canonical(_get(tc, "id"))
        if label is not None:
            call["id"] = label
        projected.append(call)
    return projected


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
