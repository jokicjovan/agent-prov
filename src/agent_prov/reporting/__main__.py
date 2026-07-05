"""Command-line entry point: `python -m agent_prov.reporting <bundle.json> <out.pdf>`."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from agent_prov.reporting.compliance_report import ComplianceReport


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent_prov.reporting",
        description=(
            "Render an EU AI Act compliance PDF from a sealed Pipeline Bundle."
        ),
    )
    parser.add_argument("bundle", type=pathlib.Path, help="path to bundle JSON")
    parser.add_argument("output", type=pathlib.Path, help="path to write PDF")
    args = parser.parse_args(argv)

    try:
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"FAILED: cannot read {args.bundle}: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"FAILED: {args.bundle} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        report = ComplianceReport(bundle)
    except (TypeError, ValueError) as exc:
        print(f"FAILED: {args.bundle} is not a usable bundle: {exc}", file=sys.stderr)
        return 1
    out_path = report.to_pdf(args.output)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
