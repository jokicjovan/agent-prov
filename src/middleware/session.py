"""PipelineSession — collects provenance records for one pipeline execution.

Generates pipeline_id and session_id UUIDs, maintains the ordered record
list, and tracks last_record_id so emitters can wire parent-record chains
without querying the list.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4


_DEFAULT_PROTOCOL_VERSION = "0.1.0"

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


class PipelineSession:
    """Accumulates provenance records for a single pipeline execution.

    Satisfies SessionProtocol (_frames.py) so that ProvenanceMiddleware can
    interact with it without a hard import dependency.

    Args:
        pipeline_id: Identifier for the pipeline definition. Supply this when
            a single logical pipeline spans multiple sessions (e.g. retries or
            scheduled runs). Must be a lowercase RFC 4122 UUID; omit to generate
            a fresh one.
        protocol_version: Semver string stamped on every emitted record.

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

    def add_record(self, record: dict[str, Any]) -> None:
        """Append *record* to the session and update last_record_id."""
        self.records.append(record)
        self.last_record_id = record["record_id"]

    def __len__(self) -> int:
        return len(self.records)
