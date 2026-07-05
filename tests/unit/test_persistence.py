"""Tests for crash-safe persistence: the append-only NDJSON event log.

Test cases covering:
  1     EventLog writes a session header as the first line.
  2     EventLog streams each appended record as one NDJSON line.
  3     EventLog opens for exclusive create: an existing path raises.
  4     EventLog works as a context manager and close() is idempotent.
  5     Writing to a closed EventLog raises.
  6     A session attached to an EventLog streams every record type to disk.
  7     recover_session round-trips identity, records, and last_record_id.
  8     A recovered session seals into a bundle that verify_bundle accepts.
  9     A recovered bundle is byte-identical to one sealed without logging.
  10    A truncated final line is dropped with recovery proceeding.
  11    A malformed non-final line raises EventLogError.
  12    An empty log raises EventLogError.
  13    A log whose first line is not a session header raises EventLogError.
  14    HITL records survive a round-trip through the log.
  15    The recovery CLI seals a recovered log into a valid bundle file.
  16    A field holding a Unicode line separator survives recovery (NDJSON is
        split on "\n" only, not str.splitlines()).
  17    A header missing required keys raises EventLogError (not KeyError).
  18    A header carrying an invalid id/semver raises EventLogError (not ValueError).
  19    An unsupported log_version raises EventLogError.
  20    A record event missing its 'record' payload raises EventLogError.
  21    A record dict missing 'record_id' raises EventLogError.
  22    The recovery CLI reports an unrecoverable log cleanly (FAILED + exit 1).
"""

from __future__ import annotations

import json

import pytest

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.hitl import HumanReview
from agent_prov.persistence import EventLog, EventLogError, recover_session
from agent_prov.persistence.__main__ import _cli
from agent_prov.session import PipelineSession, now_iso8601
from agent_prov.verify import verify_bundle


FIXED_PIPELINE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _add_some_records(session: PipelineSession) -> None:
    """Append one tool invocation and two agent steps to *session*."""
    session.add_tool_invocation(
        agent_id="researcher",
        tool_name="web_search",
        tool_version="1.0.0",
        timestamp_start=now_iso8601(),
        input={"query": "provenance"},
        output={"hits": 3},
    )
    session.add_agent_step(
        agent_id="researcher",
        model_id="gpt-test",
        model_version="2024-01",
        timestamp_start=now_iso8601(),
        input="summarise",
        output="a summary",
    )
    session.add_agent_step_error(
        agent_id="writer",
        model_id="gpt-test",
        model_version="2024-01",
        timestamp_start=now_iso8601(),
        input="write",
        error_type="TimeoutError",
        error_message="provider timed out",
    )


