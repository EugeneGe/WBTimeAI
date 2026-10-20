"""Capture real per-test outcomes into ``migration/inputs/outcomes.json``.

This is the **slow** half of the migration map: it runs the legacy suite for
real (tens of minutes; PostgreSQL / Docker slices included) and records what
actually happened.  It is intentionally not part of ``run.py export``.

Usage
-----
``python scripts/extract-from-py/migration/run_suite.py [options] [-- pytest args...]``

Without extra pytest arguments the default caliber is used:
``-o addopts= -m "not provider_live" -q --tb=no tests`` (i.e. the same 1699
cases the CSV covers).

Exit codes
----------
``0`` ledger written, ``1`` run failed to produce a ledger, ``2`` bootstrap error.
Note that pytest's own non-zero exit (red tests) still yields a ledger — the
outcomes *are* the deliverable, so a red run is not an error here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``_bootstrap`` importable when run as a plain script.
_TOOLKIT_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLKIT_DIR))

import _bootstrap  # noqa: E402 - path bootstrap must happen first
from migration import inventory  # noqa: E402

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_BOOTSTRAP = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="run_suite",
        description="Run the legacy suite and record per-test outcomes (outcomes.json).",
    )
    parser.add_argument(
        "--source",
        metavar="PATH",
        default=None,
        help="legacy repository root (default: $WBTIME_SOURCE or D:/WBT/WBTimeAI_old)",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="ledger path (default: migration/inputs/outcomes.json)",
    )
    parser.add_argument(
        "--timeout",
        metavar="SECONDS",
        type=int,
        default=None,
        help="hard cap for the run (default: none)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the pytest command that would run, then exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the suite and print the resulting distribution.

    Args:
        argv: Arguments without the program name; the first ``--`` separates our
            options from pytest's.

    Returns:
        Process exit code.
    """
    raw = list(argv) if argv is not None else sys.argv[1:]
    passthrough: list[str] = []
    if "--" in raw:
        split_at = raw.index("--")
        raw, passthrough = raw[:split_at], raw[split_at + 1 :]

    arguments = build_parser().parse_args(raw)
    try:
        context = _bootstrap.make_context(source=arguments.source)
    except _bootstrap.BootstrapError as error:
        print(f"[suite] {error}", file=sys.stderr)
        return EXIT_BOOTSTRAP

    destination = (
        Path(arguments.out) if arguments.out else inventory.inputs_dir() / "outcomes.json"
    )
    print(f"[suite] source: {context.source}")
    print(f"[suite] interpreter: {context.python_executable}")
    print(f"[suite] destination: {destination.as_posix()}")
    print(f"[suite] pytest extras: {' '.join(passthrough) or '(default caliber)'}")
    if arguments.dry_run:
        print("[suite] dry-run: nothing executed")
        return EXIT_OK

    try:
        status = inventory.run_outcomes(
            source=context.source,
            python_executable=context.python_executable,
            pythonpath=context.pythonpath,
            destination=destination,
            arguments=passthrough,
            timeout_seconds=arguments.timeout,
        )
    except inventory.InventoryError as error:
        print(f"[suite] FAILED: {error}", file=sys.stderr)
        return EXIT_FAILURE

    counts = status["counts"]
    print(f"[suite] pytest exit: {status['exit']}")
    print(f"[suite] recorded: {status['recorded']} case(s)")
    for outcome, count in sorted(counts.items()):
        print(f"  {outcome:8s} {count}")
    print(f"[suite] sha256: {inventory.sha256_of(destination)}")
    print(
        "[suite] now re-render the map: "
        "python scripts/extract-from-py/run.py export --only migration"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
