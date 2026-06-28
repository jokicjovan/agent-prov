"""PipelineSession — collects provenance records for one pipeline execution.

Generates pipeline_id and session_id UUIDs, maintains the ordered record
list, and tracks last_record_id so the parent-record chain is wired without
querying the list.

This module also owns the framework-neutral record factory: ``add_agent_step``
and ``add_tool_invocation`` (plus their ``_error`` variants) assemble a record,
hash the supplied input/output, stamp the end timestamp, wire the parent chain,
and append. An adapter's only job is to extract framework primitives and call
these — record shape and hashing live here, not in any one adapter. The
``SessionProtocol`` seam below is the framework-neutral interface those adapters
code against; ``PipelineSession`` is its canonical implementor.

``now_iso8601`` is re-exported here so that ``agent_prov.session`` is the single
public import home for everything an adapter needs to drive the factory by hand:
the session, the ``SessionProtocol`` seam, the ``add_*`` methods, and the
start-timestamp helper an adapter stamps before each observed call.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from agent_prov._hashing import now_iso8601, hash_content


_DEFAULT_PROTOCOL_VERSION = "0.2.0"

# Mirrored from the JSON Schema `$defs/uuid` and `$defs/semver` patterns. Validating
# user-supplied identifiers at construction time fails loudly here, rather than
# silently producing a bundle that fails Pipeline Bundle schema validation downstream.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


@runtime_checkable
class EventSink(Protocol):
    """Durability sink a session streams records to as they are appended.

    Implemented by :class:`agent_prov.persistence.EventLog`. Declared here as a
    structural type so ``session.py`` stays a framework-neutral leaf: it never
    imports ``persistence`` (which imports it), avoiding a cycle.
    """

    def write_header(
        self, *, pipeline_id: str, session_id: str, protocol_version: str
    ) -> None: ...

    def append_record(self, record: dict[str, Any]) -> None: ...


@runtime_checkable
class SessionProtocol(Protocol):
    """Framework-neutral interface an adapter needs from a `PipelineSession`.

    Adapters (e.g. the LangChain middleware) extract framework primitives and
    call the ``add_*`` factory methods; they never assemble records or hash
    content themselves. ``add_record`` remains exposed for the rare adapter that
    has already built a complete record.
    """

    pipeline_id: str
    session_id: str
    protocol_version: str
    last_record_id: str | None

    def add_record(self, record: dict[str, Any]) -> None: ...

    def add_agent_step(
        self,
        *,
        agent_id: str,
        model_id: str,
        model_version: str,
        timestamp_start: str,
        input: Any,
        output: Any,
        reference_data_id: str | None = None,
    ) -> dict[str, Any]: ...

    def add_agent_step_error(
        self,
        *,
        agent_id: str,
        model_id: str,
        model_version: str,
        timestamp_start: str,
        input: Any,
        error_type: str,
        error_message: str | None = None,
        source: str = "provider",
        retryable: bool | None = None,
        reference_data_id: str | None = None,
    ) -> dict[str, Any]: ...

    def add_tool_invocation(
        self,
        *,
        agent_id: str,
        tool_name: str,
        tool_version: str,
        timestamp_start: str,
        input: Any,
        output: Any,
        reference_data_id: str | None = None,
    ) -> dict[str, Any]: ...

    def add_tool_invocation_error(
        self,
        *,
        agent_id: str,
        tool_name: str,
        tool_version: str,
        timestamp_start: str,
        input: Any,
        error_type: str,
        error_message: str | None = None,
        source: str = "tool",
        retryable: bool | None = None,
        reference_data_id: str | None = None,
    ) -> dict[str, Any]: ...


class PipelineSession:
    """Accumulates provenance records for a single pipeline execution.

    Satisfies SessionProtocol so that an adapter can interact with it without a
    hard import dependency.

    Args:
        pipeline_id: Identifier for the pipeline definition. Supply this when
            a single logical pipeline spans multiple sessions (e.g. retries or
            scheduled runs). Must be a lowercase RFC 4122 UUID; omit to generate
            a fresh one.
        protocol_version: Semver string stamped on every emitted record.
        event_log: Optional durability sink (an
            :class:`agent_prov.persistence.EventLog`). When supplied, the
            session header is written immediately and every appended record is
            streamed to it, so an unsealed run survives a crash and can be
            recovered with :func:`agent_prov.persistence.recover_session`.

    Raises:
        ValueError: if a supplied ``pipeline_id`` is not a lowercase UUID, or
            ``protocol_version`` is not a valid semver string. Both patterns
            mirror the JSON Schema definitions; rejecting bad values here
            prevents a session from producing a bundle that would fail
            downstream schema validation.
    """

    def __init__(
        self,
        *,
        pipeline_id: str | None = None,
        protocol_version: str = _DEFAULT_PROTOCOL_VERSION,
        event_log: EventSink | None = None,
    ) -> None:
        if pipeline_id is not None and not _UUID_RE.match(pipeline_id):
            raise ValueError(
                f"pipeline_id must be a lowercase RFC 4122 UUID; got {pipeline_id!r}"
            )
        if not _SEMVER_RE.match(protocol_version):
            raise ValueError(
                f"protocol_version must be a semver string (semver.org); got {protocol_version!r}"
            )

        self.pipeline_id: str = pipeline_id or str(uuid4())
        self.session_id: str = str(uuid4())
        self.protocol_version: str = protocol_version
        self.records: list[dict[str, Any]] = []
        self.last_record_id: str | None = None
        self._event_log = event_log
        if event_log is not None:
            event_log.write_header(
                pipeline_id=self.pipeline_id,
                session_id=self.session_id,
                protocol_version=self.protocol_version,
            )

    def add_record(self, record: dict[str, Any]) -> None:
        """Append *record* to the session and update last_record_id.

        When an event log is attached the record is streamed to it after the
        in-memory state is updated, so the in-memory bundle stays complete even
        if the durable write raises (e.g. the disk is full).
        """
        self.records.append(record)
        self.last_record_id = record["record_id"]
        if self._event_log is not None:
            self._event_log.append_record(record)

    # ----------------------------------------------------------- record factory
    #
    # Framework-neutral assembly: an adapter passes already-projected, JSON-
    # serialisable primitives (input/output content, identity, timing); these
    # methods hash the content, stamp the end timestamp, wire parent_record_id,
    # append via add_record, and return the record. Keeping assembly and hashing
    # here (not in an adapter) is what makes a second adapter cheap to write.

    def add_agent_step(
        self,
        *,
        agent_id: str,
        model_id: str,
        model_version: str,
        timestamp_start: str,
        input: Any,
        output: Any,
        reference_data_id: str | None = None,
    ) -> dict[str, Any]:
        """Assemble and append a successful Agent Step Record."""
        record = self._agent_step_base(
            agent_id=agent_id,
            model_id=model_id,
            model_version=model_version,
            timestamp_start=timestamp_start,
            input=input,
            reference_data_id=reference_data_id,
        )
        record["status"] = "success"
        record["output_hash"] = hash_content(output)
        self.add_record(record)
        return record

    def add_agent_step_error(
        self,
        *,
        agent_id: str,
        model_id: str,
        model_version: str,
        timestamp_start: str,
        input: Any,
        error_type: str,
        error_message: str | None = None,
        source: str = "provider",
        retryable: bool | None = None,
        reference_data_id: str | None = None,
    ) -> dict[str, Any]:
        """Assemble and append an Agent Step Record for a failed LLM call.

        A failed step is itself an auditable event (EU AI Act Art. 12(2)(a)):
        the record carries the same identity, model, input, and timing as a
        successful step, but ``output_hash`` is absent and the failure is
        described by a structured ``error`` object.
        """
        record = self._agent_step_base(
            agent_id=agent_id,
            model_id=model_id,
            model_version=model_version,
            timestamp_start=timestamp_start,
            input=input,
            reference_data_id=reference_data_id,
        )
        record["status"] = "error"
        record["error"] = _error_detail(error_type, error_message, source, retryable)
        self.add_record(record)
        return record

    def add_tool_invocation(
        self,
        *,
        agent_id: str,
        tool_name: str,
        tool_version: str,
        timestamp_start: str,
        input: Any,
        output: Any,
        reference_data_id: str | None = None,
    ) -> dict[str, Any]:
        """Assemble and append a successful Tool Invocation Record."""
        record = self._tool_invocation_base(
            agent_id=agent_id,
            tool_name=tool_name,
            tool_version=tool_version,
            timestamp_start=timestamp_start,
            input=input,
            reference_data_id=reference_data_id,
        )
        record["status"] = "success"
        record["output_hash"] = hash_content(output)
        self.add_record(record)
        return record

    def add_tool_invocation_error(
        self,
        *,
        agent_id: str,
        tool_name: str,
        tool_version: str,
        timestamp_start: str,
        input: Any,
        error_type: str,
        error_message: str | None = None,
        source: str = "tool",
        retryable: bool | None = None,
        reference_data_id: str | None = None,
    ) -> dict[str, Any]:
        """Assemble and append a Tool Invocation Record for a failed tool call.

        A failed tool call is an auditable event (EU AI Act Art. 12(2)(a)): the
        record carries the same identity, tool, input, and timing as a
        successful call, but ``output_hash`` is absent and the failure is
        described by a structured ``error`` object.
        """
        record = self._tool_invocation_base(
            agent_id=agent_id,
            tool_name=tool_name,
            tool_version=tool_version,
            timestamp_start=timestamp_start,
            input=input,
            reference_data_id=reference_data_id,
        )
        record["status"] = "error"
        record["error"] = _error_detail(error_type, error_message, source, retryable)
        self.add_record(record)
        return record

    def _agent_step_base(
        self,
        *,
        agent_id: str,
        model_id: str,
        model_version: str,
        timestamp_start: str,
        input: Any,
        reference_data_id: str | None,
    ) -> dict[str, Any]:
        """Fields shared by the success and error Agent Step Records."""
        return {
            "record_id": str(uuid4()),
            "record_type": "agent_step",
            "protocol_version": self.protocol_version,
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
            "agent_id": agent_id,
            "model_id": model_id,
            "model_version": model_version,
            "timestamp_start": timestamp_start,
            "timestamp_end": now_iso8601(),
            "input_hash": hash_content(input),
            "reference_data_id": reference_data_id,
            "parent_record_id": self.last_record_id,
        }

    def _tool_invocation_base(
        self,
        *,
        agent_id: str,
        tool_name: str,
        tool_version: str,
        timestamp_start: str,
        input: Any,
        reference_data_id: str | None,
    ) -> dict[str, Any]:
        """Fields shared by the success and error Tool Invocation Records."""
        return {
            "record_id": str(uuid4()),
            "record_type": "tool_invocation",
            "protocol_version": self.protocol_version,
            "pipeline_id": self.pipeline_id,
            "session_id": self.session_id,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "tool_version": tool_version,
            "timestamp_start": timestamp_start,
            "timestamp_end": now_iso8601(),
            "input_hash": hash_content(input),
            "reference_data_id": reference_data_id,
            "parent_record_id": self.last_record_id,
        }

    def __len__(self) -> int:
        return len(self.records)


def _error_detail(
    error_type: str,
    error_message: str | None,
    source: str,
    retryable: bool | None,
) -> dict[str, Any]:
    """Build the structured ``error`` object for a failure record.

    ``type`` is the (low-PII) exception class name and ``source`` the failure
    boundary; ``message_hash`` follows the same privacy stance as input/output
    hashing. ``retryable`` is included only when the adapter could determine it.
    """
    error: dict[str, Any] = {"type": error_type, "source": source}
    if error_message is not None:
        error["message_hash"] = hash_content(error_message)
    if retryable is not None:
        error["retryable"] = retryable
    return error