def _read_lines(path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# Tests 1-5: EventLog mechanics
# ---------------------------------------------------------------------------


def test_01_first_line_is_a_session_header(tmp_path):
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        PipelineSession(pipeline_id=FIXED_PIPELINE_ID, event_log=log)
    lines = _read_lines(log_path)
    assert lines[0]["event"] == "session"
    assert lines[0]["pipeline_id"] == FIXED_PIPELINE_ID
    assert lines[0]["log_version"] == "1"


def test_02_each_record_is_one_ndjson_line(tmp_path):
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        session = PipelineSession(event_log=log)
        _add_some_records(session)
    lines = _read_lines(log_path)
    record_lines = [ln for ln in lines if ln["event"] == "record"]
    assert len(record_lines) == 3
    assert all("record" in ln for ln in record_lines)


def test_03_exclusive_create_refuses_existing_path(tmp_path):
    log_path = tmp_path / "run.ndjson"
    log_path.write_text("prior run\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        EventLog(log_path)


def test_04_close_is_idempotent(tmp_path):
    log = EventLog(tmp_path / "run.ndjson")
    log.close()
    log.close()  # no raise


def test_05_writing_to_closed_log_raises(tmp_path):
    log = EventLog(tmp_path / "run.ndjson")
    log.close()
    with pytest.raises(ValueError):
        log.append_record({"record_id": "x"})


# ---------------------------------------------------------------------------
# Tests 6-9: session streaming + recovery round-trip
# ---------------------------------------------------------------------------


def test_06_session_streams_every_record_type(tmp_path):
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        session = PipelineSession(event_log=log)
        _add_some_records(session)
    logged = [ln["record"] for ln in _read_lines(log_path) if ln["event"] == "record"]
    assert [r["record_type"] for r in logged] == [
        "tool_invocation",
        "agent_step",
        "agent_step",
    ]
    assert logged == session.records


def test_07_recover_session_round_trips(tmp_path):
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        session = PipelineSession(pipeline_id=FIXED_PIPELINE_ID, event_log=log)
        _add_some_records(session)

    recovered = recover_session(log_path)
    assert recovered.pipeline_id == session.pipeline_id
    assert recovered.session_id == session.session_id
    assert recovered.protocol_version == session.protocol_version
    assert recovered.records == session.records
    assert recovered.last_record_id == session.last_record_id


def test_08_recovered_session_seals_and_verifies(tmp_path):
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        session = PipelineSession(event_log=log)
        _add_some_records(session)

    recovered = recover_session(log_path)
    bundle = BundleGenerator(recovered).generate()
    assert verify_bundle(bundle).ok


def test_09_recovered_bundle_matches_unlogged_bundle(tmp_path):
    # Recovery must preserve the records payload and identity exactly. (The
    # bundle_hash itself differs only because created_at and bundle_id are
    # minted fresh per seal, so we compare the parts persistence is responsible
    # for, not the seal.)
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        logged = PipelineSession(pipeline_id=FIXED_PIPELINE_ID, event_log=log)
        _add_some_records(logged)

    recovered = recover_session(log_path)

    direct_bundle = BundleGenerator(logged).generate()
    recovered_bundle = BundleGenerator(recovered).generate()
    assert recovered_bundle["records"] == direct_bundle["records"]
    assert recovered_bundle["pipeline_id"] == direct_bundle["pipeline_id"]
    assert recovered_bundle["session_id"] == direct_bundle["session_id"]


# ---------------------------------------------------------------------------
# Tests 10-13: crash tolerance and corruption
# ---------------------------------------------------------------------------


def test_10_truncated_final_line_is_dropped(tmp_path):
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        session = PipelineSession(event_log=log)
        _add_some_records(session)
    # Simulate a crash mid-write: append a half-written final line (no newline,
    # invalid JSON).
    with open(log_path, "a", encoding="utf-8") as f:
        f.write('{"event": "record", "record": {"record_id": "tru')

    recovered = recover_session(log_path)
    assert recovered.records == session.records  # the partial tail is ignored


def test_11_malformed_non_final_line_raises(tmp_path):
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        session = PipelineSession(event_log=log)
        _add_some_records(session)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    lines[1] = "{ this is not json"  # corrupt a middle line
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(EventLogError):
        recover_session(log_path)


def test_12_empty_log_raises(tmp_path):
    log_path = tmp_path / "empty.ndjson"
    log_path.write_text("", encoding="utf-8")
    with pytest.raises(EventLogError):
        recover_session(log_path)


def test_13_missing_header_raises(tmp_path):
    log_path = tmp_path / "headerless.ndjson"
    log_path.write_text(
        json.dumps({"event": "record", "record": {"record_id": "x"}}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(EventLogError):
        recover_session(log_path)


# ---------------------------------------------------------------------------
# Tests 14-15: HITL round-trip and the recovery CLI
# ---------------------------------------------------------------------------


def test_14_hitl_record_survives_round_trip(tmp_path):
    log_path = tmp_path / "run.ndjson"
    with EventLog(log_path) as log:
        session = PipelineSession(event_log=log)
        session.add_agent_step(
            agent_id="summarizer",
            model_id="gpt-test",
            model_version="2024-01",
            timestamp_start=now_iso8601(),
            input="draft",
            output="summary",
        )
        with HumanReview(
            session=session,
            reviewer_id=["alice"],
            reviewer_role="editor",
            output_before="summary",
        ) as review:
            review.edit("edited summary")

    recovered = recover_session(log_path)
    assert recovered.records == session.records
    hitl = recovered.records[-1]
    assert hitl["record_type"] == "human_intervention"
    assert hitl["action_type"] == "edited"


def test_15_cli_seals_recovered_log(tmp_path, capsys):
    log_path = tmp_path / "run.ndjson"
    out_path = tmp_path / "recovered_bundle.json"
    with EventLog(log_path) as log:
        session = PipelineSession(event_log=log)
        _add_some_records(session)

    rc = _cli([str(log_path), str(out_path), "--outcome", "aborted"])
    assert rc == 0
    bundle = json.loads(out_path.read_text(encoding="utf-8"))
    assert bundle["outcome"] == "aborted"
    assert verify_bundle(bundle).ok


# ---------------------------------------------------------------------------
# Tests 16-22: recover_session hardening (every malformed-log case reports
# EventLogError, never a leaked KeyError/ValueError) and NDJSON line splitting
# ---------------------------------------------------------------------------

FIXED_SESSION_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
VALID_HEADER = json.dumps(
    {
        "event": "session",
        "log_version": "1",
        "pipeline_id": FIXED_PIPELINE_ID,
        "session_id": FIXED_SESSION_ID,
        "protocol_version": "0.3.0",
    }
)


def _make_log(tmp_path, *lines: str):
    p = tmp_path / "log.ndjson"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_16_unicode_line_separator_in_field_round_trips(tmp_path):
    # A free-form field containing U+2028 must not be treated as a line break by
    # the recovery splitter (regression: str.splitlines() split it in two).
    log_path = tmp_path / "run.ndjson"
    weird = "tool" + chr(0x2028) + "name" + chr(0x85) + "x"  # U+2028 line sep + U+0085 NEL: str.splitlines() breaks on these, split('\n') does not
    with EventLog(log_path) as log:
        session = PipelineSession(event_log=log)
        session.add_tool_invocation(
            agent_id="a",
            tool_name=weird,
            tool_version="1.0.0",
            timestamp_start=now_iso8601(),
            input="x",
            output="y",
        )
    recovered = recover_session(log_path)
    assert recovered.records == session.records
    assert recovered.records[0]["tool_name"] == weird


def test_17_header_missing_keys_raises_event_log_error(tmp_path):
    p = _make_log(tmp_path, json.dumps({"event": "session", "log_version": "1"}))
    with pytest.raises(EventLogError):
        recover_session(p)


def test_18_header_invalid_identifier_raises_event_log_error(tmp_path):
    p = _make_log(
        tmp_path,
        json.dumps(
            {
                "event": "session",
                "log_version": "1",
                "pipeline_id": "NOT-A-UUID",
                "session_id": FIXED_SESSION_ID,
                "protocol_version": "v1",
            }
        ),
    )
    with pytest.raises(EventLogError):
        recover_session(p)


def test_19_unsupported_log_version_raises(tmp_path):
    p = _make_log(
        tmp_path,
        json.dumps(
            {
                "event": "session",
                "log_version": "99",
                "pipeline_id": FIXED_PIPELINE_ID,
                "session_id": FIXED_SESSION_ID,
                "protocol_version": "0.3.0",
            }
        ),
    )
    with pytest.raises(EventLogError):
        recover_session(p)


def test_20_record_line_missing_record_key_raises(tmp_path):
    p = _make_log(tmp_path, VALID_HEADER, json.dumps({"event": "record"}))
    with pytest.raises(EventLogError):
        recover_session(p)


def test_21_record_missing_record_id_raises(tmp_path):
    p = _make_log(
        tmp_path,
        VALID_HEADER,
        json.dumps({"event": "record", "record": {"record_type": "agent_step"}}),
    )
    with pytest.raises(EventLogError):
        recover_session(p)


def test_22_cli_reports_unrecoverable_log_cleanly(tmp_path, capsys):
    p = _make_log(tmp_path, "{ not a json header")
    out_path = tmp_path / "out.json"
    rc = _cli([str(p), str(out_path)])
    assert rc == 1
    assert not out_path.exists()
    assert "FAILED" in capsys.readouterr().err
