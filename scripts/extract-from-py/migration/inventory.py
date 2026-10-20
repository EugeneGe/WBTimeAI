"""Inventory ledgers for the migration map: collection + real-run outcomes.

Two JSON ledgers feed :mod:`migration.build`:

``collect.json``
    Produced by :mod:`migration.wbtime_migration_collect` (a pytest plugin) under
    ``pytest --collect-only``.  Authoritative list of node ids **and** their
    markers.
``outcomes.json``
    Produced by :mod:`migration.wbtime_migration_outcome` under a real run.
    Optional: when absent every row is reported as ``unknown``.

Both live under ``migration/inputs/`` so the map can be re-rendered without
re-running a 40-minute suite.  :func:`collect_inventory` regenerates the first
one on demand (≈12 s) using the legacy interpreter, exactly like the OpenAPI
exporter does.

Only the Python standard library is used here.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "COLLECT_SCHEMA",
    "OUTCOMES_SCHEMA",
    "PROVIDER_LIVE_MARKER",
    "REGISTERED_MARKERS",
    "IMPLICIT_MARKERS",
    "OUTCOME_VOCABULARY",
    "TestRecord",
    "InventoryError",
    "inputs_dir",
    "plugin_dir",
    "sha256_of",
    "load_collect_ledger",
    "load_outcomes_ledger",
    "select_default_run",
    "collect_inventory",
    "relative_path_of",
    "protocol_path",
    "run_outcomes",
]

#: Expected ``schema`` value of ``collect.json``.
COLLECT_SCHEMA = 1

#: Expected ``schema`` value of ``outcomes.json``.
OUTCOMES_SCHEMA = 1

#: Marker that ``pyproject.toml`` addopts excludes by default.
PROVIDER_LIVE_MARKER = "provider_live"

#: Markers declared in the legacy ``[tool.pytest.ini_options].markers`` table.
REGISTERED_MARKERS: tuple[str, ...] = (
    "contracts",
    "provider_live",
    "docker",
    "security",
    "smoke",
    "regression",
    "full",
)

#: Markers synthesised by pytest itself; kept out of the ``markers`` column.
IMPLICIT_MARKERS: frozenset[str] = frozenset(
    {"parametrize", "skipif", "xfail", "usefixtures", "filterwarnings", "timeout"}
)

#: Accepted ``outcome`` values in the CSV (``unknown`` means "not re-run").
OUTCOME_VOCABULARY: tuple[str, ...] = (
    "passed",
    "failed",
    "skipped",
    "xfailed",
    "xpassed",
    "error",
    "unknown",
)


class InventoryError(RuntimeError):
    """Raised when a ledger is missing, malformed, or inconsistent."""


@dataclasses.dataclass(frozen=True)
class TestRecord:
    """One collected test case.

    Attributes:
        nodeid: Pytest node id, e.g. ``tests/unit/test_core_id.py::test_x``.
        path: POSIX path relative to the legacy root.
        markers: All markers pytest attached, sorted, de-duplicated.
        module: Dotted module name (evidence only).
    """

    nodeid: str
    path: str
    markers: tuple[str, ...]
    module: str

    @property
    def project_markers(self) -> tuple[str, ...]:
        """Return the subset of markers declared by the project (not implicit)."""
        return tuple(marker for marker in self.markers if marker in REGISTERED_MARKERS)

    @property
    def has_provider_live(self) -> bool:
        """Whether the default ``addopts`` filter would drop this test."""
        return PROVIDER_LIVE_MARKER in self.markers


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def plugin_dir() -> Path:
    """Directory holding the two pytest plugins (``migration/``)."""
    return Path(__file__).resolve().parent


def inputs_dir() -> Path:
    """Directory holding the frozen input ledgers (``migration/inputs/``)."""
    return plugin_dir() / "inputs"


def sha256_of(path: str | Path) -> str:
    """Return the hex SHA-256 of a file, or ``""`` when it does not exist."""
    target = Path(path)
    if not target.is_file():
        return ""
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(131072), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Path handling
# ---------------------------------------------------------------------------


def protocol_path(raw: str) -> str:
    """Normalise any recorded path to ``POSIX`` form.

    Args:
        raw: Path as recorded by pytest (``D:\\\\WBT\\\\...`` on Windows).

    Returns:
        Forward-slash path without changing its root.
    """
    return str(raw).replace("\\", "/")


def relative_path_of(record: TestRecord, source_root: str) -> str:
    """Return the POSIX path of ``record`` relative to ``source_root``.

    ``nodeid`` is already relative for tests inside ``testpaths``, so it is the
    primary source of truth; the absolute ``fspath`` is only a fallback.

    Args:
        record: Collected record.
        source_root: Normalised legacy root (``D:/WBT/WBTimeAI_old``).
    """
    if "::" in record.nodeid:
        candidate = record.nodeid.split("::", 1)[0]
        if candidate:
            return protocol_path(candidate)
    root = protocol_path(source_root).rstrip("/") + "/"
    path = protocol_path(record.path)
    if path.startswith(root):
        return path[len(root) :]
    return path


# ---------------------------------------------------------------------------
# Ledger loading
# ---------------------------------------------------------------------------


def _read_json(path: Path, what: str) -> dict[str, Any]:
    """Read a JSON object from ``path`` with a helpful error message."""
    if not path.is_file():
        raise InventoryError(f"{what} not found: {path.as_posix()}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InventoryError(f"{what} is not valid JSON: {path.as_posix()}: {error}") from error
    if not isinstance(payload, dict):
        raise InventoryError(f"{what} must be a JSON object: {path.as_posix()}")
    return payload


def load_collect_ledger(path: str | Path) -> tuple[dict[str, Any], list[TestRecord]]:
    """Load ``collect.json``.

    Args:
        path: Ledger path.

    Returns:
        ``(meta, records)`` where ``meta`` keeps ``pytest_version`` / ``rootdir``
        / ``collected`` for the summary.

    Raises:
        InventoryError: When the ledger is missing, malformed, or has the wrong
            schema version.
    """
    payload = _read_json(Path(path), "collection ledger")
    schema = payload.get("schema")
    if schema != COLLECT_SCHEMA:
        raise InventoryError(
            f"collection ledger schema {schema!r} != expected {COLLECT_SCHEMA}: {path}"
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InventoryError(f"collection ledger has no items: {path}")

    records: list[TestRecord] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise InventoryError(f"collection ledger item is not an object: {item!r}")
        nodeid = str(item.get("nodeid", ""))
        if not nodeid:
            raise InventoryError(f"collection ledger item has no nodeid: {item!r}")
        markers = item.get("markers") or []
        records.append(
            TestRecord(
                nodeid=nodeid,
                path=protocol_path(str(item.get("path", ""))),
                markers=tuple(sorted({str(marker) for marker in markers})),
                module=str(item.get("module", "")),
            )
        )
    meta = {
        "pytest_version": str(payload.get("pytest_version", "")),
        "rootdir": protocol_path(str(payload.get("rootdir", ""))),
        "collected": len(records),
        "declared_collected": int(payload.get("collected", len(records)) or len(records)),
        "sha256": sha256_of(path),
    }
    return meta, records


def load_outcomes_ledger(path: str | Path) -> dict[str, Any] | None:
    """Load ``outcomes.json`` when present.

    Args:
        path: Ledger path.

    Returns:
        ``None`` when the file does not exist (all outcomes become ``unknown``),
        otherwise a dict with ``outcomes``, ``counts`` and provenance metadata.

    Raises:
        InventoryError: When the file exists but is malformed.
    """
    target = Path(path)
    if not target.is_file():
        return None
    payload = _read_json(target, "outcome ledger")
    schema = payload.get("schema")
    if schema != OUTCOMES_SCHEMA:
        raise InventoryError(
            f"outcome ledger schema {schema!r} != expected {OUTCOMES_SCHEMA}: {path}"
        )
    outcomes = payload.get("outcomes")
    if not isinstance(outcomes, dict):
        raise InventoryError(f"outcome ledger has no 'outcomes' object: {path}")
    return {
        "outcomes": {str(key): str(value) for key, value in outcomes.items()},
        "counts": dict(payload.get("counts") or {}),
        "pytest_version": str(payload.get("pytest_version", "")),
        "argv": list(payload.get("argv") or []),
        "exitstatus": payload.get("exitstatus"),
        "duration_seconds": payload.get("duration_seconds"),
        "sha256": sha256_of(target),
    }


def select_default_run(records: Sequence[TestRecord]) -> list[TestRecord]:
    """Apply the default ``addopts`` filter (``-m 'not provider_live'``).

    Args:
        records: Raw collected records.

    Returns:
        The records a plain ``pytest`` run would select — the row basis of the
        migration map (1699 at the 2026-10-20 baseline).
    """
    return [record for record in records if not record.has_provider_live]


# ---------------------------------------------------------------------------
# Regenerating the collection ledger
# ---------------------------------------------------------------------------


def collect_inventory(
    source: str,
    python_executable: str,
    pythonpath: str,
    destination: str | Path,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Run ``pytest --collect-only`` under the legacy interpreter.

    The plugin (:mod:`migration.wbtime_migration_collect`) writes the ledger, so
    no stdout scraping is involved.  ``-o addopts=`` clears the legacy
    ``addopts`` (which carries ``-q ... --cov``); therefore the default marker
    filter is **not** applied here and the raw inventory is preserved
    (``provider_live`` included), which :func:`select_default_run` narrows down.

    Args:
        source: Normalised legacy root.
        python_executable: Legacy interpreter path.
        pythonpath: ``os.pathsep``-joined legacy import roots.
        destination: Where to write ``collect.json``.
        timeout_seconds: Hard cap so an export can never hang forever.

    Returns:
        A short status dict for the exporter log.

    Raises:
        InventoryError: When pytest fails or produces no ledger.
    """
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    environment = dict(os.environ)
    environment["PYTHONPATH"] = pythonpath + os.pathsep + str(plugin_dir())
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    environment["WBTIME_MIGRATION_OUT"] = str(target)
    environment.pop("PYTEST_ADDOPTS", None)

    command = [
        python_executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-o",
        "addopts=",
        "-p",
        "wbtime_migration_collect",
        "tests",
    ]
    completed = subprocess.run(  # noqa: S603 - deliberate, argv is internal
        command,
        cwd=source,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    if not target.is_file():
        tail = (completed.stdout or "")[-2000:] + (completed.stderr or "")[-2000:]
        raise InventoryError(
            f"collection produced no ledger (exit {completed.returncode}); tail:\n{tail}"
        )
    meta, records = load_collect_ledger(target)
    return {
        "exit": completed.returncode,
        "ledger": target.as_posix(),
        "collected": len(records),
        "pytest_version": meta["pytest_version"],
    }


def run_outcomes(
    source: str,
    python_executable: str,
    pythonpath: str,
    destination: str | Path,
    arguments: Iterable[str] = (),
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Run the legacy suite for real and capture per-test outcomes.

    Deliberately **not** wired into ``run.py export``: a full run takes tens of
    minutes and needs PostgreSQL / Docker for the integration slices.  Invoke it
    via ``python scripts/extract-from-py/migration/run_suite.py`` when the map
    should be refreshed against a fresh run.

    Args:
        source: Normalised legacy root.
        python_executable: Legacy interpreter path.
        pythonpath: ``os.pathsep``-joined legacy import roots.
        destination: Where to write ``outcomes.json``.
        arguments: Extra pytest arguments (default: default-run selection).
        timeout_seconds: Optional hard cap.

    Returns:
        A short status dict.

    Raises:
        InventoryError: When the ledger is not produced.
    """
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    environment = dict(os.environ)
    environment["PYTHONPATH"] = pythonpath + os.pathsep + str(plugin_dir())
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    environment["WBTIME_MIGRATION_OUTCOMES"] = str(target)
    environment.pop("PYTEST_ADDOPTS", None)

    extra = list(arguments) or ["-m", f"not {PROVIDER_LIVE_MARKER}", "-q", "--tb=no", "tests"]
    command = [
        python_executable,
        "-m",
        "pytest",
        "-p",
        "wbtime_migration_outcome",
        "-o",
        "addopts=",
        "-p",
        "no:cacheprovider",
        *extra,
    ]
    completed = subprocess.run(  # noqa: S603 - deliberate, argv is internal
        command,
        cwd=source,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    if not target.is_file():
        tail = (completed.stdout or "")[-2000:] + (completed.stderr or "")[-2000:]
        raise InventoryError(
            f"outcome run produced no ledger (exit {completed.returncode}); tail:\n{tail}"
        )
    payload = load_outcomes_ledger(target) or {}
    counts = payload.get("counts", {})
    return {
        "exit": completed.returncode,
        "ledger": target.as_posix(),
        "recorded": sum(int(value) for value in counts.values()),
        "counts": counts,
    }
