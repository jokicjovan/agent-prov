"""Command-line entry point: `python -m agent_prov.verify <bundle.json>`."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

from agent_prov.verify import verify_bundle


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent_prov.verify",
        description=(
            "Independently verify a sealed Pipeline Bundle: recompute the "
            "bundle_hash, re-run schema and conditional validation, and check "
            "parent-chain and identifier integrity."
        ),
    )
    parser.add_argument("bundle", type=pathlib.Path, help="path to bundle JSON")
    args = parser.parse_args(argv)

    bundle = _load_json(args.bundle)
    if bundle is None:
        return 1
    result = verify_bundle(bundle)

    if result.ok:
        n = len(bundle.get("records", []))
        print(f"OK: bundle verified ({n} records)")
        return 0

    print(f"FAILED: {len(result.errors)} problem(s) found", file=sys.stderr)
    for err in result.errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


def _load_json(path: pathlib.Path) -> Any:
    """Read and parse JSON, reporting a missing file or parse error cleanly.

    Returns the parsed object, or ``None`` after printing a ``FAILED:`` line to
    stderr so the caller can exit non-zero without dumping a traceback.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"FAILED: cannot read {path}: {exc}", file=sys.stderr)
    except json.JSONDecodeError as exc:
        print(f"FAILED: {path} is not valid JSON: {exc}", file=sys.stderr)
    return None


if __name__ == "__main__":
    sys.exit(_cli())
