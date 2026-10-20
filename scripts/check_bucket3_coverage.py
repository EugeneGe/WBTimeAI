#!/usr/bin/env python3
"""DoD#6 — bucket-③ coverage gate (every abandoned case has a registered replacement).

Background
----------
``contracts/test-migration-map.csv`` classifies every legacy pytest case into
bucket ①(333) / ②(1363) / ③(3), where ③ means **abandoned or merged**.  The CSV is
frozen and must not be edited to make anything look better, so the replacement-gate
mapping lives in a separate, human-written ledger:
``docs/V1.0/V0.0.2-…/03-台账/桶③替代门禁登记.json`` (user ruling D-6).

This gate makes "bucket ③ is 100% covered" a checkable fact instead of a claim.
It verifies, **in both directions**:

CSV -> registry
    every ``bucket=3`` row has exactly one registry entry (missing ⇒ red);
registry -> CSV
    every registry entry names a case that really exists **and** really is
    ``bucket=3`` (dangling ⇒ red, wrong bucket ⇒ red);
gate_id resolvable
    every registered ``gate_id`` resolves to a real artifact:
    ``C<n>`` in ``contract-manifest.json#criteria[].id`` /
    ``conformance/*.yaml`` / a frozen JSON-Schema file under ``contracts/``;
semantic partition
    every ``asserted_semantics[].id`` is **exactly one of** "covered by some
    ``relation=covers`` gate" or "listed in ``uncovered_semantic_ids``".  This is
    what stops "登记了就算": a semantic claim can never be silently dropped, and a
    ``veto`` gate can never be laundered into coverage.

What this gate deliberately does **not** do
-------------------------------------------
It cannot judge whether a gate *really* covers the semantic it claims to — that is
QA's line-by-line review, which D-6 explicitly refuses to replace with registration.
What the gate does guarantee is that no semantic can be ignored, and that the
``enforcement`` flag (``live`` vs ``declared-skeleton``) is present and in
vocabulary, so nobody can quietly present a skeleton invariant as a live gate.

Exit codes (§3.3)
-----------------
``0`` / ``1`` / ``2`` (usage or load failure) / ``9`` (``--self-test`` failed).

Python: standard library only.
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from _gate_io import (
    EXIT_OK,
    EXIT_SELFTEST,
    EXIT_USAGE,
    EXIT_VIOLATION,
    Diff,
    GateIOError,
    GatePaths,
    load_json,
    load_text,
    log,
)

__all__ = [
    "TAG",
    "EXPECTED_BUCKET3",
    "BUCKET3_TARGET",
    "REGISTRY_RELATIVE",
    "BucketRow",
    "Registry",
    "main",
]

#: Log tag (K-7).
TAG = "bucket3"

#: The frozen CSV, relative to ``contracts/``.
MIGRATION_MAP = "test-migration-map.csv"

#: The contract manifest (source of the ``C1``–``C23`` criterion ids).
CONTRACT_MANIFEST = "contract-manifest.json"

#: The human-written replacement-gate ledger, relative to the repository root.
REGISTRY_RELATIVE = (
    "docs/V1.0/V0.0.2-oracle自证与假绿反例/03-台账/桶③替代门禁登记.json"
)

#: Bucket value this gate is about.
BUCKET3_TARGET = "3"

#: How many ``bucket=3`` rows the frozen CSV must contain.  Confirmed by T01
#: (``1:333 / 2:1363 / 3:3``).  Pinned so a silent CSV edit cannot shrink the
#: denominator — an empty or shrunken bucket ③ would make coverage vacuously true
#: (K-11).
EXPECTED_BUCKET3 = 3

#: Allowed ``relation`` values for one gate reference.
RELATIONS: frozenset[str] = frozenset({"covers", "veto"})

#: Allowed ``enforcement`` values for one gate reference.
ENFORCEMENTS: frozenset[str] = frozenset({"live", "declared-skeleton"})

#: Allowed ``gate_kind`` values, and the shape each one must have.
GATE_KINDS: dict[str, str] = {
    "criterion": r"^C\d+$",
    "conformance": r"^conformance/[A-Za-z0-9._-]+\.yaml$",
    "schema": r"^[A-Za-z0-9._-]+\.(?:json|yaml|yml)$",
}

#: Fields every registry entry must carry, with the reason they matter.
REQUIRED_ENTRY_FIELDS: tuple[tuple[str, str], ...] = (
    ("test_id", "the CSV row this entry belongs to"),
    ("why_bucket3", "why the case was abandoned — D-6 rejects 'registered therefore covered'"),
    ("asserted_semantics", "what the case actually asserts, one claim per id"),
    ("alternative_gates", "which gate replaces which claim"),
    ("uncovered_semantic_ids", "what nothing replaces, stated out loud"),
    ("residual_risk", "what must be rebuilt in a later version"),
    ("qa_checklist", "what QA must verify by hand"),
)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BucketRow:
    """One row of the frozen migration map.

    Attributes:
        test_id: ``"<file>::<test>"`` identity.
        bucket: ``"1"`` / ``"2"`` / ``"3"``.
        file: Source test file path.
        outcome: Recorded pytest outcome.
        target_module: Target npm package.
        target_version: Target version.
    """

    test_id: str
    bucket: str
    file: str
    outcome: str
    target_module: str
    target_version: str


@dataclass
class Registry:
    """The parsed replacement-gate ledger.

    Attributes:
        document: The raw decoded JSON (kept for diagnostics).
        entries: The entry list, as-is.
        declared_bucket3: What the ledger claims the bucket-③ count is.
        path: Where the ledger was read from.
    """

    document: dict[str, Any] = field(default_factory=dict)
    entries: list[dict[str, Any]] = field(default_factory=list)
    declared_bucket3: int | None = None
    path: Path | None = None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_migration_map(csv_path: Path) -> list[BucketRow]:
    """Read the frozen migration map.

    Comment lines (first non-blank character ``#``) are dropped, exactly as
    ``contracts/endpoints.txt`` documents for its own format.

    Args:
        csv_path: Path to ``test-migration-map.csv``.

    Returns:
        Every row, in file order.

    Raises:
        GateIOError: The file is missing or has no parsable rows / columns.
    """
    text = load_text(csv_path)
    kept = [
        line
        for line in text.splitlines()
        if not (line.strip() and line.lstrip().startswith("#"))
    ]
    if not kept:
        raise GateIOError(f"{csv_path.as_posix()} has no non-comment lines")
    reader = csv.DictReader(io.StringIO("\n".join(kept)))
    if reader.fieldnames is None:
        raise GateIOError(f"{csv_path.as_posix()} has no header row")
    missing = {"test_id", "bucket"} - {name.strip() for name in reader.fieldnames}
    if missing:
        raise GateIOError(
            f"{csv_path.as_posix()} is missing column(s) {sorted(missing)} "
            f"(found {reader.fieldnames})"
        )
    rows: list[BucketRow] = []
    for raw in reader:
        test_id = (raw.get("test_id") or "").strip()
        if not test_id:
            continue
        rows.append(
            BucketRow(
                test_id=test_id,
                bucket=(raw.get("bucket") or "").strip(),
                file=(raw.get("file") or "").strip(),
                outcome=(raw.get("outcome") or "").strip(),
                target_module=(raw.get("target_module") or "").strip(),
                target_version=(raw.get("target_version") or "").strip(),
            )
        )
    return rows


def load_registry(registry_path: Path) -> Registry:
    """Read the replacement-gate ledger.

    Args:
        registry_path: Path to the registry JSON.

    Returns:
        The parsed registry.

    Raises:
        GateIOError: The file is missing, is not a JSON object, or has no
            ``entries`` array.
    """
    document = load_json(registry_path)
    if not isinstance(document, dict):
        raise GateIOError(f"{registry_path.as_posix()} is not a JSON object")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise GateIOError(f"{registry_path.as_posix()} has no 'entries' array")
    declared = document.get("csv_frozen_bucket3_count")
    return Registry(
        document=document,
        entries=[entry for entry in entries if isinstance(entry, dict)],
        declared_bucket3=declared if isinstance(declared, int) else None,
        path=registry_path,
    )


def load_criteria(contracts_dir: Path) -> dict[str, dict[str, Any]]:
    """Read the ``criteria`` block of ``contract-manifest.json``.

    Args:
        contracts_dir: The ``contracts/`` directory.

    Returns:
        Criterion id -> criterion record.

    Raises:
        GateIOError: The manifest is missing or has no usable ``criteria`` array.
    """
    document = load_json(contracts_dir / CONTRACT_MANIFEST)
    if not isinstance(document, dict):
        raise GateIOError(f"{CONTRACT_MANIFEST} is not a JSON object")
    criteria = document.get("criteria")
    if not isinstance(criteria, list):
        raise GateIOError(f"{CONTRACT_MANIFEST} has no 'criteria' array")
    return {
        str(item["id"]): item
        for item in criteria
        if isinstance(item, dict) and item.get("id")
    }


# ---------------------------------------------------------------------------
# Gate-id resolution
# ---------------------------------------------------------------------------
def resolve_gate(
    gate: Mapping[str, Any], contracts_dir: Path, criteria: Mapping[str, Any]
) -> tuple[bool, str]:
    """Resolve one ``alternative_gates[]`` record to a real artifact.

    Args:
        gate: The gate record from the registry.
        contracts_dir: The ``contracts/`` directory.
        criteria: Criterion id -> record, from the contract manifest.

    Returns:
        ``(resolved, detail)``.  ``detail`` always explains the verdict, so a
        failing run prints a reason rather than a bare "red".
    """
    gate_id = str(gate.get("gate_id") or "").strip()
    gate_kind = str(gate.get("gate_kind") or "").strip()
    if not gate_id:
        return False, "empty gate_id"
    if gate_kind not in GATE_KINDS:
        return False, f"unknown gate_kind {gate_kind!r} (known: {sorted(GATE_KINDS)})"
    if not re.match(GATE_KINDS[gate_kind], gate_id):
        return False, f"gate_id {gate_id!r} does not have the {gate_kind!r} shape"

    if gate_kind == "criterion":
        if gate_id not in criteria:
            return False, f"criterion {gate_id} is not in {CONTRACT_MANIFEST}#criteria"
        return True, f"criterion {gate_id} (status={criteria[gate_id].get('status')})"

    target = contracts_dir / Path(*gate_id.split("/"))
    if not target.is_file():
        return False, f"{gate_id} does not exist under contracts/"
    return True, f"{gate_kind} {gate_id}"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check(
    *,
    rows: Sequence[BucketRow],
    registry: Registry,
    criteria: Mapping[str, Any],
    contracts_dir: Path,
) -> list[Diff]:
    """Run every structural check and return the violations.

    Args:
        rows: Every row of the frozen migration map.
        registry: The parsed replacement-gate ledger.
        criteria: Criterion id -> record.
        contracts_dir: The ``contracts/`` directory.

    Returns:
        Sorted diffs; empty means the registry is complete and resolvable.
    """
    diffs: list[Diff] = []

    by_id: dict[str, BucketRow] = {}
    for row in rows:
        by_id.setdefault(row.test_id, row)
    bucket3 = [row for row in rows if row.bucket == BUCKET3_TARGET]

    # K-11 — an empty bucket ③ must never be a pass.
    if not bucket3:
        diffs.append(
            Diff(
                kind="invalid-empty",
                subject="contracts/test-migration-map.csv#bucket3",
                left=f"expected {EXPECTED_BUCKET3} rows",
                right="0 rows -> INVALID (K-11: an empty set is never a pass)",
            )
        )
    elif len(bucket3) != EXPECTED_BUCKET3:
        diffs.append(
            Diff(
                kind="count",
                subject="contracts/test-migration-map.csv#bucket3",
                left=str(EXPECTED_BUCKET3),
                right=str(len(bucket3)),
            )
        )

    if not registry.entries:
        diffs.append(
            Diff(
                kind="invalid-empty",
                subject="registry#entries",
                left="non-empty",
                right="empty -> INVALID (K-11)",
            )
        )

    if registry.declared_bucket3 is not None and registry.declared_bucket3 != len(bucket3):
        diffs.append(
            Diff(
                kind="count",
                subject="registry#csv_frozen_bucket3_count",
                left=str(registry.declared_bucket3),
                right=str(len(bucket3)),
            )
        )

    registered: dict[str, int] = {}
    for entry in registry.entries:
        test_id = str(entry.get("test_id") or "").strip()
        if not test_id:
            diffs.append(
                Diff(
                    kind="malformed-entry",
                    subject="registry#entries",
                    left="test_id expected",
                    right="absent",
                )
            )
            continue
        registered[test_id] = registered.get(test_id, 0) + 1

        # --- registry -> CSV -------------------------------------------------
        row = by_id.get(test_id)
        if row is None:
            diffs.append(
                Diff(
                    kind="dangling-test-id",
                    subject=test_id,
                    left="registry entry",
                    right="not present in test-migration-map.csv",
                )
            )
        elif row.bucket != BUCKET3_TARGET:
            diffs.append(
                Diff(
                    kind="wrong-bucket",
                    subject=test_id,
                    left=f"bucket={BUCKET3_TARGET}",
                    right=f"bucket={row.bucket}",
                )
            )

        # --- required fields -------------------------------------------------
        for name, why in REQUIRED_ENTRY_FIELDS:
            value = entry.get(name)
            if value is None or (isinstance(value, (str, list)) and not value):
                diffs.append(
                    Diff(
                        kind="missing-field",
                        subject=f"{test_id}#{name}",
                        left="required",
                        right=f"absent ({why})",
                    )
                )

        diffs.extend(
            _check_entry_semantics(
                entry, test_id=test_id, contracts_dir=contracts_dir, criteria=criteria
            )
        )

    # --- CSV -> registry -----------------------------------------------------
    for row in bucket3:
        occurrences = registered.get(row.test_id, 0)
        if occurrences == 0:
            diffs.append(
                Diff(
                    kind="unregistered",
                    subject=row.test_id,
                    left="bucket=3 (CSV)",
                    right="no registry entry",
                )
            )
        elif occurrences > 1:
            diffs.append(
                Diff(
                    kind="duplicate-registration",
                    subject=row.test_id,
                    left="1 entry",
                    right=f"{occurrences} entries",
                )
            )

    return sorted(diffs, key=lambda diff: (diff.kind, diff.subject))


def _check_entry_semantics(
    entry: Mapping[str, Any],
    *,
    test_id: str,
    contracts_dir: Path,
    criteria: Mapping[str, Any],
) -> list[Diff]:
    """Check one entry's semantic partition and gate resolvability.

    Args:
        entry: One registry entry.
        test_id: Its ``test_id`` (for diff subjects).
        contracts_dir: The ``contracts/`` directory.
        criteria: Criterion id -> record.

    Returns:
        Diffs for this entry.
    """
    diffs: list[Diff] = []

    semantics = entry.get("asserted_semantics")
    semantic_ids: list[str] = []
    if isinstance(semantics, list):
        for item in semantics:
            if isinstance(item, Mapping) and item.get("id") and item.get("text"):
                semantic_ids.append(str(item["id"]))
            else:
                diffs.append(
                    Diff(
                        kind="malformed-semantic",
                        subject=test_id,
                        left="asserted_semantics[] entries need id + text",
                        right=json.dumps(item, ensure_ascii=False)[:120],
                    )
                )
    known = set(semantic_ids)

    covered: set[str] = set()
    gates = entry.get("alternative_gates")
    covering_gates = 0
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, Mapping):
                diffs.append(
                    Diff(
                        kind="malformed-gate",
                        subject=test_id,
                        left="alternative_gates[] entries must be objects",
                        right=json.dumps(gate, ensure_ascii=False)[:120],
                    )
                )
                continue
            resolved, detail = resolve_gate(gate, contracts_dir, criteria)
            if not resolved:
                diffs.append(
                    Diff(
                        kind="unresolvable-gate",
                        subject=f"{test_id}#{gate.get('gate_id') or '<empty>'}",
                        left="resolvable",
                        right=detail,
                    )
                )
            relation = str(gate.get("relation") or "").strip()
            enforcement = str(gate.get("enforcement") or "").strip()
            if relation not in RELATIONS:
                diffs.append(
                    Diff(
                        kind="bad-relation",
                        subject=f"{test_id}#{gate.get('gate_id')}",
                        left=f"one of {sorted(RELATIONS)}",
                        right=relation or "absent",
                    )
                )
            if enforcement not in ENFORCEMENTS:
                diffs.append(
                    Diff(
                        kind="bad-enforcement",
                        subject=f"{test_id}#{gate.get('gate_id')}",
                        left=f"one of {sorted(ENFORCEMENTS)}",
                        right=enforcement or "absent",
                    )
                )
            if not str(gate.get("rationale") or "").strip():
                diffs.append(
                    Diff(
                        kind="missing-rationale",
                        subject=f"{test_id}#{gate.get('gate_id')}",
                        left="rationale required (D-6: 'registered therefore covered' is rejected)",
                        right="absent",
                    )
                )
            listed = gate.get("semantic_ids")
            listed_ids = (
                [str(item) for item in listed] if isinstance(listed, list) else []
            )
            if not listed_ids:
                diffs.append(
                    Diff(
                        kind="missing-semantic-ids",
                        subject=f"{test_id}#{gate.get('gate_id')}",
                        left="at least one semantic id",
                        right="absent",
                    )
                )
            for semantic_id in listed_ids:
                if semantic_id not in known:
                    diffs.append(
                        Diff(
                            kind="unknown-semantic",
                            subject=f"{test_id}#{gate.get('gate_id')}",
                            left=f"semantic {semantic_id}",
                            right="not declared in asserted_semantics",
                        )
                    )
            if relation == "covers":
                covering_gates += 1
                covered.update(listed_ids)

    if covering_gates == 0:
        diffs.append(
            Diff(
                kind="no-covering-gate",
                subject=test_id,
                left=">=1 gate with relation=covers",
                right="none (veto-only registration is not coverage)",
            )
        )

    uncovered_raw = entry.get("uncovered_semantic_ids")
    uncovered = (
        {str(item) for item in uncovered_raw} if isinstance(uncovered_raw, list) else set()
    )
    for semantic_id in sorted(uncovered - known):
        diffs.append(
            Diff(
                kind="unknown-semantic",
                subject=f"{test_id}#uncovered",
                left=f"semantic {semantic_id}",
                right="not declared in asserted_semantics",
            )
        )

    # The partition rule: covered XOR uncovered, for every declared semantic.
    for semantic_id in semantic_ids:
        is_covered = semantic_id in covered
        is_uncovered = semantic_id in uncovered
        if is_covered and is_uncovered:
            diffs.append(
                Diff(
                    kind="semantic-partition",
                    subject=f"{test_id}#{semantic_id}",
                    left="covered by a relation=covers gate",
                    right="also listed in uncovered_semantic_ids",
                )
            )
        elif not is_covered and not is_uncovered:
            diffs.append(
                Diff(
                    kind="semantic-partition",
                    subject=f"{test_id}#{semantic_id}",
                    left="covered",
                    right="not covered and not declared uncovered (silently dropped)",
                )
            )
    return diffs


# ---------------------------------------------------------------------------
# Gate entry point
# ---------------------------------------------------------------------------
def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments without the program name.

    Returns:
        The parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="check_bucket3_coverage.py",
        description=(
            "DoD#6: every bucket-3 migration case has a registered replacement gate, "
            "bidirectionally, with resolvable gate ids and a complete semantic partition."
        ),
    )
    parser.add_argument(
        "--contracts",
        default=None,
        metavar="DIR",
        help="contracts directory (default: <repo>/contracts)",
    )
    parser.add_argument(
        "--registry",
        default=None,
        metavar="PATH",
        help=f"replacement-gate ledger (default: <repo>/{REGISTRY_RELATIVE})",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the named injections on a temporary registry copy (exit 9 on failure)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the diffs as a JSON array",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _registry_path(arguments: argparse.Namespace, paths: GatePaths) -> Path:
    """Resolve the ledger path.

    Args:
        arguments: Parsed arguments.
        paths: Resolved gate paths.

    Returns:
        The absolute ledger path.
    """
    if arguments.registry:
        return Path(arguments.registry).expanduser().resolve()
    return paths.repo_root / Path(*REGISTRY_RELATIVE.split("/"))


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name.

    Returns:
        ``0`` the registry is complete and resolvable, ``1`` violation,
        ``2`` usage or load failure, ``9`` ``--self-test`` failed.
    """
    try:
        arguments = _parse_arguments(argv)
    except SystemExit as exit_error:  # argparse already printed the message
        return EXIT_USAGE if exit_error.code else EXIT_OK

    paths = GatePaths.resolve(contracts_dir=arguments.contracts)
    registry_path = _registry_path(arguments, paths)

    if arguments.self_test:
        return _self_test(
            csv_path=paths.contract_file(MIGRATION_MAP),
            registry_path=registry_path,
            paths=paths,
        )

    log(TAG, f"csv      : {(paths.contracts_dir / MIGRATION_MAP).as_posix()}")
    log(TAG, f"registry : {registry_path.as_posix()}")

    try:
        rows = load_migration_map(paths.contract_file(MIGRATION_MAP))
        registry = load_registry(registry_path)
        criteria = load_criteria(paths.contracts_dir)
    except GateIOError as error:
        log(TAG, f"ERROR: cannot load inputs: {error}")
        return EXIT_USAGE

    log(
        TAG,
        f"csv rows: total={len(rows)} bucket1={_count(rows, '1')} "
        f"bucket2={_count(rows, '2')} bucket3={_count(rows, '3')}",
    )
    log(
        TAG,
        f"registry entries: {len(registry.entries)} "
        f"(declared bucket3 count: {registry.declared_bucket3})",
    )

    for entry in registry.entries:
        test_id = str(entry.get("test_id") or "<missing>")
        gates = entry.get("alternative_gates") or []
        labels = [
            f"{gate.get('gate_id')}[{gate.get('relation')}/{gate.get('enforcement')}]"
            for gate in gates
            if isinstance(gate, Mapping)
        ]
        log(TAG, f"  {test_id} -> {', '.join(labels) or '<no gates>'}")

    diffs = check(
        rows=rows,
        registry=registry,
        criteria=criteria,
        contracts_dir=paths.contracts_dir,
    )
    if arguments.json:
        print(json.dumps([diff.to_dict() for diff in diffs], ensure_ascii=False, indent=2))

    if diffs:
        for diff in diffs:
            log(TAG, f"DIFF {diff.render()}")
        log(TAG, f"VERDICT: FAIL ({len(diffs)} violation(s))")
        return EXIT_VIOLATION

    covering = sum(
        1
        for entry in registry.entries
        for gate in entry.get("alternative_gates") or []
        if isinstance(gate, Mapping) and gate.get("relation") == "covers"
    )
    log(
        TAG,
        f"VERDICT: PASS ({_count(rows, '3')}/{EXPECTED_BUCKET3} bucket-3 rows registered; "
        f"{covering} covering gate ref(s); no dangling id in either direction)",
    )
    return EXIT_OK


def _count(rows: Iterable[BucketRow], bucket: str) -> int:
    """Count rows in one bucket.

    Args:
        rows: The migration-map rows.
        bucket: The bucket value.

    Returns:
        The number of matching rows.
    """
    return sum(1 for row in rows if row.bucket == bucket)


# ---------------------------------------------------------------------------
# --self-test
# ---------------------------------------------------------------------------
def _expect(
    *, label: str, diffs: Sequence[Diff], must_contain_kind: str, must_name: str | None = None
) -> bool:
    """Assert a tampered registry goes red for the expected reason.

    Args:
        label: Injection label, for output.
        diffs: Diffs produced on the tampered registry.
        must_contain_kind: The diff kind that must appear.
        must_name: A subject fragment that must appear on a diff of that kind.

    Returns:
        ``True`` when the specific expected red reason is present.
    """
    hits = [diff for diff in diffs if diff.kind == must_contain_kind]
    if must_name is not None:
        hits = [diff for diff in hits if must_name in diff.subject]
    if not hits:
        log(
            TAG,
            f"SELFTEST FAIL [{label}]: expected a '{must_contain_kind}' diff"
            + (f" naming {must_name}" if must_name else "")
            + f"; got {[(diff.kind, diff.subject) for diff in diffs][:6]}",
        )
        return False
    log(TAG, f"SELFTEST OK [{label}]: red on {hits[0].render()}")
    return True


def _run_checks(
    *, rows: Sequence[BucketRow], document: dict[str, Any], paths: GatePaths
) -> list[Diff]:
    """Run :func:`check` against an in-memory registry document.

    Args:
        rows: Migration-map rows.
        document: The (possibly tampered) registry document.
        paths: Resolved gate paths.

    Returns:
        The violations.

    Raises:
        GateIOError: The manifest cannot be loaded.
    """
    entries = document.get("entries")
    registry = Registry(
        document=document,
        entries=[entry for entry in entries if isinstance(entry, dict)]
        if isinstance(entries, list)
        else [],
        declared_bucket3=(
            document.get("csv_frozen_bucket3_count")
            if isinstance(document.get("csv_frozen_bucket3_count"), int)
            else None
        ),
    )
    criteria = load_criteria(paths.contracts_dir)
    return check(
        rows=rows,
        registry=registry,
        criteria=criteria,
        contracts_dir=paths.contracts_dir,
    )


def _self_test(*, csv_path: Path, registry_path: Path, paths: GatePaths) -> int:
    """Run the named injections on an in-memory copy of the registry.

    Three assertions:

    1. the untouched registry is green (otherwise "red" proves nothing);
    2. deleting one registration **must** go red with an ``unregistered`` diff
       naming that exact case (the DoD#6 counterexample);
    3. pointing one ``gate_id`` at a criterion that does not exist **must** go red
       with an ``unresolvable-gate`` diff — otherwise the resolver could be a
       stub that always says yes.

    Args:
        csv_path: The frozen migration map.
        registry_path: The real ledger.
        paths: Resolved gate paths (the ledger's gate ids resolve against these).

    Returns:
        ``0`` when every assertion holds, ``9`` otherwise.
    """
    log(TAG, f"self-test: csv={(csv_path).as_posix()} registry={registry_path.as_posix()}")
    failures = 0

    try:
        rows = load_migration_map(csv_path)
        document = json.loads(load_text(registry_path))
    except (GateIOError, json.JSONDecodeError) as error:
        log(TAG, f"SELFTEST FAIL: cannot load inputs: {error}")
        return EXIT_SELFTEST

    if not isinstance(document, dict):
        log(TAG, "SELFTEST FAIL: the registry is not a JSON object")
        return EXIT_SELFTEST
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        log(TAG, "SELFTEST FAIL: the registry has no entries to tamper with")
        return EXIT_SELFTEST

    # Step 1 — baseline.
    baseline_diffs = _run_checks(rows=rows, document=document, paths=paths)
    if baseline_diffs:
        log(
            TAG,
            f"SELFTEST FAIL [baseline]: the untouched registry is already red "
            f"({len(baseline_diffs)} diffs)",
        )
        for diff in baseline_diffs[:5]:
            log(TAG, f"  {diff.render()}")
        failures += 1
    else:
        log(
            TAG,
            f"SELFTEST OK [baseline]: untouched registry is green "
            f"({len(entries)} entries)",
        )

    # Step 2 — delete one registration.
    tampered = copy.deepcopy(document)
    removed = tampered["entries"].pop(0)
    victim = str(removed.get("test_id") or "<unknown>")
    log(TAG, f"self-test injection 1: deleted the registration for {victim}")
    diffs = _run_checks(rows=rows, document=tampered, paths=paths)
    if not _expect(
        label="inject-1 registration deleted",
        diffs=diffs,
        must_contain_kind="unregistered",
        must_name=victim,
    ):
        failures += 1

    # Step 3 — an unresolvable gate id must be caught.
    tampered = copy.deepcopy(document)
    first_entry = tampered["entries"][0]
    gates = first_entry.get("alternative_gates")
    if isinstance(gates, list) and gates and isinstance(gates[0], dict):
        original = gates[0].get("gate_id")
        gates[0]["gate_kind"] = "criterion"
        gates[0]["gate_id"] = "C999"
        log(
            TAG,
            f"self-test injection 2: rewrote gate_id {original!r} -> 'C999' "
            f"on {first_entry.get('test_id')}",
        )
        diffs = _run_checks(rows=rows, document=tampered, paths=paths)
        if not _expect(
            label="inject-2 unresolvable gate id",
            diffs=diffs,
            must_contain_kind="unresolvable-gate",
            must_name="C999",
        ):
            failures += 1
    else:
        log("bucket3", "SELFTEST FAIL: the first entry has no gate to rewrite")
        failures += 1

    if failures:
        log(TAG, f"SELFTEST VERDICT: FAIL ({failures} assertion(s) did not hold)")
        return EXIT_SELFTEST
    log(TAG, "SELFTEST VERDICT: PASS (both injections go red on the expected reason)")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
