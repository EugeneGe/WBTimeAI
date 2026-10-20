#!/usr/bin/env python3
"""Semantic gate for the frozen WBTimeAI contract artifacts (defects D-1/D-2/D-3).

Why this file exists
--------------------
``python scripts/extract-from-py/run.py check`` proves *byte integrity*: every
artifact still matches the digest recorded in ``contracts/manifest.sha256`` and
in the dual ledger (``contracts/contract-manifest.json -> objects[]``). It says
nothing about whether the **numbers and judgements inside** those artifacts are
still true.

QA demonstrated the gap with two counter-examples on a scratch copy:

* (1) edit ``openapi.v1.frozen.json -> info.version`` without touching the
  ledger: ``check`` exits 1 (red) -- integrity gate works.
* (2) edit ``schema.v0018.pg.normalized.json`` so that
  ``counts.metadata_indexes`` 174 -> 170 and ``counts.index_objects_total``
  176 -> 172, then re-pin ``manifest.sha256`` *and* the object digest inside
  ``contract-manifest.json``, then re-pin ``contract-manifest.json`` itself:
  ``check`` exits 0 (green) -- the tamper is invisible to an integrity gate.

A third round of QA review found a *second-order* false green (N-1): the two
criteria that exist **specifically to stop D-1/D-2 from coming back** (``C22``,
``C23``) had no executor at all. They were computed once at ``export`` time and
then only ever *summarised* by ``check`` (dual-ledger digest comparison +
enum legality + coverage completeness) -- never recomputed. So they carried
``status="verified"`` while nothing verified them. Re-pinning the whole sha
chain resurrected both defects with ``check`` and this gate both green.

Consequently this gate never trusts a pre-computed statistic *or* a pre-computed
verdict. Every headline number is re-derived from the raw structures
(``paths`` keys, path x method expansion, ``tables[].columns``,
``tables[].indexes``, CSV data rows, ...) and every *judgement* criterion
(``C22`` / ``C23``) is re-decided from the evidence it is supposed to be about
(``codes.*.http_status_by_call_site_resolved`` rows, CSV ``bucket`` / ``note`` /
protected test ids), then compared against:

1. ``contracts/contract-manifest.json -> criteria[].measured`` -- the value the
   ledger publicly claims (this is what the DoD sign-off relies on);
2. the artifacts' own self-declared blocks (``counts``, ``meta``,
   ``artifacts`` digests, ``case_overrides``, ``bucket_distribution``) -- the
   place a tamperer likes to edit because nothing else reads it.

A check is red when either reference disagrees with the recomputed value.

Coverage
--------
``C1``-``C23`` (23 criteria) plus the structural check ``S1`` = **24 checks**:

======  =====================================  ===============================
id      metric                                 recomputed from
======  =====================================  ===============================
C1..C3  openapi.{paths,operations,schemas}      ``paths`` / method x path / schemas
C4..C8  ddl.{tables,columns,indexes,...}        ``tables[].columns`` / ``indexes``
C9      sqlite.dialect_only_objects             ``dialect_only[]`` grouped by kind
C10     sse.channels                            ``channels[]`` length
C11     sse.golden_frames                       distinct ``channels[].golden``
C12     sse.golden_coverage                     every channel's golden file exists
C13     errors.codes                            ``codes`` size
C14     envelope.shell_keys                     ``$defs.*.required`` of 3 shells
C15     migration_map.rows                      CSV data rows
C16     migration_map.passed                    CSV ``outcome == passed``
C17     reproducibility.toolkit                 toolkit modules present
C18     reproducibility.ledgers                 two ledgers present + agree
C19     conformance.skeletons                   ``conformance/*.yaml`` count
C20     migration.self_declared_digests         summary ``artifacts`` vs disk
C21     ddl_objects.total                       ``ddl_objects[]`` length
C22     errors.http_status_uniformity           per-code resolved call sites
C23     migration.disposition_auditability      CSV bucket/note/protected ids
S1      ddl_objects.self_consistency            kinds/sources/dialects decompose
======  =====================================  ===============================

Design rules
------------
* Read-only against ``contracts/``; never touches ``D:/WBT/WBTimeAI_old``.
* Standard library only (no third-party imports), so it can run in CI.
* Exit codes are disjoint from ``run.py check`` (which uses 1 for integrity):

  =====  ===================================================================
  ``0``  all checks matched
  ``2``  at least one semantic mismatch was recomputed
  ``3``  an artifact/criterion could not be read or parsed (cannot evaluate)
  ``4``  ``--self-test`` ran but its expectations were violated
  =====  ===================================================================

Usage
-----
::

    python scripts/verify_semantics.py
    python scripts/verify_semantics.py --contracts <dir> --verbose
    python scripts/verify_semantics.py --json
    python scripts/verify_semantics.py --self-test
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

PROG = "verify_semantics.py"

EXIT_OK = 0
EXIT_MISMATCH = 2
EXIT_LOAD_ERROR = 3
EXIT_SELF_TEST_FAILED = 4

# Artifact file names, relative to the contracts directory.
MANIFEST_JSON = "contract-manifest.json"
MANIFEST_SHA = "manifest.sha256"
OPENAPI = "openapi.v1.frozen.json"
PG_SCHEMA = "schema.v0018.pg.normalized.json"
SQLITE_SCHEMA = "schema.v0018.sqlite.normalized.json"
SSE_CHANNELS = "sse/channels.json"
ERRORS = "errors.json"
ENVELOPE = "envelope.schema.json"
MIGRATION_CSV = "test-migration-map.csv"
MIGRATION_SUMMARY = "test-migration-summary.json"
CONFORMANCE_DIR = "conformance"
SSE_DIR = "sse"

#: Keys of an OpenAPI path item that represent HTTP operations.
HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)

#: Envelope shells that must expose the four canonical top-level keys.
ENVELOPE_SHELL_DEFS = ("successEnvelope", "errorEnvelope", "messageEnvelope")

#: The four top-level keys frozen by 总纲 §11.1 (``C14``).
CANONICAL_ENVELOPE_KEYS = ("code", "message", "data", "request_id")

#: Toolkit modules that make ``contracts/`` reproducible (``C17``), in the order
#: the criterion publishes them.
REQUIRED_TOOLKIT = ("_bootstrap.py", "hashes.py", "run.py", "export_openapi.py")

#: The two ledgers of the dual-ledger baseline (``C18``), in published order.
REQUIRED_LEDGERS = (MANIFEST_SHA, MANIFEST_JSON)

#: CSV bucket that means "abandoned or merged" (``C23``).
BUCKET_DROPPED = "3"

#: Cases that D-2 forbids from ever being judged bucket ③. This is the one API
#: level fail-closed assertion in the repository
#: (``test_unmapped_mcp_tool_is_fail_closed_and_roundtrips``); every other
#: fail-closed proof is unit level and does not cover it.
PROTECTED_TEST_IDS = (
    "tests/integration/permission/test_mcp_permissions_redirect.py"
    "::test_unmapped_mcp_tool_is_fail_closed_and_roundtrips",
)

#: Substrings that mark a case as a fail-closed assertion. A row whose id or
#: capability carries one of these can never be judged bucket ③, even if it is
#: not in :data:`PROTECTED_TEST_IDS` (catches renames / new protected cases).
FAIL_CLOSED_MARKERS = ("fail_closed", "fail-closed", "fail closed", "failclosed")

#: A bucket ③ ``note`` must explain *why* the case was dropped.
DROPPED_RATIONALE_MARKERS = ("放弃", "dropped", "why dropped", "not ported")

#: Minimum length of a bucket ③ ``note`` for it to count as substantive.
MIN_DROPPED_NOTE_LENGTH = 50

#: Expected number of checks: 23 criteria plus the structural check ``S1``.
EXPECTED_CHECK_COUNT = 24


# ---------------------------------------------------------------------------
# Value formatting / small helpers
# ---------------------------------------------------------------------------


def _fmt_value(value: Any) -> str:
    """Render a value compactly for the one-line report.

    Args:
        value: Any JSON-compatible value (int, str, dict, list, bool, None).

    Returns:
        A short, whitespace-free representation suitable for column output.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    """Compute the sha256 hex digest of a file.

    Args:
        path: File to hash.

    Returns:
        Lowercase 64-character hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_contracts_dir() -> Path:
    """Resolve ``<repo>/contracts`` from this file's location.

    Returns:
        Absolute path to the contracts directory expected by the repository
        layout (``<repo>/scripts/verify_semantics.py``).
    """
    return Path(__file__).resolve().parent.parent / "contracts"


def default_toolkit_dir() -> Path:
    """Resolve ``<repo>/scripts/extract-from-py`` from this file's location.

    Returns:
        Absolute path to the extraction toolkit checked by ``C17``.
    """
    return Path(__file__).resolve().parent / "extract-from-py"


def _dig(document: Any, *keys: str) -> Any:
    """Read a nested mapping path, returning ``None`` when any hop is absent.

    Args:
        document: Parsed JSON document (usually a mapping).
        *keys: Successive mapping keys.

    Returns:
        The value at the path, or ``None`` when the path does not exist.
    """
    current: Any = document
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _normalise_text(text: str) -> str:
    """Collapse all whitespace runs so two notes can be compared by content.

    Args:
        text: Raw cell text.

    Returns:
        Whitespace-normalised, stripped string.
    """
    return " ".join(str(text).split())


class ArtifactError(RuntimeError):
    """Raised when a required artifact is missing, unreadable or unparsable."""


# ---------------------------------------------------------------------------
# Artifact loading (pure read of contracts/, no legacy tree)
# ---------------------------------------------------------------------------


class Artifacts:
    """Lazy, cached, read-only accessor for the frozen contract artifacts."""

    def __init__(self, contracts_dir: Path, toolkit_dir: Path | None = None) -> None:
        """Create an accessor bound to a contracts directory.

        Args:
            contracts_dir: Directory holding the frozen artifacts.
            toolkit_dir: Directory holding the extraction toolkit; defaults to
                ``<repo>/scripts/extract-from-py``. Only ``C17`` reads it, and
                ``--self-test`` points it at a scratch copy.
        """
        self._dir = Path(contracts_dir)
        self._toolkit_dir = Path(toolkit_dir) if toolkit_dir else default_toolkit_dir()
        self._cache: dict[str, Any] = {}

    @property
    def contracts_dir(self) -> Path:
        """The contracts directory this accessor reads from."""
        return self._dir

    @property
    def toolkit_dir(self) -> Path:
        """The extraction toolkit directory checked by ``C17``."""
        return self._toolkit_dir

    def path(self, relative: str) -> Path:
        """Resolve an artifact path and assert that it exists.

        Args:
            relative: POSIX-style path relative to the contracts directory.

        Returns:
            Absolute path to the artifact.

        Raises:
            ArtifactError: If the contracts directory or the artifact is absent.
        """
        if not self._dir.is_dir():
            raise ArtifactError(f"contracts directory not found: {self._dir.as_posix()}")
        candidate = self._dir / relative
        if not candidate.is_file():
            raise ArtifactError(f"missing artifact: {relative} (under {self._dir.as_posix()})")
        return candidate

    def json(self, relative: str) -> Any:
        """Load (and cache) a JSON artifact.

        Args:
            relative: POSIX-style path relative to the contracts directory.

        Returns:
            The parsed JSON document.

        Raises:
            ArtifactError: If the file is missing or is not valid JSON.
        """
        if relative not in self._cache:
            target = self.path(relative)
            try:
                with target.open("r", encoding="utf-8") as handle:
                    self._cache[relative] = json.load(handle)
            except json.JSONDecodeError as error:
                raise ArtifactError(f"invalid JSON in {relative}: {error}") from error
            except OSError as error:  # pragma: no cover - filesystem edge case
                raise ArtifactError(f"cannot read {relative}: {error}") from error
        return self._cache[relative]

    def object_json(self, relative: str) -> Mapping[str, Any]:
        """Load a JSON artifact and require an object at the root.

        Args:
            relative: POSIX-style path relative to the contracts directory.

        Returns:
            The parsed document as a mapping.

        Raises:
            ArtifactError: If the root is not a JSON object.
        """
        document = self.json(relative)
        if not isinstance(document, Mapping):
            raise ArtifactError(f"{relative}: expected a JSON object at the root")
        return document

    def manifest(self) -> Mapping[str, Any]:
        """Return the contract manifest document (``contract-manifest.json``)."""
        return self.object_json(MANIFEST_JSON)

    def manifest_digest(self) -> str:
        """sha256 of ``contract-manifest.json`` as currently on disk."""
        return sha256_file(self.path(MANIFEST_JSON))

    def criteria(self) -> dict[str, Mapping[str, Any]]:
        """Index ``criteria[]`` by criterion id (``C1`` ... ``C23``).

        Raises:
            ArtifactError: If the ``criteria`` array is absent or malformed.
        """
        raw = self.manifest().get("criteria")
        if not isinstance(raw, list) or not raw:
            raise ArtifactError(f"{MANIFEST_JSON}: 'criteria' is missing or empty")
        indexed: dict[str, Mapping[str, Any]] = {}
        for entry in raw:
            if not isinstance(entry, Mapping):
                raise ArtifactError(f"{MANIFEST_JSON}: criteria entry is not an object: {entry!r}")
            identifier = str(entry.get("id", "")).strip()
            if not identifier:
                raise ArtifactError(f"{MANIFEST_JSON}: criteria entry without an 'id'")
            indexed[identifier] = entry
        return indexed


# ---------------------------------------------------------------------------
# Recomputation primitives -- each one ignores the artifacts' own statistics
# ---------------------------------------------------------------------------


def count_openapi_paths(openapi: Mapping[str, Any]) -> int:
    """Count path items in the frozen OpenAPI document."""
    paths = openapi.get("paths")
    return len(paths) if isinstance(paths, Mapping) else 0


def count_openapi_operations(openapi: Mapping[str, Any]) -> int:
    """Count operations by expanding every path item over the HTTP method keys."""
    paths = openapi.get("paths")
    if not isinstance(paths, Mapping):
        return 0
    total = 0
    for item in paths.values():
        if isinstance(item, Mapping):
            total += sum(1 for key in item if str(key).lower() in HTTP_METHODS)
    return total


def count_openapi_schemas(openapi: Mapping[str, Any]) -> int:
    """Count ``components.schemas`` entries."""
    components = openapi.get("components")
    if not isinstance(components, Mapping):
        return 0
    schemas = components.get("schemas")
    return len(schemas) if isinstance(schemas, Mapping) else 0


def ddl_tables(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the ``tables`` array of a normalized DDL document (empty if absent)."""
    tables = document.get("tables")
    if not isinstance(tables, list):
        return []
    return [table for table in tables if isinstance(table, Mapping)]


