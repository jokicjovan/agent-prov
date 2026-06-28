"""Crash-safe persistence: an append-only NDJSON event log.

A :class:`~agent_prov.session.PipelineSession` accumulates records in memory and
:class:`~agent_prov.bundle_generator.BundleGenerator` seals them at the end of
the run. If the process crashes before sealing, that in-memory state is lost.
This module adds an optional durability layer: every record the session appends
is also written -- immediately, flushed and ``fsync``'d -- as one line of an
append-only NDJSON log. After a crash, :func:`recover_session` replays the log
into a fresh ``PipelineSession``, which can then be sealed into a bundle exactly
as a live one would be.

The log is *operational* storage, not part of the protocol's hashed evidence: it
is plain (non-canonical) JSON and carries no integrity hash of its own. The
authoritative artefact remains the sealed Pipeline Bundle, whose ``bundle_hash``
is recomputed from the recovered records and re-validated at seal time. Nothing
here depends on a framework or on any optional extra -- it is standard-library
only (``json``, ``os``, ``pathlib``), so it lives in the protocol core.

The log is line-oriented NDJSON. The first line is a header describing the
session; each subsequent line wraps one record::

    {"event": "session", "log_version": "1", "pipeline_id": "...", "session_id": "...", "protocol_version": "0.2.0"}
    {"event": "record", "record": { ... }}
    {"event": "record", "record": { ... }}

Run recovery from the command line::

    python -m agent_prov.persistence path/to/log.ndjson out/bundle.json
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

from agent_prov.session import PipelineSession

logger = logging.getLogger(__name__)

#: Format version of the NDJSON event log, written into the session header. A
#: breaking change to the line shapes below would bump this so a reader can
#: refuse a log it does not understand.
LOG_VERSION = "1"


class EventLogError(RuntimeError):
    """Raised when an event log cannot be recovered (empty, or corrupt before its end)."""


class EventLog:
    """Append-only NDJSON sink a :class:`PipelineSession` streams records to.

    Opens *path* for **exclusive creation**: an existing file is never
    overwritten, so a log left behind by a crashed run is preserved as forensic
    evidence rather than clobbered by the next run (delete it explicitly to
    reuse the path). Each append is ``flush``ed and ``fsync``'d before returning,
    so a record :meth:`PipelineSession.add_record` has accepted is on disk even
    if the process dies immediately afterwards.

    Opting a session into an event log is opting into its durability contract:
    if a write cannot reach disk it raises rather than silently dropping the
    record, because a log with a hole is not a recoverable log. This is a
    deliberate divergence from the observation layer's "never crash the observed
    pipeline" stance -- the operator asked for durability, so a durability
    failure is surfaced, not masked.

    Use it as a context manager, or call :meth:`close` when the run ends::

        with EventLog(path) as log:
            session = PipelineSession(event_log=log)
            ...  # run the pipeline; records stream to disk as they are added
    """

    def __init__(self, path: str | pathlib.Path) -> None:
        self._path = pathlib.Path(path)
        # "x" = exclusive create: fail loudly if a prior run's log is here.
        self._file = open(self._path, "x", encoding="utf-8")
        self._closed = False

    def write_header(
        self,
        *,
        pipeline_id: str,
        session_id: str,
        protocol_version: str,
    ) -> None:
        """Write the session header line. Called once, when a session is attached."""
        self._write(
            {
                "event": "session",
                "log_version": LOG_VERSION,
                "pipeline_id": pipeline_id,
                "session_id": session_id,
                "protocol_version": protocol_version,
            }
        )

    def append_record(self, record: dict[str, Any]) -> None:
        """Append one record as an NDJSON line, then flush and fsync it to disk."""
        self._write({"event": "record", "record": record})

    def _write(self, obj: dict[str, Any]) -> None:
        if self._closed:
            raise ValueError("cannot write to a closed EventLog")
        self._file.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        """Close the underlying file. Idempotent."""
        if not self._closed:
            self._file.close()
            self._closed = True

    def __enter__(self) -> EventLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def path(self) -> pathlib.Path:
        """Filesystem path the log is being written to."""
        return self._path


def recover_session(path: str | pathlib.Path) -> PipelineSession:
    """Replay an NDJSON event log into a fresh in-memory :class:`PipelineSession`.

    Reconstructs the session identity from the header and re-appends every
    logged record in order, restoring ``records`` and ``last_record_id``. The
    returned session has no event log attached -- replay does not re-write the
    log -- so it can be sealed straight away::

        session = recover_session("run.ndjson")
        bundle = BundleGenerator(session).to_file("recovered_bundle.json")

    A final line left half-written by a crash is tolerated: if the last line does
    not parse as JSON it is treated as a truncated tail, dropped with a warning,
    and recovery proceeds with the records that were fully flushed. A malformed
    line *before* the end is unrecoverable corruption and raises
    :class:`EventLogError`.

    Raises:
        EventLogError: if the log is empty, its first line is not a session
            header, or a non-final line is malformed.
    """
    p = pathlib.Path(path)
    # NDJSON is newline-delimited: split on "\n" only (not str.splitlines(),
    # which also breaks on U+2028/U+2029/U+0085 and other Unicode separators a
    # free-form field such as tool_name or reviewer_role may legitimately
    # contain). read_text applies universal-newline translation, so "\r\n" line
    # terminators have already become "\n" here.
    lines = [ln for ln in p.read_text(encoding="utf-8").split("\n") if ln.strip()]
    if not lines:
        raise EventLogError(f"event log {str(p)!r} is empty")

    session = _session_from_header(p, lines[0])

    last_index = len(lines) - 1
    for i in range(1, len(lines)):
        line = lines[i]
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            if i == last_index:
                logger.warning(
                    "event log %s: dropping truncated final line (crash mid-write)",
                    p,
                )
                break
            raise EventLogError(f"event log {str(p)!r}: line {i + 1} is not valid JSON")
        record = _record_from_line(p, i, obj)
        session.add_record(record)

    return session


def _session_from_header(p: pathlib.Path, line: str) -> PipelineSession:
    """Parse the header line and build the empty session it describes.

    Every way the header can be malformed -- unparseable, not a session event,
    an unsupported log version, missing an identifier, or carrying an identifier
    that fails the session's own UUID/semver validation -- is reported as
    :class:`EventLogError`, so a caller (and the recovery CLI) only ever has to
    catch that one type.
    """
    try:
        header = json.loads(line)
    except json.JSONDecodeError as exc:
        raise EventLogError(f"event log {str(p)!r} has a malformed header line") from exc
    if not isinstance(header, dict) or header.get("event") != "session":
        raise EventLogError(f"event log {str(p)!r} does not start with a session header")
    if header.get("log_version") != LOG_VERSION:
        raise EventLogError(
            f"event log {str(p)!r} has unsupported log_version "
            f"{header.get('log_version')!r}; this reader supports {LOG_VERSION!r}"
        )
    missing = [k for k in ("pipeline_id", "session_id", "protocol_version") if k not in header]
    if missing:
        raise EventLogError(
            f"event log {str(p)!r} session header is missing keys: {missing}"
        )
    try:
        session = PipelineSession(
            pipeline_id=header["pipeline_id"],
            protocol_version=header["protocol_version"],
        )
    except ValueError as exc:
        raise EventLogError(
            f"event log {str(p)!r} session header has an invalid identifier: {exc}"
        ) from exc
    # Restore the original session_id (the constructor minted a fresh one).
    session.session_id = header["session_id"]
    return session


def _record_from_line(p: pathlib.Path, i: int, obj: Any) -> dict[str, Any]:
    """Validate a parsed record event and return its inner record dict.

    Catches the structurally-broken-but-parseable cases -- wrong event, the
    ``record`` payload absent, or a record dict with no ``record_id`` (which
    would otherwise raise ``KeyError`` from ``add_record`` *after* partially
    mutating the session) -- and reports them as :class:`EventLogError`.
    """
    if not isinstance(obj, dict) or obj.get("event") != "record" or "record" not in obj:
        raise EventLogError(f"event log {str(p)!r}: line {i + 1} is not a record event")
    record = obj["record"]
    if not isinstance(record, dict) or "record_id" not in record:
        raise EventLogError(
            f"event log {str(p)!r}: line {i + 1} record is missing record_id"
        )
    return record


__all__ = ["EventLog", "EventLogError", "recover_session", "LOG_VERSION"]
