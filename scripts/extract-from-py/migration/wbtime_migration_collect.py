"""Pytest plugin that dumps the full collected test inventory as JSON.

This module is *not* an exporter; the exporter loads it as a pytest plugin
(``-p wbtime_migration_collect``) so that the migration map is derived from
pytest's own collection instead of from text scraping.

Why a plugin instead of parsing ``pytest --collect-only -q`` stdout
--------------------------------------------------------------------
The legacy ``pyproject.toml`` sets ``addopts = "-q -m 'not provider_live' ..."``.
Adding another ``-q`` on the command line yields ``-qq``, which makes pytest
print ``<file>: <count>`` instead of one nodeid per line.  Parsing that output
would either lose every nodeid or force fragile arithmetic.  A
``pytest_collection_modifyitems`` hook receives the real ``Item`` objects, so we
get exact nodeids **and** the markers attached to each one, independent of the
verbosity flags.

Output contract
---------------
The plugin writes UTF-8 JSON to the path in ``$WBTIME_MIGRATION_OUT``:

.. code-block:: json

    {
      "schema": 1,
      "pytest_version": "8.x.y",
      "rootdir": "D:/WBT/WBTimeAI_old",
      "collected": 1701,
      "items": [
        {"nodeid": "tests/unit/test_x.py::test_y", "path": "tests/unit/test_x.py",
         "markers": ["smoke"], "module": "tests.unit.test_x"}
      ]
    }

``markers`` is sorted and de-duplicated.  The ``provider_live`` filter that
``addopts`` performs is **not** applied here on purpose (see
:mod:`export_migration`), so the raw inventory is preserved and the exporter can
report both the raw and the ``addopts``-selected counts.

Only the standard library plus pytest itself is imported.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

__all__ = ["OUTPUT_ENV_VAR", "pytest_collection_modifyitems", "pytest_sessionfinish"]

#: Environment variable holding the JSON output path.
OUTPUT_ENV_VAR = "WBTIME_MIGRATION_OUT"

#: Collected payload, filled during the collection phase.
_PAYLOAD: dict[str, Any] = {}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session: Any, config: Any, items: list[Any]) -> None:
    """Record every collected item before marker de-selection rewrites the list.

    ``tryfirst`` matters: ``_pytest.mark`` implements the same hook to drop items
    excluded by ``-m``.  Running first guarantees the inventory is complete, so
    the exporter can compute the ``not provider_live`` selection itself.

    Args:
        session: Pytest session (unused beyond ``config``).
        config: Pytest config, used for ``rootdir``/``pytest_version``.
        items: Mutable list of collected items.
    """
    records: list[dict[str, Any]] = []
    for item in items:
        path = str(getattr(item, "fspath", ""))
        marker_names = sorted({marker.name for marker in item.iter_markers()})
        records.append(
            {
                "nodeid": item.nodeid,
                "path": path.replace("\\", "/"),
                "markers": marker_names,
                "module": getattr(getattr(item, "module", None), "__name__", ""),
            }
        )

    rootdir = str(getattr(config, "rootpath", "") or getattr(config, "rootdir", ""))
    _PAYLOAD.clear()
    _PAYLOAD.update(
        {
            "schema": 1,
            "pytest_version": str(pytest.__version__),
            "rootdir": rootdir.replace("\\", "/"),
            "collected": len(records),
            "items": records,
        }
    )
    _write()


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """Write the payload again so a collection error still leaves evidence."""
    _write()


def _write() -> None:
    """Persist ``_PAYLOAD`` to ``$WBTIME_MIGRATION_OUT`` when configured."""
    target = os.environ.get(OUTPUT_ENV_VAR, "").strip()
    if not target or not _PAYLOAD:
        return
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(_PAYLOAD, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