def count_ddl_columns(tables: Sequence[Mapping[str, Any]]) -> int:
    """Sum ``len(table['columns'])`` over all tables."""
    total = 0
    for table in tables:
        columns = table.get("columns")
        if isinstance(columns, list):
            total += len(columns)
    return total


def count_metadata_indexes(tables: Sequence[Mapping[str, Any]]) -> int:
    """Sum ``len(table['indexes'])`` over all tables."""
    total = 0
    for table in tables:
        indexes = table.get("indexes")
        if isinstance(indexes, list):
            total += len(indexes)
    return total


def count_raw_indexes(document: Mapping[str, Any]) -> int:
    """Count top-level ``raw_indexes`` entries."""
    raw = document.get("raw_indexes")
    return len(raw) if isinstance(raw, list) else 0


def group_dialect_only(document: Mapping[str, Any]) -> dict[str, int]:
    """Group ``dialect_only[]`` by ``kind`` into a deterministic dict."""
    raw = document.get("dialect_only")
    counter: Counter[str] = Counter()
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, Mapping):
                counter[str(entry.get("kind"))] += 1
    return {kind: counter[kind] for kind in sorted(counter)}


def count_collection(document: Any, key: str) -> int:
    """Count a top-level mapping key or array in a contract document.

    Args:
        document: Parsed JSON document.
        key: Top-level key to count.

    Returns:
        Number of entries in the mapping/array, ``0`` when absent.
    """
    if not isinstance(document, Mapping):
        return 0
    value = document.get(key)
    if isinstance(value, Mapping):
        return len(value)
    if isinstance(value, list):
        return len(value)
    return 0


def count_sse_golden_frames(channels_document: Mapping[str, Any]) -> int:
    """Count distinct ``channels[].golden`` references.

    Enumeration of ``sse/golden/*.txt`` is deliberately avoided: that directory
    also holds ``_guard-float-normalization.txt``, a guard fixture that must not
    be counted among the 19 contract frames.

    Args:
        channels_document: Parsed ``sse/channels.json``.

    Returns:
        Number of distinct golden frame references.
    """
    channels = channels_document.get("channels")
    if not isinstance(channels, list):
        return 0
    references = {
        str(entry.get("golden"))
        for entry in channels
        if isinstance(entry, Mapping) and entry.get("golden")
    }
    return len(references)


def read_migration_rows(path: Path) -> list[dict[str, str]]:
    """Parse ``test-migration-map.csv`` into data rows.

    The file starts with a ``#``-prefixed provenance banner, one header row and
    one row per selected pytest case.

    Args:
        path: Path to the CSV artifact.

    Returns:
        One ``dict`` per data row (blank rows dropped), keyed by header name.

    Raises:
        ArtifactError: If the file cannot be read.
    """
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
    except OSError as error:  # pragma: no cover - filesystem edge case
        raise ArtifactError(f"cannot read {path.name}: {error}") from error

    reader = csv.DictReader(lines)
    rows: list[dict[str, str]] = []
    for record in reader:
        if any((value or "").strip() for value in record.values() if isinstance(value, str)):
            rows.append({str(key): (value if isinstance(value, str) else "") for key, value in record.items()})
    return rows


