"""Command-line entry point: recover a crashed event log into a sealed bundle.

    python -m agent_prov.persistence <log.ndjson> <out_bundle.json> [--outcome ...] [--disclosure]

Replays the append-only NDJSON event log left behind by a run, then seals the
recovered records into a Pipeline Bundle (the same validation a live seal runs).
By default ``outcome`` is derived from the records ('error' if any record
failed, else 'completed'); pass ``--outcome aborted`` to record that the run was
stopped early -- often the right call for a log recovered after a crash.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from agent_prov.bundle_generator import BundleGenerator
from agent_prov.persistence import EventLogError, recover_session
from agent_prov.validation import ProtocolValidationError


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent_prov.persistence",
        description=(
            "Recover a crashed pipeline's append-only NDJSON event log and seal "
            "the recovered records into a Pipeline Bundle."
        ),
    )
    parser.add_argument("log", type=pathlib.Path, help="path to the NDJSON event log")
    parser.add_argument("out", type=pathlib.Path, help="path to write the sealed bundle JSON")
    parser.add_argument(
        "--outcome",
        choices=["completed", "aborted", "error"],
        default=None,
        help="terminal outcome to stamp on the bundle (default: derived from records)",
    )
    parser.add_argument(
        "--disclosure",
        action="store_true",
        help="record that an AI-interaction disclosure was presented (Art. 50(1))",
    )
    args = parser.parse_args(argv)

    try:
        session = recover_session(args.log)
    except EventLogError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    if not session.records:
        print(
            f"FAILED: no records recovered from {args.log} (header only)",
            file=sys.stderr,
        )
        return 1

    try:
        bundle = BundleGenerator(
            session,
            disclosure_presented=args.disclosure,
            outcome=args.outcome,
        ).to_file(args.out)
    except (ProtocolValidationError, ValueError) as exc:
        print(f"FAILED: recovered records do not seal into a valid bundle: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK: recovered {len(session.records)} record(s) -> {args.out} "
        f"(outcome={bundle['outcome']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
