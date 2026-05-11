"""PipelineSession — collects provenance records for one pipeline execution.

Generates pipeline_id and session_id UUIDs, maintains the ordered record
list, and tracks last_record_id so emitters can wire parent-record chains
without querying the list.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


_DEFAULT_PROTOCOL_VERSION = "0.1.0"


class PipelineSession:
    """Accumulates provenance records for a single pipeline execution.

    Satisfies SessionProtocol (core.py) so that ProvenanceMiddleware can
    interact with it without a hard import dependency.

    Args:
        pipeline_id: Identifier for the pipeline definition. Supply this when
            a single logical pipeline spans multiple sessions (e.g. retries or
            scheduled runs). Omit to generate a fresh UUID.
        protocol_version: Semver string stamped on every emitted record.
    """

    def __init__(
        self,
        *,
        pipeline_id: str | None = None,
        protocol_version: str = _DEFAULT_PROTOCOL_VERSION,
    ) -> None:
        self.pipeline_id: str = pipeline_id or str(uuid4())
        self.session_id: str = str(uuid4())
        self.protocol_version: str = protocol_version
        self.records: list[dict[str, Any]] = []
        self.last_record_id: str | None = None

    def add_record(self, record: dict[str, Any]) -> None:
        """Append *record* to the session and update last_record_id."""
        self.records.append(record)
        self.last_record_id = record["record_id"]

    def __len__(self) -> int:
        return len(self.records)