def count_migration_rows(path: Path) -> tuple[int, tuple[str, ...]]:
    """Count data rows of ``test-migration-map.csv``, skipping comments/header.

    Args:
        path: Path to the CSV artifact.

    Returns:
        ``(row_count, fieldnames)`` where ``row_count`` excludes the comment
        banner, the header and blank lines.
    """
    rows = read_migration_rows(path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
    except OSError as error:  # pragma: no cover - filesystem edge case
        raise ArtifactError(f"cannot read {path.name}: {error}") from error
    fieldnames = tuple(csv.DictReader(lines).fieldnames or ())
    return len(rows), fieldnames


def count_migration_outcomes(rows: Sequence[Mapping[str, str]]) -> dict[str, int]:
    """Group CSV rows by their ``outcome`` column.

    Args:
        rows: Parsed CSV data rows.

    Returns:
        ``outcome -> row count`` with keys sorted for a stable report.
    """
    counter: Counter[str] = Counter(str(row.get("outcome", "")).strip() for row in rows)
    return {outcome: counter[outcome] for outcome in sorted(counter)}


def read_sha256_ledger(path: Path) -> tuple[dict[str, str], list[str]]:
    """Parse a ``sha256sum``-style ledger (``<digest><two spaces><path>``).

    Args:
        path: Path to ``manifest.sha256``.

    Returns:
        ``(entries, problems)`` where ``entries`` maps relative path to digest
        and ``problems`` lists malformed lines.

    Raises:
        ArtifactError: If the ledger cannot be read.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:  # pragma: no cover - filesystem edge case
        raise ArtifactError(f"cannot read {path.name}: {error}") from error

    entries: dict[str, str] = {}
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        digest, separator, relative = line.partition("  ")
        relative = relative.strip()
        if not separator or not relative:
            problems.append(f"{path.name}:{number}: malformed ledger line")
            continue
        if relative in entries:
            problems.append(f"{path.name}:{number}: duplicate entry for {relative}")
            continue
        entries[relative] = digest.strip().lower()
    return entries, problems


# ---------------------------------------------------------------------------
# Check model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single semantic check."""

    check_id: str
    label: str
    expected: Any
    recomputed: Any
    failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True when no failure was recorded for this check."""
        return not self.failures

    def with_note(self, note: str) -> "CheckResult":
        """Return a copy of this result with one extra informative note.

        Args:
            note: Note text appended after the existing notes.

        Returns:
            A new :class:`CheckResult` (the dataclass is frozen).
        """
        return CheckResult(
            check_id=self.check_id,
            label=self.label,
            expected=self.expected,
            recomputed=self.recomputed,
            failures=self.failures,
            notes=self.notes + (note,),
        )

    def render(self, verbose: bool = False) -> str:
        """Render the check as report lines.

        Args:
            verbose: Also emit successful informative notes.

        Returns:
            One status line plus optional ``note:``/``reason:`` lines.
        """
        status = "OK" if self.ok else "MISMATCH"
        lines = [
            f"[semantic] {self.check_id:<3} {self.label:<30} "
            f"expect={_fmt_value(self.expected):<14} "
            f"recomputed={_fmt_value(self.recomputed):<14} {status}"
        ]
        if verbose or not self.ok:
            for note in self.notes:
                lines.append(f"[semantic]     note: {note}")
        for failure in self.failures:
            lines.append(f"[semantic]     reason: {failure}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the check for ``--json`` output."""
        return {
            "id": self.check_id,
            "label": self.label,
            "expected": self.expected,
            "recomputed": self.recomputed,
            "ok": self.ok,
            "failures": list(self.failures),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class GateReport:
    """Aggregated outcome of the semantic gate."""

    contracts_dir: Path
    manifest_sha256: str
    checks: tuple[CheckResult, ...]
    header_notes: tuple[str, ...] = ()

    @property
    def mismatched(self) -> tuple[CheckResult, ...]:
        """All checks that failed."""
        return tuple(check for check in self.checks if not check.ok)

    @property
    def mismatched_ids(self) -> tuple[str, ...]:
        """Identifiers of the failed checks, in report order."""
        return tuple(check.check_id for check in self.mismatched)

    @property
    def ok(self) -> bool:
        """True when every check passed."""
        return not self.mismatched

    def render(self, verbose: bool = False) -> str:
        """Render the whole report.

        Args:
            verbose: Also emit successful informative notes.

        Returns:
            Multi-line report text.
        """
        lines = [
            f"[semantic] contracts dir: {self.contracts_dir.as_posix()}",
            f"[semantic] anchor: {MANIFEST_JSON} sha256={self.manifest_sha256}",
            f"[semantic] method: recompute every number from the artifacts, re-decide "
            f"C22/C23 from their evidence rows, compare to criteria[].measured and to "
            f"the artifacts' own self-declared blocks",
        ]
        for note in self.header_notes:
            lines.append(f"[semantic] note: {note}")
        for check in self.checks:
            lines.append(check.render(verbose=verbose))
        lines.append(
            f"[semantic] RESULT: {len(self.checks)} checks, {len(self.mismatched)} mismatch"
        )
        if self.mismatched:
            lines.append(
                "[semantic] VERDICT: FAIL (semantic contradiction between artifacts and ledger)"
            )
        else:
            lines.append("[semantic] VERDICT: PASS")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the report for ``--json`` output."""
        return {
            "contracts_dir": self.contracts_dir.as_posix(),
            "manifest_sha256": self.manifest_sha256,
            "check_count": len(self.checks),
            "mismatch_count": len(self.mismatched),
            "ok": self.ok,
            "header_notes": list(self.header_notes),
            "checks": [check.to_dict() for check in self.checks],
        }


# ---------------------------------------------------------------------------
# Check construction helpers
# ---------------------------------------------------------------------------


def _require_criterion(
    criteria: Mapping[str, Mapping[str, Any]], criterion_id: str
) -> Mapping[str, Any]:
    """Fetch a criterion by id.

    Args:
        criteria: Criteria indexed by id.
        criterion_id: Identifier such as ``C8``.

    Returns:
        The criterion mapping.

    Raises:
        ArtifactError: If the criterion is not present in the manifest.
    """
    criterion = criteria.get(criterion_id)
    if criterion is None:
        raise ArtifactError(f"{MANIFEST_JSON}: criteria[{criterion_id}] is missing")
    return criterion


def _compare(
    criterion: Mapping[str, Any],
    label: str,
    recomputed: Any,
    declared: Sequence[tuple[Any, ...]] = (),
    extra_failures: Sequence[str] = (),
    extra_notes: Sequence[str] = (),
) -> CheckResult:
    """Compare a recomputed value against the ledger claim and declared counts.

    Args:
        criterion: The criterion entry that owns this metric.
        label: Human readable metric name for the report line.
        recomputed: Value freshly derived from the artifact structures (or, for
            the judgement criteria, the verdict re-decided from evidence rows).
        declared: Declared statistics copied from the artifact's own blocks (or
            a sister artifact). Each entry is either ``(name, value)`` --
            ``value`` must equal ``recomputed`` -- or ``(name, value, target)``
            where ``target`` overrides the value the statistic is expected to
            equal (e.g. an aggregate of ``recomputed``). A ``None`` value means
            "not declared, skip".
        extra_failures: Semantic contradictions found by the caller that are not
            expressible as a single recomputed value (e.g. "this bucket ③ note
            duplicates another one"). Any entry turns the check red.
        extra_notes: Informative statements appended to the notes list.

    Returns:
        A populated :class:`CheckResult`.
    """
    criterion_id = str(criterion.get("id", "?"))
    measured = criterion.get("measured")
    failures: list[str] = []
    notes: list[str] = []

    if recomputed != measured:
        failures.append(
            f"artifact yields {_fmt_value(recomputed)} but criteria[{criterion_id}]"
            f".measured = {_fmt_value(measured)}"
        )

    failures.extend(extra_failures)
    notes.extend(extra_notes)

    for entry in declared:
        if len(entry) == 2:
            name, value = entry
            target = recomputed
        elif len(entry) == 3:
            name, value, target = entry
        else:  # pragma: no cover - programming error
            raise ValueError(f"declared statistic must have 2 or 3 elements: {entry!r}")
        if value is None:
            continue
        if value != target:
            failures.append(
                f"self-declared {name} = {_fmt_value(value)} disagrees with recomputed "
                f"{_fmt_value(target)} (edited statistic, re-pinned ledger?)"
            )
        else:
            notes.append(f"{name} = {_fmt_value(value)} agrees with recomputed")

    status = str(criterion.get("status", ""))
    declared_expected = criterion.get("expected")
    if status == "verified" and declared_expected != measured:
        failures.append(
            f"criteria[{criterion_id}].status = verified but measured "
            f"{_fmt_value(measured)} != expected {_fmt_value(declared_expected)} "
            "(a verified criterion must not carry a reconciliation delta)"
        )
    elif status and status != "verified":
        notes.append(f"criteria[{criterion_id}].status = {status}")

    return CheckResult(
        check_id=criterion_id,
        label=label,
        expected=measured,
        recomputed=recomputed,
        failures=tuple(failures),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Recomputed DDL numbers (shared by several checks)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DdlNumbers:
    """Numbers re-derived from the two normalized DDL artifacts."""

    tables: int
    columns: int
    metadata_indexes: int
    raw_indexes: int
    index_objects_total: int
    sqlite_tables: int
    sqlite_columns: int
    sqlite_metadata_indexes: int
    sqlite_dialect_only_by_kind: Mapping[str, int]
    sqlite_dialect_only_total: int


def recompute_ddl(artifacts: Artifacts) -> DdlNumbers:
    """Re-derive every DDL headline number from the raw table structures.

    Args:
        artifacts: Artifact accessor.

    Returns:
        The recomputed :class:`DdlNumbers`.
    """
    pg = artifacts.object_json(PG_SCHEMA)
    sqlite = artifacts.object_json(SQLITE_SCHEMA)

    pg_tables = ddl_tables(pg)
    sqlite_tables = ddl_tables(sqlite)
    metadata_indexes = count_metadata_indexes(pg_tables)
    raw_indexes = count_raw_indexes(pg)
    dialect_only_by_kind = group_dialect_only(sqlite)

    return DdlNumbers(
        tables=len(pg_tables),
        columns=count_ddl_columns(pg_tables),
        metadata_indexes=metadata_indexes,
        raw_indexes=raw_indexes,
        index_objects_total=metadata_indexes + raw_indexes,
        sqlite_tables=len(sqlite_tables),
        sqlite_columns=count_ddl_columns(sqlite_tables),
        sqlite_metadata_indexes=count_metadata_indexes(sqlite_tables),
        sqlite_dialect_only_by_kind=dialect_only_by_kind,
        sqlite_dialect_only_total=sum(dialect_only_by_kind.values()),
    )


# ---------------------------------------------------------------------------
# C1..C13 -- numbers
# ---------------------------------------------------------------------------


def _openapi_checks(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> list[CheckResult]:
    """C1/C2/C3 -- OpenAPI surface, recomputed from ``paths``/``components``."""
    openapi = artifacts.object_json(OPENAPI)

    info = openapi.get("info") if isinstance(openapi.get("info"), Mapping) else {}
    version_note = f"info.version = {info.get('version')}"

    return [
        _compare(
            _require_criterion(criteria, "C1"), "openapi.paths", count_openapi_paths(openapi)
        ).with_note(version_note),
        _compare(
            _require_criterion(criteria, "C2"),
            "openapi.operations",
            count_openapi_operations(openapi),
        ),
        _compare(
            _require_criterion(criteria, "C3"),
            "openapi.schemas",
            count_openapi_schemas(openapi),
        ),
    ]


def _ddl_checks(
    artifacts: Artifacts,
    criteria: Mapping[str, Mapping[str, Any]],
    numbers: DdlNumbers,
) -> list[CheckResult]:
    """C4..C8 -- PostgreSQL DDL numbers plus their self-declared ``counts``."""
    pg_counts = artifacts.object_json(PG_SCHEMA).get("counts")
    pg_counts = pg_counts if isinstance(pg_counts, Mapping) else {}
    sqlite_counts = artifacts.object_json(SQLITE_SCHEMA).get("counts")
    sqlite_counts = sqlite_counts if isinstance(sqlite_counts, Mapping) else {}

    return [
        _compare(
            _require_criterion(criteria, "C4"),
            "ddl.tables",
            numbers.tables,
            declared=(
                ("pg counts.tables", pg_counts.get("tables")),
                ("sqlite tables (cross-dialect)", numbers.sqlite_tables),
            ),
        ),
        _compare(
            _require_criterion(criteria, "C5"),
            "ddl.columns",
            numbers.columns,
            declared=(
                ("pg counts.columns", pg_counts.get("columns")),
                ("sqlite columns (cross-dialect)", numbers.sqlite_columns),
            ),
        ),
        _compare(
            _require_criterion(criteria, "C6"),
            "ddl.metadata_indexes",
            numbers.metadata_indexes,
            declared=(
                ("pg counts.metadata_indexes", pg_counts.get("metadata_indexes")),
                ("sqlite metadata_indexes (cross-dialect)", numbers.sqlite_metadata_indexes),
            ),
        ),
        _compare(
            _require_criterion(criteria, "C7"),
            "ddl.raw_hnsw_indexes",
            numbers.raw_indexes,
            declared=(("pg counts.raw_indexes", pg_counts.get("raw_indexes")),),
        ),
        _compare(
            _require_criterion(criteria, "C8"),
            "ddl.index_objects_total",
            numbers.index_objects_total,
            declared=(
                ("pg counts.index_objects_total", pg_counts.get("index_objects_total")),
                (
                    "pg counts.metadata_indexes + counts.raw_indexes",
                    _add_pair(pg_counts.get("metadata_indexes"), pg_counts.get("raw_indexes")),
                ),
            ),
        ),
    ]


def _add_pair(left: Any, right: Any) -> Any:
    """Add two optional integers, returning ``None`` when either is unusable."""
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if isinstance(left, int) and isinstance(right, int):
        return left + right
    return None


def _sqlite_check(
    artifacts: Artifacts,
    criteria: Mapping[str, Mapping[str, Any]],
    numbers: DdlNumbers,
) -> CheckResult:
    """C9 -- SQLite ``dialect_only`` objects grouped by kind."""
    sqlite_counts = artifacts.object_json(SQLITE_SCHEMA).get("counts")
    sqlite_counts = sqlite_counts if isinstance(sqlite_counts, Mapping) else {}
    declared_kinds = sqlite_counts.get("dialect_only_by_kind")
    recomputed = dict(numbers.sqlite_dialect_only_by_kind)
    return _compare(
        _require_criterion(criteria, "C9"),
        "sqlite.dialect_only",
        recomputed,
        declared=(
            (
                "sqlite counts.dialect_only_by_kind",
                dict(declared_kinds) if isinstance(declared_kinds, Mapping) else None,
            ),
            (
                "sqlite counts.dialect_only_objects",
                sqlite_counts.get("dialect_only_objects"),
                sum(recomputed.values()),
            ),
        ),
    )


def _sse_checks(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> list[CheckResult]:
    """C10/C11 -- SSE channel inventory and golden frame references."""
    channels_document = artifacts.object_json(SSE_CHANNELS)

    channels = channels_document.get("channels")
    channel_count = len(channels) if isinstance(channels, list) else 0
    by_channel = channels_document.get("by_channel")
    by_channel_count = len(by_channel) if isinstance(by_channel, Mapping) else None

    return [
        _compare(
            _require_criterion(criteria, "C10"),
            "sse.channels",
            channel_count,
            declared=(("by_channel entries", by_channel_count),),
        ),
        _compare(
            _require_criterion(criteria, "C11"),
            "sse.golden_frames",
            count_sse_golden_frames(channels_document),
        ),
    ]


def _sse_golden_coverage_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C12 -- every declared channel must own a real golden frame file.

    ``channels[].golden`` is relative to ``contracts/sse/``. Coverage means three
    things at once, all re-derived here instead of trusted:

    1. the channel row *has* a ``golden`` reference;
    2. the referenced file exists inside ``sse/`` (no path escape);
    3. the recorded ``golden_sha256`` still matches the bytes on disk.

    Args:
        artifacts: Artifact accessor.
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C12``.
    """
    channels_document = artifacts.object_json(SSE_CHANNELS)
    channels = channels_document.get("channels")
    channels = [entry for entry in channels if isinstance(entry, Mapping)] if isinstance(channels, list) else []

    failures: list[str] = []
    notes: list[str] = []
    covered = 0
    covered_channels: list[str] = []

    if not channels:
        failures.append(f"{SSE_CHANNELS}: no 'channels[]' rows to cover")

    golden_root = (artifacts.contracts_dir / SSE_DIR).resolve()
    for entry in channels:
        name = str(entry.get("channel") or entry.get("domain_type") or "<unnamed>")
        reference = entry.get("golden")
        if not reference:
            failures.append(f"channel {name}: has no 'golden' reference (coverage hole)")
            continue
        relative = str(reference).replace("\\", "/").lstrip("/")
        target = (golden_root / relative).resolve()
        if golden_root != target and golden_root not in target.parents:
            failures.append(f"channel {name}: golden path {relative!r} escapes {SSE_DIR}/")
            continue
        if not target.is_file():
            failures.append(
                f"channel {name}: golden frame {relative!r} does not exist under {golden_root.as_posix()}"
            )
            continue
        covered += 1
        covered_channels.append(relative)
        declared_digest = entry.get("golden_sha256")
        actual_digest = sha256_file(target)
        if isinstance(declared_digest, str) and declared_digest and declared_digest != actual_digest:
            failures.append(
                f"channel {name}: golden_sha256 {declared_digest[:12]} != disk {actual_digest[:12]}"
            )

    notes.append(f"{covered}/{len(channels)} channels resolve to an existing golden file")
    if covered_channels:
        notes.append(f"golden files: {', '.join(sorted(covered_channels))}")

    recomputed = "complete" if not failures else f"incomplete({len(failures)} issue(s))"
    return _compare(
        _require_criterion(criteria, "C12"),
        "sse.golden_coverage",
        recomputed,
        extra_failures=failures,
        extra_notes=notes,
    )


def _errors_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C13 -- error code table size."""
    errors_document = artifacts.object_json(ERRORS)
    return _compare(
        _require_criterion(criteria, "C13"),
        "errors.codes",
        count_collection(errors_document, "codes"),
    )


def _envelope_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C14 -- the three envelope shells must carry exactly the four frozen keys.

    Recomputed straight from ``$defs.<shell>.required`` / ``.properties``:
    every shell must require exactly ``code/message/data/request_id``, expose no
    other property, and forbid additional properties. The reported value is the
    number of keys required by *all* shells, so a single shell losing a key
    drops it below 4 and turns the check red.

    Args:
        artifacts: Artifact accessor.
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C14``.
    """
    envelope = artifacts.object_json(ENVELOPE)
    defs = envelope.get("$defs")
    if not isinstance(defs, Mapping):
        defs = envelope.get("definitions")
    if not isinstance(defs, Mapping):
        raise ArtifactError(f"{ENVELOPE}: neither '$defs' nor 'definitions' is an object")

    canonical = set(CANONICAL_ENVELOPE_KEYS)
    failures: list[str] = []
    notes: list[str] = []
    required_sets: dict[str, set[str]] = {}

    for shell_name in ENVELOPE_SHELL_DEFS:
        shell = defs.get(shell_name)
        if not isinstance(shell, Mapping):
            failures.append(f"{ENVELOPE}: $defs.{shell_name} is missing")
            continue
        required = shell.get("required")
        keys = {str(key) for key in required} if isinstance(required, list) else set()
        required_sets[shell_name] = keys
        notes.append(f"{shell_name}.required = {sorted(keys)}")
        if keys != canonical:
            failures.append(
                f"{shell_name}.required = {sorted(keys)} != "
                f"{sorted(canonical)} (总纲 §11.1 four-key shell)"
            )
        properties = shell.get("properties")
        if isinstance(properties, Mapping) and set(map(str, properties)) != keys:
            failures.append(
                f"{shell_name}.properties = {sorted(map(str, properties))} != "
                f"required {sorted(keys)} (a declared property must be required, "
                "and a required key must be declared)"
            )
        if shell.get("additionalProperties") is not False:
            failures.append(
                f"{shell_name}.additionalProperties = "
                f"{_fmt_value(shell.get('additionalProperties'))} "
                "(must be false so no fifth top-level key can appear)"
            )

    common = set(CANONICAL_ENVELOPE_KEYS)
    for keys in required_sets.values():
        common &= keys
    if len(required_sets) == len(ENVELOPE_SHELL_DEFS):
        distinct = {tuple(sorted(keys)) for keys in required_sets.values()}
        if len(distinct) > 1:
            failures.append(
                f"the three shells require different key sets: {_fmt_value(sorted(distinct))}"
            )

    return _compare(
        _require_criterion(criteria, "C14"),
        "envelope.shell_keys",
        len(common),
        extra_failures=failures,
        extra_notes=notes,
    )


# ---------------------------------------------------------------------------
# C15..C20 -- migration map, reproducibility, conformance
# ---------------------------------------------------------------------------


def _migration_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C15 -- migration map data rows (comments and header excluded)."""
    rows, fieldnames = count_migration_rows(artifacts.path(MIGRATION_CSV))
    criterion = _require_criterion(criteria, "C15")
    note = f"header columns: {','.join(fieldnames)}" if fieldnames else "header: <none>"
    return _compare(criterion, "migration_map.rows", rows).with_note(note)


def _migration_passed_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C16 -- rows whose ``outcome`` is ``passed``.

    Counted from the CSV, then cross-checked against the summary's own
    ``observed.distribution``: the two must agree, because ``C16`` is registered
    on the ``passed`` caliber while ``C15`` is registered on ``selected``.

    Args:
        artifacts: Artifact accessor.
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C16``.
    """
    rows = read_migration_rows(artifacts.path(MIGRATION_CSV))
    outcomes = count_migration_outcomes(rows)
    passed = outcomes.get("passed", 0)

    summary = artifacts.object_json(MIGRATION_SUMMARY)
    declared_distribution = _dig(summary, "observed", "distribution")

    notes = [f"outcomes from csv = {_fmt_value(outcomes)}"]
    failures: list[str] = []
    if isinstance(declared_distribution, Mapping):
        declared_passed = declared_distribution.get("passed")
        if declared_passed != passed:
            failures.append(
                f"summary observed.distribution.passed = {_fmt_value(declared_passed)} "
                f"but the csv holds {passed} passed rows"
            )
        else:
            notes.append(f"summary observed.distribution.passed = {passed} agrees with the csv")
        declared_total = sum(
            value for value in declared_distribution.values() if isinstance(value, int)
        )
        if declared_total != len(rows):
            failures.append(
                f"summary observed.distribution sums to {declared_total} but the csv holds "
                f"{len(rows)} data rows"
            )

    return _compare(
        _require_criterion(criteria, "C16"),
        "migration_map.passed",
        passed,
        extra_failures=failures,
        extra_notes=notes,
    )


def _toolkit_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C17 -- the extraction toolkit that regenerates ``contracts/``.

    Recomputed by stat-ing the toolkit directory, so deleting a module (which
    would silently break "re-run export and get the same bytes") is visible here.

    Args:
        artifacts: Artifact accessor (its ``toolkit_dir`` is inspected).
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C17``.
    """
    toolkit = artifacts.toolkit_dir
    present = [name for name in REQUIRED_TOOLKIT if (toolkit / name).is_file()]
    missing = [name for name in REQUIRED_TOOLKIT if name not in present]

    failures = [
        f"toolkit module {name} is missing from {toolkit.as_posix()} "
        "(contracts/ would no longer be reproducible)"
        for name in missing
    ]
    notes = [f"toolkit dir: {toolkit.as_posix()}"]
    if not toolkit.is_dir():
        failures.append(f"toolkit directory not found: {toolkit.as_posix()}")

    return _compare(
        _require_criterion(criteria, "C17"),
        "reproducibility.toolkit",
        present,
        extra_failures=failures,
        extra_notes=notes,
    )


def _ledgers_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C18 -- both ledgers exist and describe the same artifact set.

    Beyond presence, the two ledgers must agree with each other: the set of
    paths in ``manifest.sha256`` must equal ``objects[].path`` plus the object
    ledger's own self-entry, and every shared path must carry the same digest.
    A ledger that stops listing an artifact is exactly how a "frozen" baseline
    quietly loses a file.

    Args:
        artifacts: Artifact accessor.
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C18``.
    """
    contracts = artifacts.contracts_dir
    present = [name for name in REQUIRED_LEDGERS if (contracts / name).is_file()]
    failures = [
        f"ledger {name} is missing from {contracts.as_posix()}"
        for name in REQUIRED_LEDGERS
        if name not in present
    ]
    notes: list[str] = []

    if len(present) == len(REQUIRED_LEDGERS):
        entries, problems = read_sha256_ledger(contracts / MANIFEST_SHA)
        failures.extend(problems)

        manifest = artifacts.manifest()
        objects_raw = manifest.get("objects")
        objects = (
            [entry for entry in objects_raw if isinstance(entry, Mapping)]
            if isinstance(objects_raw, list)
            else []
        )
        object_digests = {
            str(entry.get("path", "")): str(entry.get("sha256", "")) for entry in objects
        }
        object_paths = set(object_digests)
        expected_paths = object_paths | {MANIFEST_JSON}
        expected_count = len(object_paths - {MANIFEST_JSON}) + 1

        if len(entries) != expected_count:
            failures.append(
                f"{MANIFEST_SHA} holds {len(entries)} entries but "
                f"{MANIFEST_JSON}.objects holds {len(object_paths)} artifact(s) "
                f"(+1 self-entry) = {expected_count}"
            )
        for name in sorted(expected_paths - set(entries)):
            failures.append(f"{name}: recorded in {MANIFEST_JSON}.objects but absent from {MANIFEST_SHA}")
        for name in sorted(set(entries) - expected_paths):
            failures.append(f"{name}: recorded in {MANIFEST_SHA} but absent from {MANIFEST_JSON}.objects")
        for name in sorted(object_paths & set(entries)):
            if object_digests[name] != entries[name]:
                failures.append(
                    f"{name}: the two ledgers disagree "
                    f"({MANIFEST_SHA} {entries[name][:12]} vs {MANIFEST_JSON} "
                    f"{object_digests[name][:12]})"
                )
        notes.append(
            f"{MANIFEST_SHA}: {len(entries)} entries; {MANIFEST_JSON}.objects: "
            f"{len(object_paths)} artifact(s) + self-entry"
        )

    return _compare(
        _require_criterion(criteria, "C18"),
        "reproducibility.ledgers",
        present,
        extra_failures=failures,
        extra_notes=notes,
    )


def _conformance_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C19 -- number of conformance skeleton files on disk.

    Args:
        artifacts: Artifact accessor.
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C19``.
    """
    directory = artifacts.contracts_dir / CONFORMANCE_DIR
    if not directory.is_dir():
        raise ArtifactError(
            f"missing directory: {CONFORMANCE_DIR}/ (under {artifacts.contracts_dir.as_posix()})"
        )
    files = sorted(path.name for path in directory.glob("*.yaml") if path.is_file())
    notes = [f"files = {files}"]
    failures: list[str] = []
    if not files:
        failures.append(f"{CONFORMANCE_DIR}/ holds no *.yaml skeleton")
    return _compare(
        _require_criterion(criteria, "C19"),
        "conformance.skeletons",
        len(files),
        extra_failures=failures,
        extra_notes=notes,
    )


def _migration_digests_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C20 -- digests the migration summary declares about itself.

    The summary embeds ``artifacts{path: sha256}``. Every one of them is
    recomputed from disk and additionally compared with the object ledger and
    with ``manifest.sha256`` -- the "triple cross-check" the criterion claims.

    Args:
        artifacts: Artifact accessor.
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C20``.
    """
    summary = artifacts.object_json(MIGRATION_SUMMARY)
    declared = summary.get("artifacts")
    if not isinstance(declared, Mapping) or not declared:
        raise ArtifactError(f"{MIGRATION_SUMMARY}: 'artifacts' is missing or empty")

    manifest = artifacts.manifest()
    objects_raw = manifest.get("objects")
    object_digests = {
        str(entry.get("path", "")): str(entry.get("sha256", ""))
        for entry in (objects_raw if isinstance(objects_raw, list) else [])
        if isinstance(entry, Mapping)
    }
    entries, ledger_problems = read_sha256_ledger(artifacts.path(MANIFEST_SHA))

    failures: list[str] = list(ledger_problems)
    checked: list[str] = []
    for relative in sorted(str(name) for name in declared):
        recorded = str(declared[relative])
        target = artifacts.contracts_dir / relative
        if not target.is_file():
            failures.append(
                f"self-declared artifact {relative} does not exist on disk "
                f"(summary claims {recorded[:12]})"
            )
            continue
        actual = sha256_file(target)
        checked.append(relative)
        if recorded != actual:
            failures.append(
                f"{relative}: summary self-declared {recorded[:12]} != disk {actual[:12]}"
            )
        if object_digests.get(relative) != actual:
            failures.append(
                f"{relative}: object ledger digest "
                f"{str(object_digests.get(relative))[:12]} != disk {actual[:12]}"
            )
        if entries.get(relative) != actual:
            failures.append(
                f"{relative}: {MANIFEST_SHA} digest "
                f"{str(entries.get(relative))[:12]} != disk {actual[:12]}"
            )

    notes = [f"{len(checked)}/{len(declared)} self-declared artifact(s) verified against disk"]
    recomputed = "consistent" if not failures else f"inconsistent({len(failures)} issue(s))"
    return _compare(
        _require_criterion(criteria, "C20"),
        "migration.self_declared_digests",
        recomputed,
        extra_failures=failures,
        extra_notes=notes,
    )


# ---------------------------------------------------------------------------
# C21/S1 -- object ledger
# ---------------------------------------------------------------------------


def _ddl_object_total_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C21 -- DDL object ledger size."""
    manifest = artifacts.manifest()
    ddl_objects = manifest.get("ddl_objects")
    total = len(ddl_objects) if isinstance(ddl_objects, list) else 0
    schema_block = manifest.get("schema")
    schema_block = schema_block if isinstance(schema_block, Mapping) else {}
    return _compare(
        _require_criterion(criteria, "C21"),
        "ddl_objects.total",
        total,
        declared=(("schema.ddl_object_count", schema_block.get("ddl_object_count")),),
    )


def _ddl_object_consistency_check(
    artifacts: Artifacts, numbers: DdlNumbers
) -> CheckResult:
    """Structural self-consistency of ``ddl_objects[]`` (kinds, sources, dialects).

    The ledger must decompose exactly into the numbers recomputed from the two
    normalized DDL artifacts; any drift means the object ledger and the data no
    longer describe the same database.

    Args:
        artifacts: Artifact accessor.
        numbers: Recomputed DDL numbers.

    Returns:
        Check id ``S1``.
    """
    manifest = artifacts.manifest()
    ddl_objects = manifest.get("ddl_objects")
    entries = [entry for entry in ddl_objects if isinstance(entry, Mapping)] if isinstance(ddl_objects, list) else []

    failures: list[str] = []
    notes: list[str] = []

    actual_kinds = Counter(str(entry.get("kind")) for entry in entries)
    expected_kinds = {
        "table": numbers.tables,
        "index.metadata": numbers.metadata_indexes,
        "index.raw_hnsw": numbers.raw_indexes,
    }
    expected_kinds.update({kind: count for kind, count in numbers.sqlite_dialect_only_by_kind.items()})

    for kind in sorted(set(actual_kinds) | set(expected_kinds)):
        actual = actual_kinds.get(kind, 0)
        expected = expected_kinds.get(kind, 0)
        if actual != expected:
            failures.append(f"kind {kind}: ddl_objects has {actual}, artifacts yield {expected}")
    if not failures:
        notes.append(f"kinds = {_fmt_value(dict(sorted(actual_kinds.items())))}")

    actual_sources = Counter(str(entry.get("source")) for entry in entries)
    expected_sources = {
        "metadata": numbers.tables + numbers.metadata_indexes,
        "migration": numbers.raw_indexes + numbers.sqlite_dialect_only_total,
    }
    for source in sorted(set(actual_sources) | set(expected_sources)):
        actual = actual_sources.get(source, 0)
        expected = expected_sources.get(source, 0)
        if actual != expected:
            failures.append(f"source {source}: ddl_objects has {actual}, expected {expected}")
    if not failures:
        notes.append(f"sources = {_fmt_value(dict(sorted(actual_sources.items())))}")

    actual_dialects = Counter(str(entry.get("dialect_only")) for entry in entries)
    expected_dialects = {
        "None": numbers.tables + numbers.metadata_indexes,
        "pg": numbers.raw_indexes,
        "sqlite": numbers.sqlite_dialect_only_total,
    }
    for dialect in sorted(set(actual_dialects) | set(expected_dialects)):
        actual = actual_dialects.get(dialect, 0)
        expected = expected_dialects.get(dialect, 0)
        if actual != expected:
            failures.append(
                f"dialect_only {dialect}: ddl_objects has {actual}, expected {expected}"
            )
    if not failures:
        notes.append(f"dialect_only = {_fmt_value(dict(sorted(actual_dialects.items())))}")

    if numbers.tables != numbers.sqlite_tables:
        failures.append(
            f"cross-dialect tables: pg={numbers.tables} sqlite={numbers.sqlite_tables}"
        )
    if numbers.columns != numbers.sqlite_columns:
        failures.append(
            f"cross-dialect columns: pg={numbers.columns} sqlite={numbers.sqlite_columns}"
        )
    if numbers.metadata_indexes != numbers.sqlite_metadata_indexes:
        failures.append(
            "cross-dialect metadata indexes: "
            f"pg={numbers.metadata_indexes} sqlite={numbers.sqlite_metadata_indexes}"
        )

    consistent = "consistent" if not failures else f"{len(failures)} issue(s)"
    return CheckResult(
        check_id="S1",
        label="ddl_objects.self_consistency",
        expected="consistent",
        recomputed=consistent,
        failures=tuple(failures),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# C22 -- errors.http_status_uniformity (the D-1 regression gate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniformityVerdict:
    """Re-decided verdict for ``C22``.

    Attributes:
        failures: Semantic contradictions; any entry turns ``C22`` red.
        notes: Informative statements for ``--verbose``.
        non_uniform_codes: Codes whose call sites really do disagree.
        uniform_codes: Codes whose call sites really do agree.
        unverifiable_codes: Codes that carry no resolved call site.
    """

    failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    non_uniform_codes: tuple[str, ...] = ()
    uniform_codes: tuple[str, ...] = ()
    unverifiable_codes: tuple[str, ...] = ()


def _status_key(row: Mapping[str, Any]) -> tuple[str, Any, str]:
    """Build a comparable identity for one resolved call site.

    Args:
        row: One ``http_status_by_call_site_resolved`` entry.

    Returns:
        ``(file, line, actual_status)`` tuple with the statuses stringified so
        int/str representations compare equal.
    """
    return (str(row.get("file", "")), str(row.get("line", "")), str(row.get("actual_status")))


def analyse_http_status_uniformity(errors_document: Mapping[str, Any]) -> UniformityVerdict:
    """Decide ``C22`` from the evidence rows instead of from the flag.

    The D-1 defect was "``http_status: 503`` masked two call sites that really
    answer 500". The guard against it therefore cannot be the *flag*
    ``http_status_uniform`` -- a tamperer flips that in one keystroke. It must be
    the derived truth from ``http_status_by_call_site_resolved``:

    1. the derived distribution must equal the declared
       ``http_status_distribution`` **and** sum to the number of resolved rows;
    2. ``http_status_uniform=false`` requires a multi-valued resolved set, a
       distribution and a non-empty ``http_status_inconsistent_call_sites``
       that lists *exactly* the rows whose ``actual_status`` deviates from
       ``http_status``;
    3. ``http_status_uniform=true`` requires a single-valued resolved set, an
       empty inconsistent list and a ``http_status`` equal to that value;
    4. codes without any resolved call site must not claim uniformity;
    5. ``meta.codes_with_non_uniform_http_status`` /
       ``meta.codes_with_uniform_http_status`` must agree with the derivation.

    Args:
        errors_document: Parsed ``errors.json``.

    Returns:
        The :class:`UniformityVerdict` for ``C22``.

    Raises:
        ArtifactError: If ``codes`` is not a mapping.
    """
    codes = errors_document.get("codes")
    if not isinstance(codes, Mapping) or not codes:
        raise ArtifactError(f"{ERRORS}: 'codes' is missing, empty or not an object")

    failures: list[str] = []
    notes: list[str] = []
    non_uniform: list[str] = []
    uniform: list[str] = []
    unverifiable: list[str] = []

    for name in sorted(str(key) for key in codes):
        entry = codes[name]
        if not isinstance(entry, Mapping):
            failures.append(f"{name}: code entry is not an object")
            continue

        declared_status = str(entry.get("http_status"))
        flag = entry.get("http_status_uniform")
        resolved_raw = entry.get("http_status_by_call_site_resolved")
        resolved_raw = resolved_raw if isinstance(resolved_raw, list) else []
        resolved = [row for row in resolved_raw if isinstance(row, Mapping)]
        if len(resolved) != len(resolved_raw):
            failures.append(f"{name}: http_status_by_call_site_resolved holds non-object rows")

        inconsistent_raw = entry.get("http_status_inconsistent_call_sites")
        inconsistent_raw = inconsistent_raw if isinstance(inconsistent_raw, list) else []
        inconsistent = [row for row in inconsistent_raw if isinstance(row, Mapping)]
        if len(inconsistent) != len(inconsistent_raw):
            failures.append(
                f"{name}: http_status_inconsistent_call_sites holds non-object rows"
            )

        distribution_raw = entry.get("http_status_distribution")
        declared_distribution: dict[str, int] = {}
        if isinstance(distribution_raw, Mapping):
            for status_key, count in distribution_raw.items():
                if isinstance(count, bool) or not isinstance(count, int):
                    failures.append(
                        f"{name}: http_status_distribution[{status_key}] is not an integer"
                    )
                    continue
                declared_distribution[str(status_key)] = count
        elif distribution_raw is not None:
            failures.append(f"{name}: http_status_distribution is not an object")

        actual_counter = Counter(str(row.get("actual_status")) for row in resolved)
        actual_distribution = {status: actual_counter[status] for status in sorted(actual_counter)}
        distinct = sorted(actual_distribution)
        multi_valued = len(distinct) > 1

        if resolved:
            if declared_distribution != actual_distribution:
                failures.append(
                    f"{name}: http_status_distribution = "
                    f"{_fmt_value(declared_distribution)} but the resolved call sites "
                    f"yield {_fmt_value(actual_distribution)}"
                )
            if sum(declared_distribution.values()) != len(resolved):
                failures.append(
                    f"{name}: http_status_distribution sums to "
                    f"{sum(declared_distribution.values())} but "
                    f"http_status_by_call_site_resolved holds {len(resolved)} row(s)"
                )
        else:
            unverifiable.append(name)
            if flag is True:
                failures.append(
                    f"{name}: http_status_uniform=true but no call site was resolved "
                    "(a uniformity claim with no evidence)"
                )
            if declared_distribution:
                failures.append(
                    f"{name}: declares http_status_distribution "
                    f"{_fmt_value(declared_distribution)} but resolved no call site"
                )

        if flag is True:
            uniform.append(name)
            if multi_valued:
                failures.append(
                    f"{name}: http_status_uniform=true is contradicted by its own call "
                    f"sites -- resolved statuses {distinct} "
                    f"(distribution {_fmt_value(actual_distribution)}, http_status="
                    f"{declared_status}) (D-1 regression: the single value masks "
                    "differing call sites)"
                )
            if inconsistent:
                failures.append(
                    f"{name}: http_status_uniform=true but "
                    f"http_status_inconsistent_call_sites lists {len(inconsistent)} row(s)"
                )
            if resolved and declared_status not in distinct:
                failures.append(
                    f"{name}: http_status={declared_status} is not among the resolved "
                    f"statuses {distinct}"
                )
        elif flag is False:
            non_uniform.append(name)
            if not resolved:
                failures.append(
                    f"{name}: http_status_uniform=false without any resolved call site "
                    "(nothing to justify the disclosure)"
                )
            elif not multi_valued:
                failures.append(
                    f"{name}: http_status_uniform=false but every resolved call site "
                    f"answers {distinct} (self-contradictory disclosure)"
                )
            if not declared_distribution:
                failures.append(
                    f"{name}: http_status_uniform=false must disclose http_status_distribution"
                )
            if not inconsistent:
                failures.append(
                    f"{name}: http_status_uniform=false must disclose "
                    "http_status_inconsistent_call_sites"
                )
            expected_inconsistent = sorted(
                _status_key(row) for row in resolved if str(row.get("actual_status")) != declared_status
            )
            declared_inconsistent = sorted(_status_key(row) for row in inconsistent)
            if sorted(declared_distribution) and multi_valued:
                mode = actual_distribution[distinct[0]]
                for status in distinct:
                    if actual_distribution[status] > mode:
                        mode = actual_distribution[status]
                majority = [status for status in distinct if actual_distribution[status] == mode]
                if declared_status not in majority:
                    failures.append(
                        f"{name}: http_status={declared_status} is not the majority call-site "
                        f"value {majority} (distribution {_fmt_value(actual_distribution)})"
                    )
            if expected_inconsistent != declared_inconsistent:
                failures.append(
                    f"{name}: http_status_inconsistent_call_sites = "
                    f"{_fmt_value(declared_inconsistent)} but the deviating rows are "
                    f"{_fmt_value(expected_inconsistent)}"
                )
        elif flag is None:
            if resolved:
                failures.append(
                    f"{name}: http_status_uniform is null although "
                    f"{len(resolved)} call site(s) were resolved"
                )
        else:
            failures.append(
                f"{name}: http_status_uniform = {_fmt_value(flag)} is not a boolean"
            )

    meta = errors_document.get("meta")
    meta = meta if isinstance(meta, Mapping) else {}
    declared_non_uniform = meta.get("codes_with_non_uniform_http_status")
    if isinstance(declared_non_uniform, list):
        declared_set = sorted(str(code) for code in declared_non_uniform)
        if declared_set != sorted(non_uniform):
            failures.append(
                f"meta.codes_with_non_uniform_http_status = {declared_set} but the "
                f"call-site evidence yields {sorted(non_uniform)}"
            )
        else:
            notes.append(f"meta.codes_with_non_uniform_http_status = {declared_set} agrees")
    declared_uniform_count = meta.get("codes_with_uniform_http_status")
    if isinstance(declared_uniform_count, int) and not isinstance(declared_uniform_count, bool):
        if declared_uniform_count != len(uniform):
            failures.append(
                f"meta.codes_with_uniform_http_status = {declared_uniform_count} but "
                f"{len(uniform)} code(s) actually carry http_status_uniform=true"
            )
        else:
            notes.append(f"meta.codes_with_uniform_http_status = {declared_uniform_count} agrees")
    declared_resolved = meta.get("call_site_resolved")
    if isinstance(declared_resolved, Mapping):
        for code in sorted(str(key) for key in declared_resolved):
            entry = codes.get(code)
            if not isinstance(entry, Mapping):
                failures.append(f"meta.call_site_resolved names unknown code {code}")
                continue
            if str(declared_resolved[code]) != str(entry.get("http_status")):
                failures.append(
                    f"meta.call_site_resolved[{code}] = {declared_resolved[code]} but "
                    f"codes[{code}].http_status = {entry.get('http_status')}"
                )

    notes.append(
        f"derived uniformity: {len(uniform)} uniform / {len(non_uniform)} non-uniform "
        f"/ {len(unverifiable)} without resolved call sites"
    )
    if non_uniform:
        notes.append(f"non-uniform codes derive to {sorted(non_uniform)}")

    return UniformityVerdict(
        failures=tuple(failures),
        notes=tuple(notes),
        non_uniform_codes=tuple(sorted(non_uniform)),
        uniform_codes=tuple(sorted(uniform)),
        unverifiable_codes=tuple(sorted(unverifiable)),
    )


def _errors_uniformity_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C22 -- error codes must not hide call-site status differences (defect D-1).

    Args:
        artifacts: Artifact accessor.
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C22``.
    """
    errors_document = artifacts.object_json(ERRORS)
    verdict = analyse_http_status_uniformity(errors_document)
    recomputed = "consistent" if not verdict.failures else f"inconsistent({len(verdict.failures)} issue(s))"
    return _compare(
        _require_criterion(criteria, "C22"),
        "errors.http_status_uniformity",
        recomputed,
        extra_failures=verdict.failures,
        extra_notes=verdict.notes,
    )


# ---------------------------------------------------------------------------
# C23 -- migration.disposition_auditability (the D-2 regression gate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispositionVerdict:
    """Re-decided verdict for ``C23``."""

    failures: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    dropped_rows: int = 0
    protected_ids: tuple[str, ...] = ()


def analyse_disposition_auditability(artifacts: Artifacts) -> DispositionVerdict:
    """Decide ``C23`` from the CSV rows and the summary's own overrides.

    The D-2 defect was a copy-pasted bucket ③ block plus one genuinely
    *protected* case (the only API-level fail-closed assertion) being filed as
    "abandoned". So each bucket ③ row is judged on its own merits:

    1. every bucket ③ ``note`` must be substantively different from the others
       (copy-paste detection, whitespace-insensitive);
    2. no ``MUST_NOT_BE_DROPPED`` case may sit in bucket ③ -- checked both
       against the hard-coded protected ids and against the fail-closed markers
       in the row's id/capability (so a rename cannot sneak through);
    3. every bucket ③ ``note`` must be long enough and must actually state why
       the case was dropped;
    4. the summary's ``case_overrides[]`` must agree with the CSV row it
       describes, and its bucket distribution must match the CSV.

    Args:
        artifacts: Artifact accessor.

    Returns:
        The :class:`DispositionVerdict` for ``C23``.

    Raises:
        ArtifactError: If the CSV has no data rows or lacks a required column.
    """
    rows = read_migration_rows(artifacts.path(MIGRATION_CSV))
    if not rows:
        raise ArtifactError(f"{MIGRATION_CSV}: no data rows")

    required_columns = {"test_id", "bucket", "note"}
    missing_columns = required_columns - set(rows[0])
    if missing_columns:
        raise ArtifactError(
            f"{MIGRATION_CSV}: missing column(s) {sorted(missing_columns)}"
        )

    summary = artifacts.object_json(MIGRATION_SUMMARY)
    protected = set(PROTECTED_TEST_IDS)
    overrides = summary.get("case_overrides")
    overrides = [entry for entry in overrides if isinstance(entry, Mapping)] if isinstance(overrides, list) else []
    for entry in overrides:
        haystack = f"{entry.get('test_id', '')} {entry.get('capability', '')}".lower()
        if any(marker in haystack for marker in FAIL_CLOSED_MARKERS):
            protected.add(str(entry.get("test_id", "")))

    failures: list[str] = []
    notes: list[str] = []

    by_test_id: dict[str, Mapping[str, str]] = {}
    for row in rows:
        test_id = str(row.get("test_id", "")).strip()
        if test_id in by_test_id:
            failures.append(f"{test_id}: appears more than once in the migration map")
        by_test_id[test_id] = row

    dropped = [row for row in rows if str(row.get("bucket", "")).strip() == BUCKET_DROPPED]
    if not dropped:
        failures.append(
            f"no row is judged bucket={BUCKET_DROPPED}; the disposition record is empty"
        )

    seen_notes: dict[str, str] = {}
    for row in dropped:
        test_id = str(row.get("test_id", "")).strip()
        note = str(row.get("note", ""))
        normalised = _normalise_text(note)

        if test_id in protected:
            failures.append(
                f"{test_id}: is MUST_NOT_BE_DROPPED (the only API-level fail-closed "
                f"assertion) but is judged bucket={BUCKET_DROPPED} (D-2 regression)"
            )
        haystack = f"{test_id} {row.get('capability', '')}".lower()
        if any(marker in haystack for marker in FAIL_CLOSED_MARKERS):
            failures.append(
                f"{test_id}: asserts fail-closed behaviour but is judged "
                f"bucket={BUCKET_DROPPED} (a fail-closed proof cannot be 'abandoned')"
            )

        if not normalised:
            failures.append(f"{test_id}: bucket={BUCKET_DROPPED} row carries no note")
        else:
            if normalised in seen_notes:
                failures.append(
                    f"{test_id}: bucket={BUCKET_DROPPED} note duplicates "
                    f"{seen_notes[normalised]} (copy-pasted rationale)"
                )
            else:
                seen_notes[normalised] = test_id
            if len(normalised) <= MIN_DROPPED_NOTE_LENGTH:
                failures.append(
                    f"{test_id}: bucket={BUCKET_DROPPED} note is only {len(normalised)} "
                    f"char(s); a disposition needs a substantive reason"
                )
            lowered = note.lower()
            if not any(
                marker in note or marker in lowered for marker in DROPPED_RATIONALE_MARKERS
            ):
                failures.append(
                    f"{test_id}: bucket={BUCKET_DROPPED} note never states why the case "
                    "was dropped"
                )

    for entry in overrides:
        test_id = str(entry.get("test_id", "")).strip()
        declared_bucket = str(entry.get("bucket", "")).strip()
        row = by_test_id.get(test_id)
        if row is None:
            failures.append(
                f"summary case_overrides names {test_id} which is absent from {MIGRATION_CSV}"
            )
            continue
        actual_bucket = str(row.get("bucket", "")).strip()
        if declared_bucket != actual_bucket:
            failures.append(
                f"{test_id}: summary case_overrides says bucket={declared_bucket} but "
                f"the csv says bucket={actual_bucket}"
            )
        if declared_bucket == BUCKET_DROPPED and test_id in protected:
            failures.append(
                f"{test_id}: summary case_overrides agrees with a bucket={BUCKET_DROPPED} "
                "judgement for a MUST_NOT_BE_DROPPED case"
            )

    bucket_counts = Counter(str(row.get("bucket", "")).strip() for row in rows)
    bucket_counts_sorted = {bucket: bucket_counts[bucket] for bucket in sorted(bucket_counts)}
    for label, block in (
        ("summary basis.bucket_distribution", _dig(summary, "basis", "bucket_distribution")),
        ("summary buckets", summary.get("buckets")),
    ):
        if not isinstance(block, Mapping):
            continue
        declared = {str(key): value for key, value in block.items()}
        if declared != bucket_counts_sorted:
            failures.append(
                f"{label} = {_fmt_value(declared)} but the csv holds "
                f"{_fmt_value(bucket_counts_sorted)}"
            )
        else:
            notes.append(f"{label} = {_fmt_value(declared)} agrees with the csv")

    notes.append(f"bucket distribution from csv = {_fmt_value(bucket_counts_sorted)}")
    notes.append(
        f"bucket={BUCKET_DROPPED}: {len(dropped)} row(s), "
        f"{len(seen_notes)} distinct note(s); protected cases = {len(protected)}"
    )

    return DispositionVerdict(
        failures=tuple(failures),
        notes=tuple(notes),
        dropped_rows=len(dropped),
        protected_ids=tuple(sorted(protected)),
    )


def _disposition_check(
    artifacts: Artifacts, criteria: Mapping[str, Mapping[str, Any]]
) -> CheckResult:
    """C23 -- abandoned (bucket ③) dispositions must be individually auditable.

    Args:
        artifacts: Artifact accessor.
        criteria: Criteria indexed by id.

    Returns:
        Check id ``C23``.
    """
    verdict = analyse_disposition_auditability(artifacts)
    recomputed = "auditable" if not verdict.failures else f"inauditable({len(verdict.failures)} issue(s))"
    return _compare(
        _require_criterion(criteria, "C23"),
        "migration.disposition_auditability",
        recomputed,
        extra_failures=verdict.failures,
        extra_notes=verdict.notes,
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_checks(artifacts: Artifacts) -> GateReport:
    """Run all 24 checks against a contracts directory.

    Args:
        artifacts: Artifact accessor bound to the contracts directory.

    Returns:
        A populated :class:`GateReport`.

    Raises:
        ArtifactError: If a required artifact or criterion cannot be read.
    """
    criteria = artifacts.criteria()
    numbers = recompute_ddl(artifacts)

    checks: list[CheckResult] = []
    checks.extend(_openapi_checks(artifacts, criteria))          # C1  - C3
    checks.extend(_ddl_checks(artifacts, criteria, numbers))     # C4  - C8
    checks.append(_sqlite_check(artifacts, criteria, numbers))   # C9
    checks.extend(_sse_checks(artifacts, criteria))              # C10 - C11
    checks.append(_sse_golden_coverage_check(artifacts, criteria))  # C12
    checks.append(_errors_check(artifacts, criteria))            # C13
    checks.append(_envelope_check(artifacts, criteria))          # C14
    checks.append(_migration_check(artifacts, criteria))         # C15
    checks.append(_migration_passed_check(artifacts, criteria))  # C16
    checks.append(_toolkit_check(artifacts, criteria))           # C17
    checks.append(_ledgers_check(artifacts, criteria))            # C18
    checks.append(_conformance_check(artifacts, criteria))        # C19
    checks.append(_migration_digests_check(artifacts, criteria))  # C20
    checks.append(_ddl_object_total_check(artifacts, criteria))   # C21
    checks.append(_errors_uniformity_check(artifacts, criteria))  # C22
    checks.append(_disposition_check(artifacts, criteria))        # C23
    checks.append(_ddl_object_consistency_check(artifacts, numbers))  # S1

    header_notes: list[str] = []
    reconciled = [
        check.check_id
        for check in checks
        if any("status = reconciled" in note for note in check.notes)
    ]
    if reconciled:
        header_notes.append(
            f"{'/'.join(reconciled)} reconciled by the ledger (expected != measured): the gate "
            "compares against criteria[].measured, the figure the ledger publishes"
        )
    if len(checks) != EXPECTED_CHECK_COUNT:
        header_notes.append(
            f"coverage drift: {len(checks)} checks ran, {EXPECTED_CHECK_COUNT} expected"
        )

    return GateReport(
        contracts_dir=artifacts.contracts_dir,
        manifest_sha256=artifacts.manifest_digest(),
        checks=tuple(checks),
        header_notes=tuple(header_notes),
    )


# ---------------------------------------------------------------------------
# Self-test: replay every false-green QA reported, plus one per new criterion
# ---------------------------------------------------------------------------


def _write_json(path: Path, document: Any) -> str:
    """Serialise ``document`` to ``path`` and return the new file digest."""
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return sha256_file(path)


def _iter_artifact_files(contracts: Path) -> list[Path]:
    """List every artifact file under ``contracts`` except the sha256 ledger.

    Args:
        contracts: Contracts directory.

    Returns:
        Files sorted by POSIX relative path.
    """
    files = [
        path
        for path in contracts.rglob("*")
        if path.is_file() and path.name != MANIFEST_SHA
    ]
    return sorted(files, key=lambda path: path.relative_to(contracts).as_posix())


def _repin_all(contracts: Path) -> None:
    """Re-pin both ledgers exactly the way a careful tamperer would.

    Updates every ``objects[].sha256`` from disk, drops object rows whose file
    disappeared, rewrites ``contract-manifest.json`` and then rebuilds
    ``manifest.sha256`` (including the object ledger's own self-entry).

    Args:
        contracts: Contracts directory of the scratch copy (mutated in place).
    """
    manifest_path = contracts / MANIFEST_JSON
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    objects = manifest.get("objects")
    if isinstance(objects, list):
        synced: list[Any] = []
        for entry in objects:
            if not isinstance(entry, dict):
                continue
            target = contracts / str(entry.get("path", ""))
            if not target.is_file():
                continue
            entry["sha256"] = sha256_file(target)
            synced.append(entry)
        manifest["objects"] = synced
    _write_json(manifest_path, manifest)

    lines = [
        f"{sha256_file(path)}  {path.relative_to(contracts).as_posix()}"
        for path in _iter_artifact_files(contracts)
    ]
    (contracts / MANIFEST_SHA).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _rewrite_csv_rows(path: Path, transform: Callable[[dict[str, str]], dict[str, str]]) -> None:
    """Rewrite CSV data rows through a transform, keeping the comment banner.

    Args:
        path: CSV artifact to rewrite in place.
        transform: Callable receiving one header-keyed row and returning it
            (possibly mutated).
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    header: list[str] | None = None
    output: list[str] = []
    for line in lines:
        if line.lstrip().startswith("#") or not line.strip():
            output.append(line)
            continue
        record = next(csv.reader([line]))
        if header is None:
            header = record
            output.append(line)
            continue
        row = dict(zip(header, record))
        updated = transform(row)
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="")
        writer.writerow([updated.get(column, "") for column in header])
        output.append(buffer.getvalue())
    path.write_text("\n".join(output) + "\n", encoding="utf-8", newline="\n")


def _run_integrity_check(contracts: Path) -> tuple[int, str]:
    """Run ``run.py check`` against a directory in a subprocess.

    Args:
        contracts: Contracts directory to verify.

    Returns:
        ``(exit_code, combined_output)``; ``exit_code`` is ``-1`` when the
        extractor entry point cannot be located.
    """
    run_py = Path(__file__).resolve().parent / "extract-from-py" / "run.py"
    if not run_py.is_file():
        return -1, f"run.py not found at {run_py.as_posix()}"
    completed = subprocess.run(
        [sys.executable, str(run_py), "check", "--contracts-dir", str(contracts)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode, f"{completed.stdout or ''}{completed.stderr or ''}"


# --- mutations -------------------------------------------------------------
#
# Every mutator receives ``(contracts_clone, toolkit_clone)`` and edits the
# scratch copy only. Each one reproduces a defect that an integrity-only gate
# cannot see, i.e. the sha chain is re-pinned afterwards wherever possible.


def _mutate_ddl_statistics(contracts: Path, toolkit: Path) -> str:
    """D-3: edit ``counts`` only, then re-pin both ledgers."""
    document = json.loads((contracts / PG_SCHEMA).read_text(encoding="utf-8"))
    counts = document.get("counts")
    if not isinstance(counts, dict):
        raise ArtifactError(f"{PG_SCHEMA}: 'counts' block is missing")
    tables = ddl_tables(document)
    actual_metadata = count_metadata_indexes(tables)
    actual_total = actual_metadata + count_raw_indexes(document)
    counts["metadata_indexes"] = actual_metadata - 4
    counts["index_objects_total"] = actual_total - 4
    _write_json(contracts / PG_SCHEMA, document)
    _repin_all(contracts)
    return (
        f"{PG_SCHEMA} counts.metadata_indexes {actual_metadata} -> "
        f"{counts['metadata_indexes']}, counts.index_objects_total {actual_total} -> "
        f"{counts['index_objects_total']}"
    )


def _mutate_http_status_uniform(contracts: Path, toolkit: Path) -> str:
    """Defect D-1 resurrection: pretend ``DEPENDENCY_MISSING`` is uniform 503."""
    document = json.loads((contracts / ERRORS).read_text(encoding="utf-8"))
    codes = document.get("codes")
    if not isinstance(codes, dict) or "DEPENDENCY_MISSING" not in codes:
        raise ArtifactError(f"{ERRORS}: codes.DEPENDENCY_MISSING is missing")
    entry = codes["DEPENDENCY_MISSING"]
    entry["http_status_uniform"] = True
    _write_json(contracts / ERRORS, document)
    _repin_all(contracts)
    return (
        f"{ERRORS} codes.DEPENDENCY_MISSING.http_status_uniform false -> true "
        "(2 of its 10 call sites still answer 500), both ledgers re-pinned"
    )


def _mutate_bucket_flip(contracts: Path, toolkit: Path) -> str:
    """Defect D-2 resurrection: file the protected fail-closed case as bucket ③."""
    protected_id = PROTECTED_TEST_IDS[0]
    flipped: list[str] = []

    def transform(row: dict[str, str]) -> dict[str, str]:
        if row.get("test_id") == protected_id:
            flipped.append(f"{row.get('bucket')} -> {BUCKET_DROPPED}")
            row["bucket"] = BUCKET_DROPPED
        return row

    _rewrite_csv_rows(contracts / MIGRATION_CSV, transform)
    if not flipped:
        raise ArtifactError(f"{MIGRATION_CSV}: protected test id not found")
    _repin_all(contracts)
    return (
        f"{MIGRATION_CSV} {protected_id.rsplit('::', 1)[-1]} bucket "
        f"{flipped[0]}, both ledgers re-pinned"
    )


def _mutate_drop_golden(contracts: Path, toolkit: Path) -> str:
    """C12: a channel loses its ``golden`` reference."""
    document = json.loads((contracts / SSE_CHANNELS).read_text(encoding="utf-8"))
    channels = document.get("channels")
    if not isinstance(channels, list) or not channels:
        raise ArtifactError(f"{SSE_CHANNELS}: 'channels' is missing or empty")
    victim = channels[0]
    removed = victim.pop("golden", None)
    victim.pop("golden_sha256", None)
    _write_json(contracts / SSE_CHANNELS, document)
    _repin_all(contracts)
    return f"{SSE_CHANNELS} channel {victim.get('channel')} lost golden={removed}"


def _mutate_envelope_shell(contracts: Path, toolkit: Path) -> str:
    """C14: one shell stops requiring ``request_id``."""
    document = json.loads((contracts / ENVELOPE).read_text(encoding="utf-8"))
    defs = document.get("$defs")
    if not isinstance(defs, dict) or "errorEnvelope" not in defs:
        raise ArtifactError(f"{ENVELOPE}: $defs.errorEnvelope is missing")
    required = defs["errorEnvelope"].get("required")
    if not isinstance(required, list) or "request_id" not in required:
        raise ArtifactError(f"{ENVELOPE}: errorEnvelope.required lacks request_id")
    required.remove("request_id")
    _write_json(contracts / ENVELOPE, document)
    _repin_all(contracts)
    return f"{ENVELOPE} $defs.errorEnvelope.required drops 'request_id'"


def _mutate_migration_outcome(contracts: Path, toolkit: Path) -> str:
    """C16: one ``passed`` case is re-labelled ``skipped``."""
    flipped: list[str] = []

    def transform(row: dict[str, str]) -> dict[str, str]:
        if not flipped and row.get("outcome") == "passed":
            flipped.append(row.get("test_id", ""))
            row["outcome"] = "skipped"
        return row

    _rewrite_csv_rows(contracts / MIGRATION_CSV, transform)
    if not flipped:
        raise ArtifactError(f"{MIGRATION_CSV}: no 'passed' row found")
    _repin_all(contracts)
    return f"{MIGRATION_CSV} outcome passed -> skipped for {flipped[0].rsplit('::', 1)[-1]}"


def _mutate_missing_toolkit(contracts: Path, toolkit: Path) -> str:
    """C17: a toolkit module disappears (contracts/ no longer reproducible)."""
    victim = toolkit / "hashes.py"
    if not victim.is_file():
        raise ArtifactError(f"toolkit clone has no {victim.name}")
    victim.unlink()
    return f"toolkit module {victim.name} deleted from the scratch toolkit"


def _mutate_ledger_line(contracts: Path, toolkit: Path) -> str:
    """C18: ``manifest.sha256`` stops listing one artifact it still holds."""
    ledger = contracts / MANIFEST_SHA
    victim = "db/type-map.csv"
    lines: list[str] = []
    removed = False
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if line.partition("  ")[2].strip() == victim:
            removed = True
            continue
        lines.append(line)
    if not removed:
        raise ArtifactError(f"{MANIFEST_SHA} has no entry for {victim}")
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return f"{MANIFEST_SHA} entry for {victim} deleted (object ledger untouched)"


def _mutate_drop_conformance(contracts: Path, toolkit: Path) -> str:
    """C19: a conformance skeleton is deleted and the ledgers are re-pinned."""
    victim = contracts / CONFORMANCE_DIR / "tenant-404.yaml"
    if not victim.is_file():
        raise ArtifactError(f"conformance skeleton not found: {victim.as_posix()}")
    victim.unlink()
    _repin_all(contracts)
    return f"{CONFORMANCE_DIR}/{victim.name} deleted, both ledgers re-pinned"


def _mutate_summary_digest(contracts: Path, toolkit: Path) -> str:
    """C20: the migration summary lies about an artifact digest."""
    path = contracts / MIGRATION_SUMMARY
    document = json.loads(path.read_text(encoding="utf-8"))
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ArtifactError(f"{MIGRATION_SUMMARY}: 'artifacts' is missing or empty")
    victim = "conformance/idempotency.yaml"
    if victim not in artifacts:
        victim = sorted(artifacts)[0]
    original = artifacts[victim]
    artifacts[victim] = "0" * 64
    _write_json(path, document)
    _repin_all(contracts)
    return (
        f"{MIGRATION_SUMMARY} artifacts[{victim}] {str(original)[:12]} -> "
        "000000000000, both ledgers re-pinned"
    )


@dataclass(frozen=True)
class Scenario:
    """One self-test scenario: a mutation plus the checks that must catch it."""

    key: str
    description: str
    mutator: Callable[[Path, Path], str] | None
    expected_red: tuple[str, ...] = ()
    expect_integrity_green: bool = True
    extra_notes: tuple[str, ...] = field(default=())


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="baseline",
        description="untouched clone passes the gate and run.py check",
        mutator=None,
        expected_red=(),
        expect_integrity_green=True,
    ),
    Scenario(
        key="d3-ddl-counts",
        description="D-3: edited counts.* with both ledgers re-pinned",
        mutator=_mutate_ddl_statistics,
        expected_red=("C6", "C8"),
    ),
    Scenario(
        key="d1-uniform-status",
        description="D-1: http_status_uniform true while 500/503 still coexist",
        mutator=_mutate_http_status_uniform,
        expected_red=("C22",),
    ),
    Scenario(
        key="d2-bucket-flip",
        description="D-2: protected fail-closed case filed as bucket 3",
        mutator=_mutate_bucket_flip,
        expected_red=("C23",),
    ),
    Scenario(
        key="c12-golden-hole",
        description="C12: a channel loses its golden frame reference",
        mutator=_mutate_drop_golden,
        expected_red=("C12",),
    ),
    Scenario(
        key="c14-shell-key",
        description="C14: errorEnvelope stops requiring request_id",
        mutator=_mutate_envelope_shell,
        expected_red=("C14",),
    ),
    Scenario(
        key="c16-passed-count",
        description="C16: a passed case is re-labelled skipped",
        mutator=_mutate_migration_outcome,
        expected_red=("C16",),
    ),
    Scenario(
        key="c17-toolkit-gone",
        description="C17: hashes.py removed from the toolkit",
        mutator=_mutate_missing_toolkit,
        expected_red=("C17",),
    ),
    Scenario(
        key="c18-ledger-hole",
        description="C18: manifest.sha256 stops listing a recorded artifact",
        mutator=_mutate_ledger_line,
        expected_red=("C18",),
        expect_integrity_green=False,
        extra_notes=(
            "the fault class C18 covers is also visible to run.py check (physical "
            "ledger mismatch); the gate keeps it as an explicit criteria-level rule",
        ),
    ),
    Scenario(
        key="c19-conformance-gone",
        description="C19: a conformance skeleton deleted, ledgers re-pinned",
        mutator=_mutate_drop_conformance,
        expected_red=("C19",),
    ),
    Scenario(
        key="c20-summary-digest",
        description="C20: the migration summary lies about an artifact digest",
        mutator=_mutate_summary_digest,
        expected_red=("C20",),
    ),
)


def _prepare_scratch(
    contracts_dir: Path, toolkit_dir: Path, root: Path, key: str
) -> tuple[Path, Path]:
    """Clone ``contracts/`` and the required toolkit modules into a scratch dir.

    Args:
        contracts_dir: Source contracts directory (never modified).
        toolkit_dir: Source toolkit directory (never modified).
        root: Scratch root for this self-test run.
        key: Scenario key, used as the scratch sub-directory name.

    Returns:
        ``(contracts_clone, toolkit_clone)``.
    """
    scenario_root = root / key
    scenario_root.mkdir(parents=True, exist_ok=True)
    clone = scenario_root / "contracts"
    shutil.copytree(contracts_dir, clone)
    toolkit_clone = scenario_root / "toolkit"
    toolkit_clone.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_TOOLKIT:
        source = toolkit_dir / name
        if source.is_file():
            shutil.copy2(source, toolkit_clone / name)
    return clone, toolkit_clone


def cmd_self_test(contracts_dir: Path, verbose: bool = False) -> int:
    """Replay every known false-green and assert this gate catches each one.

    For every scenario the expectations are:

    1. the listed checks turn red (and nothing may turn red when the list is
       empty);
    2. ``run.py check`` still exits 0 -- proving the mutation is invisible to the
       integrity gate (except ``c18-ledger-hole``, where the fault class is
       physical and ``check`` is expected to be red too).

    Args:
        contracts_dir: Source contracts directory (never modified).
        verbose: Emit the full check lines for every scenario.

    Returns:
        ``EXIT_OK`` when every expectation holds, ``EXIT_SELF_TEST_FAILED``
        otherwise.
    """
    if not contracts_dir.is_dir():
        sys.stderr.write(f"[semantic] ERROR: contracts directory not found: {contracts_dir.as_posix()}\n")
        return EXIT_LOAD_ERROR

    toolkit_dir = default_toolkit_dir()
    expectations: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory(prefix="wbtime-semantic-gate-") as temporary:
        root = Path(temporary)
        print(f"[self-test] source : {contracts_dir.as_posix()}")
        print(f"[self-test] toolkit: {toolkit_dir.as_posix()}")
        print(f"[self-test] scratch: {root.as_posix()}")
        print(f"[self-test] scenarios: {len(SCENARIOS)}")

        for scenario in SCENARIOS:
            print(f"[self-test] --- {scenario.key}: {scenario.description}")
            try:
                clone, toolkit_clone = _prepare_scratch(contracts_dir, toolkit_dir, root, scenario.key)
            except OSError as error:
                sys.stderr.write(f"[self-test] ERROR: cannot prepare scratch: {error}\n")
                return EXIT_SELF_TEST_FAILED

            detail = "no mutation"
            if scenario.mutator is not None:
                try:
                    detail = scenario.mutator(clone, toolkit_clone)
                except (ArtifactError, json.JSONDecodeError, KeyError, TypeError, OSError) as error:
                    sys.stderr.write(f"[self-test] ERROR: mutation failed: {error}\n")
                    return EXIT_SELF_TEST_FAILED
            print(f"[self-test]   mutation: {detail}")

            integrity_code, integrity_output = _run_integrity_check(clone)
            first_lines = [line for line in integrity_output.splitlines() if line.strip()][:2]
            print(f"[self-test]   run.py check -> exit {integrity_code}")
            for line in first_lines:
                print(f"[self-test]   {line}")

            try:
                report = run_checks(Artifacts(clone, toolkit_dir=toolkit_clone))
            except ArtifactError as error:
                sys.stderr.write(f"[self-test] ERROR: gate could not evaluate clone: {error}\n")
                return EXIT_SELF_TEST_FAILED

            print(report.render(verbose=verbose))
            red = report.mismatched_ids
            print(f"[self-test]   gate red on: {red if red else '(none)'}")
            for note in scenario.extra_notes:
                print(f"[self-test]   note: {note}")

            if scenario.expected_red:
                missing = [identifier for identifier in scenario.expected_red if identifier not in red]
                expectations.append(
                    (
                        f"{scenario.key}: gate flags {', '.join(scenario.expected_red)}",
                        not missing,
                        f"missing={missing}" if missing else f"red={red}",
                    )
                )
            else:
                expectations.append(
                    (
                        f"{scenario.key}: gate stays green",
                        report.ok,
                        "" if report.ok else f"unexpected red={red}",
                    )
                )

            if scenario.expect_integrity_green:
                expectations.append(
                    (
                        f"{scenario.key}: run.py check stays green (integrity-only gate)",
                        integrity_code == 0,
                        f"exit={integrity_code}",
                    )
                )
            else:
                expectations.append(
                    (
                        f"{scenario.key}: run.py check may be red (physical ledger fault)",
                        True,
                        f"exit={integrity_code}",
                    )
                )

    print("[self-test] expectations")
    ok = True
    for description, passed, detail in expectations:
        suffix = f"  ({detail})" if detail else ""
        print(f"[self-test]   {'PASS' if passed else 'FAIL'}  {description}{suffix}")
        ok = ok and passed
    print(f"[self-test] RESULT: {'PASS' if ok else 'FAIL'}")
    return EXIT_OK if ok else EXIT_SELF_TEST_FAILED


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Semantic gate for contracts/: recompute every headline number from the "
            "artifacts, re-decide the C22/C23 regression gates from their evidence "
            "rows, and compare all of it with contract-manifest.json criteria[]."
        ),
    )
    parser.add_argument(
        "--contracts",
        metavar="PATH",
        default=None,
        help="contracts directory (default: <repo>/contracts)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="also print the informative notes of successful checks",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="emit a machine readable report instead of the text report",
    )
    parser.add_argument(
        "--self-test",
        dest="self_test",
        action="store_true",
        help=(
            "clone contracts/ into a temp dir, replay the D-1/D-2/D-3 false greens "
            "plus one mutation per newly covered criterion, and assert this gate "
            "turns red while run.py check stays green"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (0 ok, 2 mismatch, 3 unreadable, 4 self-test failed).
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    contracts = Path(args.contracts).resolve() if args.contracts else default_contracts_dir()

    if args.self_test:
        return cmd_self_test(contracts, verbose=bool(args.verbose))

    try:
        report = run_checks(Artifacts(contracts))
    except ArtifactError as error:
        sys.stderr.write(f"[semantic] ERROR: {error}\n")
        return EXIT_LOAD_ERROR

    if args.as_json:
        sys.stdout.write(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(report.render(verbose=bool(args.verbose)) + "\n")
    sys.stdout.flush()

    return EXIT_OK if report.ok else EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
