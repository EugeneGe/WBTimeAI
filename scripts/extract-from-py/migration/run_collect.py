"""Regenerate ``migration/inputs/collect.json`` (the collection ledger).

Run this when the legacy test tree changes (new test file, renamed case, new
marker).  It takes ≈12 s and does **not** execute any test body.

Usage
-----
``python scripts/extract-from-py/migration/run_collect.py [--source PATH] [--out PATH]``

Exit codes
----------
``0`` success, ``1`` collection failed, ``2`` bootstrap/usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``_bootstrap`` / ``hashes`` importable when run as a plain script.
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
        prog="run_collect",
        description="Regenerate the legacy pytest collection ledger (collect.json).",
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
        help="ledger path (default: migration/inputs/collect.json)",
    )
    parser.add_argument(
        "--timeout",
        metavar="SECONDS",
        type=int,
        default=900,
        help="hard cap for the collection subprocess (default: 900)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the collection and print a one-line status.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    arguments = build_parser().parse_args(argv)
    try:
        context = _bootstrap.make_context(source=arguments.source)
    except _bootstrap.BootstrapError as error:
        print(f"[collect] {error}", file=sys.stderr)
        return EXIT_BOOTSTRAP

    destination = Path(arguments.out) if arguments.out else inventory.inputs_dir() / "collect.json"
    print(f"[collect] source: {context.source}")
    print(f"[collect] interpreter: {context.python_executable}")
    print(f"[collect] destination: {destination.as_posix()}")
    try:
        status = inventory.collect_inventory(
            source=context.source,
            python_executable=context.python_executable,
            pythonpath=context.pythonpath,
            destination=destination,
            timeout_seconds=arguments.timeout,
        )
    except inventory.InventoryError as error:
        print(f"[collect] FAILED: {error}", file=sys.stderr)
        return EXIT_FAILURE

    print(
        f"[collect] OK: {status['collected']} item(s), pytest {status['pytest_version']}, "
        f"exit {status['exit']}"
    )
    print(f"[collect] sha256: {inventory.sha256_of(destination)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
