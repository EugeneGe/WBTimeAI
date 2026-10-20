"""Pytest plugin that records the per-test outcome of a real run as JSON.

Companion to :mod:`wbtime_migration_collect`.  The collector runs with
``--collect-only`` (no test bodies execute); *this* plugin runs against the real
suite and captures what actually happened, so ``test-migration-map.csv`` can
carry a truthful ``outcome`` column instead of a guess.

Output contract
---------------
``$WBTIME_MIGRATION_OUTCOMES`` receives UTF-8 JSON:

.. code-block:: json

    {
      "schema": 1,
      "pytest_version": "9.1.1",
      "argv": ["-m", "not provider_live", "tests"],
      "duration_seconds": 1234.5,
      "counts": {"passed": 1661, "failed": 3, "skipped": 33, "xfailed": 2, "error": 0},
      "outcomes": {
        "tests/unit/test_core_id.py::test_x": "passed",
        "tests/nfr/test_pg_baselines.py::test_y": "skipped"
      },
      "short_summary": "=== 1661 passed, 33 skipped ... in 1234.56s ==="
    }

Outcome vocabulary (exactly the column vocabulary of the CSV, plus ``error``):

``passed`` / ``failed`` / ``skipped`` / ``xfailed`` / ``xpassed`` / ``error``

A test that never ran (interrupted run) simply does not appear in ``outcomes``;
the exporter then keeps it as ``unknown``, which is the honest value.

Only the standard library plus pytest itself is imported.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import pytest

__all__ = ["OUTPUT_ENV_VAR", "pytest_runtest_logreport", "pytest_sessionfinish"]

#: Environment variable holding the JSON output path.
OUTPUT_ENV_VAR = "WBTIME_MIGRATION_OUTCOMES"

_START = time.time()

#: ``nodeid -> outcome``; the first non-``passed`` phase wins, otherwise ``passed``.
_OUTCOMES: dict[str, str] = {}


def _record(nodeid: str, outcome: str) -> None:
    """Store ``outcome`` for ``nodeid``, allowing a failure to override a pass.

    Args:
        nodeid: Pytest node id.
        outcome: One of the vocabulary words listed in the module docstring.
    """
    previous = _OUTCOMES.get(nodeid)
    if previous is None or previous == "passed":
        _OUTCOMES[nodeid] = outcome


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: Any) -> None:
    """Translate pytest reports into a single outcome per node id.

    Setup/teardown failures become ``error``; a failed ``call`` becomes
    ``failed``; ``skipped`` (including xfail via ``wasxfail``) keeps pytest's own
    wording so the CSV matches ``-rx`` output.

    Args:
        report: A ``TestReport`` produced by pytest.
    """
    if report.when == "call":
        if hasattr(report, "wasxfail"):
            _record(report.nodeid, "xpassed" if report.passed else "xfailed")
        elif report.failed:
            _record(report.nodeid, "failed")
        elif report.skipped:
            _record(report.nodeid, "skipped")
        else:
            _record(report.nodeid, "passed")
        return
    if report.failed:
        _record(report.nodeid, "error")
    elif report.skipped and report.nodeid not in _OUTCOMES:
        _record(report.nodeid, "skipped")


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """Write the outcome ledger plus a count summary.

    Args:
        session: Pytest session.
        exitstatus: Pytest exit code (kept for logging/debug parity).
    """
    target = os.environ.get(OUTPUT_ENV_VAR, "").strip()
    if not target:
        return
    counts: dict[str, int] = {}
    for outcome in _OUTCOMES.values():
        counts[outcome] = counts.get(outcome, 0) + 1
    payload = {
        "schema": 1,
        "pytest_version": str(pytest.__version__),
        "argv": list(getattr(session.config, "invocation_params", None).args or []),
        "exitstatus": int(exitstatus),
        "duration_seconds": round(time.time() - _START, 2),
        "counts": dict(sorted(counts.items())),
        "outcomes": dict(sorted(_OUTCOMES.items())),
        "short_summary": str(session.config.option.reportchars or ""),
    }
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
