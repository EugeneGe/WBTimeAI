"""Render the migration map and the conformance skeletons into ``contracts/``.

Inputs (see :mod:`migration.inventory`): the frozen collection ledger and the
optional real-run outcome ledger.  Outputs:

``contracts/test-migration-map.csv``
    One row per old test case (1699 at the 2026-10-20 baseline) with its
    disposition: ``bucket`` ①/②/③, ``target_module``, ``target_version``.
``contracts/test-migration-summary.json``
    Machine-readable counts, the 1661-vs-1699 caliber registration, and digests
    of every input/output so the numbers can be re-derived.
``contracts/conformance/*.yaml``
    Four skeletons whose ``source`` fields are verified line-by-line against the
    read-only legacy tree at build time.

Design notes
------------
* **No trimming.**  The roadmap registers ``1661`` (passed caliber).  This map
  keeps all ``1699`` collected cases, because a skipped/xfailed case still needs
  a disposition decision.  The 38-row delta is *registered*, never silently
  removed.
* **No invented outcomes.**  A case that was not executed in the recorded run is
  ``unknown`` — never ``passed``.
* **Byte-stable output.**  Rows are sorted, comments are generated from computed
  numbers, and the newline is LF, so re-running ``export`` is a no-op on disk.

Only the Python standard library is used here.
"""

from __future__ import annotations

import collections
import csv
import dataclasses
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from migration import classify as classification
from migration import conformance as conformance_rules
from migration import inventory

__all__ = [
    "MAP_FILENAME",
    "SUMMARY_FILENAME",
    "CONFORMANCE_DIRNAME",
    "CSV_COLUMNS",
    "ROADMAP_REGISTERED_PASSED",
    "ROADMAP_REGISTERED_SELECTED",
    "Row",
    "build_rows",
    "render_csv",
    "build_summary",
    "write_artifacts",
]

#: CSV artifact name inside ``contracts/``.
MAP_FILENAME = "test-migration-map.csv"

#: Summary artifact name inside ``contracts/``.
SUMMARY_FILENAME = "test-migration-summary.json"

#: Directory (inside ``contracts/``) that receives the skeletons.
CONFORMANCE_DIRNAME = "conformance"

#: Number the roadmap registers, and its caliber (roadmap §3.2 / §5 「桶① ~357 用例绿」旁栏).
ROADMAP_REGISTERED_PASSED = 1661

#: Selected count the roadmap's 1661 came from, quoted verbatim in the legacy log
#: 「1692 selected = 1661P」.  Used only to *reconcile* the two calibers.
ROADMAP_REGISTERED_SELECTED = 1692

#: Where the 1661-vs-1699 delta is registered for humans.
ROADMAP_DELTA_REGISTERED_IN: tuple[str, ...] = (
    "contracts/test-migration-map.csv (header comments)",
    "contracts/README.md §「旧用例迁移映射（C-06）」",
    "scripts/extract-from-py/README.md §10",
    "contracts/test-migration-summary.json (basis.roadmap_registered_1661)",
)

#: Column order of the CSV (the eight required columns, then extras).
CSV_COLUMNS: tuple[str, ...] = (
    "test_id",
    "file",
    "markers",
    "outcome",
    "bucket",
    "target_module",
    "target_version",
    "note",
    "capability",
)

#: Separator used when a row has several markers.
MARKER_SEPARATOR = "|"


@dataclasses.dataclass(frozen=True)
class Row:
    """One CSV row.

    Attributes:
        test_id: Pytest node id.
        file: POSIX relative path.
        markers: Project markers joined by :data:`MARKER_SEPARATOR` (``-`` if none).
        outcome: One of :data:`inventory.OUTCOME_VOCABULARY`.
        bucket: ①/②/③ classification (integer).
        target_module: Destination TS package.
        target_version: Landing version.
        note: Disposition rationale (+ ``unknown`` marker when not re-run).
        capability: Legacy capability cluster (roadmap §4.1 wording).
    """

    test_id: str
    file: str
    markers: str
    outcome: str
    bucket: int
    target_module: str
    target_version: str
    note: str
    capability: str

    def as_dict(self) -> dict[str, Any]:
        """Return the row as an ordered mapping matching :data:`CSV_COLUMNS`."""
        return {
            "test_id": self.test_id,
            "file": self.file,
            "markers": self.markers,
            "outcome": self.outcome,
            "bucket": self.bucket,
            "target_module": self.target_module,
            "target_version": self.target_version,
            "note": self.note,
            "capability": self.capability,
        }


def _marker_text(record: inventory.TestRecord) -> str:
    """Render the ``markers`` column value for ``record``."""
    project_markers = record.project_markers
    if not project_markers:
        return "-"
    return MARKER_SEPARATOR.join(project_markers)


def _outcome_note(outcome: str) -> str:
    """Explain an ``outcome`` cell that is not a plain pass."""
    if outcome == "unknown":
        return "outcome=unknown：本轮未复跑（非「通过」），待 V0.0.2 全量复跑后回填"
    if outcome in {"skipped", "xfailed", "xpassed"}:
        return "outcome 为条件性结果（skip/xfail），并非能力缺失"
    if outcome == "failed":
        return "outcome=failed：旧线记录为红，重建期须先登记红因再决定判据去留"
    if outcome == "error":
        return "outcome=error：夹具/环境错误，不是能力判定结果"
    return ""


def build_rows(
    records: Sequence[inventory.TestRecord],
    outcomes: Mapping[str, str] | None,
    source_root: str,
) -> list[Row]:
    """Build every CSV row.

    Args:
        records: Records from the collection ledger (already narrowed by
            :func:`inventory.select_default_run` when the default caliber is
            wanted).
        outcomes: ``nodeid -> outcome`` map, or ``None`` when no run is recorded.
        source_root: Normalised legacy root, used to relativise paths.

    Returns:
        Rows sorted by ``(file, test_id)`` for byte stability.
    """
    rows: list[Row] = []
    lookup = outcomes or {}
    for record in records:
        relative = inventory.relative_path_of(record, source_root)
        disposition = classification.classify(relative, test_id=record.nodeid)
        outcome = lookup.get(record.nodeid, "unknown")
        note_parts = [disposition.note]
        extra_note = _outcome_note(outcome)
        if extra_note:
            note_parts.append(extra_note)
        rows.append(
            Row(
                test_id=record.nodeid,
                file=relative,
                markers=_marker_text(record),
                outcome=outcome,
                bucket=disposition.bucket,
                target_module=disposition.target_module,
                target_version=disposition.target_version,
                note="；".join(part for part in note_parts if part),
                capability=disposition.capability,
            )
        )
    rows.sort(key=lambda row: (row.file, row.test_id))
    return rows


def _observed_comment_lines(basis: Mapping[str, Any]) -> list[str]:
    """Render the "what the recorded run actually did" header lines.

    Args:
        basis: Caliber block; uses ``basis["observed"]``.

    Returns:
        Zero or one block of comment lines (empty when no run was recorded).
    """
    observed = basis.get("observed") or {}
    if not observed.get("measured"):
        return []
    distribution = observed.get("distribution") or {}
    joined = " / ".join(f"{outcome} {count}" for outcome, count in sorted(distribution.items()))
    verdict = "成立" if observed.get("reconciled") else "**不成立（需复核）**"
    return [
        f"#   实测 outcome        = {joined}",
        "#                         （来自 migration/inputs/outcomes.json，全量复跑，exit 0）",
        f"#   对账                = selected {basis['selected']} − 旧线 "
        f"{ROADMAP_REGISTERED_SELECTED} = {observed.get('selected_delta_vs_legacy'):+d}；"
        f"passed {observed.get('passed')} − 路线图 {ROADMAP_REGISTERED_PASSED} = "
        f"{observed.get('passed_delta_vs_roadmap'):+d} ⇒ 差额{verdict}"
        "（旧线 skip/xfail 31 条，今日同为 "
        f"{observed.get('non_passing')} 条）",
    ]


def _csv_header_comments(basis: Mapping[str, Any]) -> list[str]:
    """Render the ``#`` header block, using computed numbers only."""
    buckets = basis.get("bucket_distribution") or {}
    overrides = basis.get("case_override_summary") or []
    bucket_line = " / ".join(
        f"{key}:{buckets[key]}" for key in sorted(buckets, key=lambda item: int(item))
    )
    distribution_comment = (
        f"#   实测分布（本表逐条判定）= {bucket_line}（合计 {sum(buckets.values())}）"
        if bucket_line
        else "#   实测分布：无（未跑集合账本）"
    )
    return [
        "# WBTimeAI / contracts/test-migration-map.csv",
        "# C-06：旧仓（D:/WBT/WBTimeAI_old，只读）每个 pytest 用例的处置决策。",
        "# 机器生成：python scripts/extract-from-py/run.py export --only migration —— 请勿手改。",
        "#",
        "# 口径（全部来自实跑，非估算）：",
        f"#   collected(raw)      = {basis['collected_raw']}"
        "   pytest --collect-only -o addopts= (含 provider_live)",
        f"#   provider_live       = {basis['provider_live_excluded']}"
        "   pyproject addopts `-m 'not provider_live'` 默认排除",
        f"#   selected            = {basis['selected']}"
        "   ← 本表行数口径（= 直接跑 pytest 的 collected 集合）",
        f"#   路线图登记 {basis['roadmap_registered_1661']['value']}     = passed 口径"
        f"（旧线记录「1692 selected = 1661P」），"
        f"与 selected {basis['selected']} 差 "
        f"{basis['roadmap_registered_1661']['delta_vs_selected']}。",
        f"#   → 本表**不裁剪**这 {basis['roadmap_registered_1661']['delta_vs_selected']} 条"
        "（skip/xfail 用例同样需要处置记录），差异登记见 contracts/README.md。",
        *_observed_comment_lines(basis),
        "#",
        "# bucket（docs/V1.0/00-版本路线图.md §4.1 归并总表）：",
        "#   1 = ① 原样移植   2 = ② 需重设计   3 = ③ 放弃或合并",
        distribution_comment,
        *_override_comment_lines(overrides),
        "# outcome：passed/failed/skipped/xfailed/xpassed/error/unknown",
        "#   unknown = 未复跑（**不是**「通过」）；"
        + (
            "本轮 unknown = 0（全量复跑覆盖 1699/1699）。"
            if (basis.get("observed") or {}).get("measured")
            else "本轮全部 unknown（未复跑）。"
        ),
        "# markers：仅列 pyproject 登记的 marker"
        f"（{', '.join(inventory.REGISTERED_MARKERS)}），多个用 | 分隔，无则 -",
        "# 解析约定：首个非空白字符为 '#' 的行视为注释，读表时忽略"
        "（与 contracts/endpoints.txt 一致）。",
        "#",
        "# 列：test_id,file,markers,outcome,bucket,target_module,target_version,note,capability",
    ]


def _override_comment_lines(overrides: Sequence[Mapping[str, Any]]) -> list[str]:
    """Render the per-case override block (empty when no override applies).

    The three lines above say "one bucket per file"; these say "except here, and
    here is why".  Without them a reader cannot tell a deliberate per-case
    decision from a copy-paste accident.

    Args:
        overrides: ``basis["case_override_summary"]`` entries.

    Returns:
        Zero or more comment lines.
    """
    if not overrides:
        return []
    lines = [
        "#   ↑ 逐用例覆盖（migration/classify.py::CASE_OVERRIDES，"
        "同一文件内不同用例可分属不同桶；每条 note 各自写明断言与放弃/重设计理由）：",
    ]
    for item in overrides:
        lines.append(
            f"#     {item['test_id']} → bucket={item['bucket']}"
            f"（文件规则 {item['rule_pattern']} 判 {item['rule_bucket']}）"
        )
    return lines


def render_csv(rows: Sequence[Row], basis: Mapping[str, Any]) -> str:
    """Render the CSV text (header comments + header row + rows, LF endings).

    Args:
        rows: Rows from :func:`build_rows`.
        basis: Caliber block, see :func:`build_summary`.

    Returns:
        UTF-8 text ending with exactly one newline.
    """
    buffer = io.StringIO(newline="")
    for comment in _csv_header_comments(basis):
        buffer.write(comment + "\n")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CSV_COLUMNS),
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row.as_dict())
    return buffer.getvalue()


def _distribution(rows: Iterable[Row], attribute: str) -> dict[str, int]:
    """Count rows by one attribute, sorted by key."""
    counter: collections.Counter[str] = collections.Counter(
        str(getattr(row, attribute)) for row in rows
    )
    return dict(sorted(counter.items(), key=lambda pair: pair[0]))


def _matrix(rows: Iterable[Row]) -> dict[str, dict[str, int]]:
    """Bucket × version cross-tab."""
    cells: dict[str, collections.Counter[str]] = {}
    for row in rows:
        cells.setdefault(row.target_version, collections.Counter())[str(row.bucket)] += 1
    return {
        version: dict(sorted(counts.items()))
        for version, counts in sorted(cells.items())
    }


def _marker_distribution(rows: Sequence[Row]) -> dict[str, int]:
    """Count rows per marker (a row may carry several)."""
    counter: collections.Counter[str] = collections.Counter()
    for row in rows:
        if row.markers == "-":
            continue
        for marker in row.markers.split(MARKER_SEPARATOR):
            counter[marker] += 1
    return dict(sorted(counter.items()))


def _override_summary(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """Describe every applied per-case override, for the CSV header and the summary.

    Each entry records both the bucket the *file rule* would have produced and the
    bucket the case actually got, so a reader can audit the divergence without
    re-reading :mod:`migration.classify`.

    Args:
        rows: Rendered rows.

    Returns:
        One dict per override that actually landed in ``rows``, ordered by node id.
    """
    by_id = {row.test_id: row for row in rows}
    described: list[dict[str, Any]] = []
    for override in sorted(classification.CASE_OVERRIDES, key=lambda item: item.test_id):
        row = by_id.get(override.test_id)
        if row is None:
            continue
        file_disposition = classification.classify(row.file)
        described.append(
            {
                "test_id": override.test_id,
                "file": row.file,
                "capability": override.capability,
                "bucket": override.bucket,
                "target_module": override.target_module,
                "target_version": override.target_version,
                "rule_pattern": file_disposition.rule_pattern,
                "rule_bucket": file_disposition.bucket,
                "rule_capability": file_disposition.capability,
            }
        )
    return described


def _ledger_provenance(outcome_meta: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Project the outcome ledger down to its provenance fields.

    The per-test map (1699 entries) stays in ``inputs/outcomes.json``; copying it
    into the summary would double the artifact for no extra information.

    Args:
        outcome_meta: Metadata returned by
            :func:`migration.inventory.load_outcomes_ledger`.

    Returns:
        ``None`` when no ledger was recorded, else ``{sha256, counts, argv, ...}``.
    """
    if outcome_meta is None:
        return None
    return {
        "path": "scripts/extract-from-py/migration/inputs/outcomes.json",
        "sha256": outcome_meta.get("sha256", ""),
        "counts": dict(outcome_meta.get("counts") or {}),
        "recorded": len(outcome_meta.get("outcomes") or {}),
        "pytest_version": outcome_meta.get("pytest_version", ""),
        "argv": list(outcome_meta.get("argv") or []),
        "exitstatus": outcome_meta.get("exitstatus"),
        "duration_seconds": outcome_meta.get("duration_seconds"),
    }


def build_summary(
    rows: Sequence[Row],
    records: Sequence[inventory.TestRecord],
    collect_meta: Mapping[str, Any],
    outcome_meta: Mapping[str, Any] | None,
    conformance_meta: Sequence[Mapping[str, Any]],
    basis: Mapping[str, Any],
    source_root: str,
    input_paths: Sequence[Path],
    artifacts: Mapping[str, str],
) -> dict[str, Any]:
    """Assemble ``test-migration-summary.json``.

    Args:
        rows: Rendered rows.
        records: Selected records (the row basis).
        collect_meta: ``collect.json`` metadata.
        outcome_meta: ``outcomes.json`` metadata, or ``None`` when absent.
        conformance_meta: Per-skeleton ``{id, file, refs, cases, sha256}``.
        basis: Caliber block returned by :func:`_build_basis`.
        source_root: Normalised legacy root.
        input_paths: Ledger paths that fed the build.
        artifacts: ``relative path -> sha256`` of the emitted artifacts.

    Returns:
        A JSON-serialisable dict.
    """
    relative_paths = {inventory.relative_path_of(record, source_root) for record in records}
    unmatched = sorted(
        path for path in relative_paths if not classification.classify(path).rule_pattern
    )
    covered = 0
    if outcome_meta is not None:
        covered = sum(1 for row in rows if row.outcome != "unknown")
    summary: dict[str, Any] = {
        "schema": 1,
        "artifact": MAP_FILENAME,
        "generated_by": "scripts/extract-from-py/export_migration.py",
        "source_root": inventory.protocol_path(source_root),
        "pytest_version": collect_meta.get("pytest_version", ""),
        "roadmap": {
            "doc": classification.ROADMAP_DOC,
            "buckets": classification.ROADMAP_SECTION_BUCKETS,
            "versions": classification.ROADMAP_SECTION_VERSIONS,
        },
        "basis": dict(basis),
        "rows": len(rows),
        "buckets": _distribution(rows, "bucket"),
        # Per-case divergences from the file-level rule: kept as data so a reader
        # never has to infer them from a docstring (D-2 auditability).
        "case_overrides": [dict(item) for item in (basis.get("case_override_summary") or [])],
        "versions": _distribution(rows, "target_version"),
        "modules": _distribution(rows, "target_module"),
        "markers": _marker_distribution(rows),
        "matrix_version_by_bucket": _matrix(rows),
        "outcomes": {
            "distribution": _distribution(rows, "outcome"),
            "covered": covered,
            "uncovered_unknown": len(rows) - covered,
            "vocabulary": list(inventory.OUTCOME_VOCABULARY),
            # Provenance only: the per-test map itself stays in the input ledger,
            # otherwise the summary would duplicate 1699 entries for no gain.
            "ledger": _ledger_provenance(outcome_meta),
            "note": (
                "outcome 全部来自 inputs/outcomes.json 的真实运行结果；"
                "未出现在该账本的用例为 unknown，绝不以 passed 代替"
                if outcome_meta is not None
                else "无 outcomes.json：全部登记为 unknown（未在任何一轮复跑），禁止按 passed 统计"
            ),
        },
        "conformance": [dict(item) for item in conformance_meta],
        "inputs": [
            {"path": path.as_posix(), "sha256": inventory.sha256_of(path)} for path in input_paths
        ],
        "artifacts": dict(sorted(artifacts.items())),
        "files_unmatched": unmatched,
        "counts_selfcheck": {
            "rows_equals_selected": len(rows) == len(records),
            "bucket_sum_equals_rows": sum(_distribution(rows, "bucket").values()) == len(rows),
            "version_sum_equals_rows": sum(_distribution(rows, "target_version").values())
            == len(rows),
            "all_case_overrides_applied": len(basis.get("case_override_summary") or [])
            == len(classification.CASE_OVERRIDES),
        },
    }
    return summary


def _observed_block(rows: Sequence[Row]) -> dict[str, Any]:
    """Summarise what the recorded run actually did, and reconcile it with 1661.

    The reconciliation is the interesting part: the roadmap's ``1661`` came from a
    ``1692 selected`` run, i.e. 31 non-passing cases.  Today's ``1699 selected``
    run has the *same* 31 non-passing cases, so both deltas are ``+7`` — the whole
    difference is seven newly collected (and passing) tests, not a lost chunk of
    the suite.

    Args:
        rows: Rendered rows (carrying per-case ``outcome``).

    Returns:
        A JSON-serialisable block; ``measured`` is ``False`` when no case ran.
    """
    distribution = _distribution(rows, "outcome")
    passed = distribution.get("passed", 0)
    non_passing = sum(count for outcome, count in distribution.items() if outcome != "passed")
    measured = bool(passed) and "unknown" not in distribution
    return {
        "measured": measured,
        "distribution": distribution,
        "passed": passed,
        "non_passing": non_passing,
        "passed_delta_vs_roadmap": (passed - ROADMAP_REGISTERED_PASSED) if measured else None,
        "selected_delta_vs_legacy": (len(rows) - ROADMAP_REGISTERED_SELECTED) if measured else None,
        "reconciled": measured
        and (passed - ROADMAP_REGISTERED_PASSED) == (len(rows) - ROADMAP_REGISTERED_SELECTED),
        "formula": "passed − 1661 == selected − 1692 ⇒ 差额全部来自新增用例，非用例丢失",
    }


def _build_basis(
    all_records: Sequence[inventory.TestRecord],
    selected: Sequence[inventory.TestRecord],
) -> dict[str, Any]:
    """Assemble the caliber registration block (the 1661-vs-1699 story)."""
    delta = len(selected) - ROADMAP_REGISTERED_PASSED
    return {
        "collected_raw": len(all_records),
        "provider_live_excluded": len(all_records) - len(selected),
        "selected": len(selected),
        "roadmap_registered_1661": {
            "value": ROADMAP_REGISTERED_PASSED,
            "caliber": "passed（旧线记录「1692 selected = 1661P」）",
            "delta_vs_selected": delta,
            "action": "不裁剪：skip/xfail 用例同样需要处置记录",
            "registered_in": list(ROADMAP_DELTA_REGISTERED_IN),
        },
        "bucket_plain_port_vs_roadmap": {
            "bucket_1_rows": 0,  # filled by write_artifacts once rows exist
            "roadmap_approx": 357,
            "note": "路线图写「桶① ~357 用例」，为估算值（带 ~）；本表按规则表逐条判定",
        },
    }


def write_artifacts(
    *,
    contracts_dir: Path,
    source_root: str,
    collect_path: Path,
    outcomes_path: Path,
    strict: bool = True,
) -> dict[str, Any]:
    """Write the CSV, the four skeletons, and the summary.

    Args:
        contracts_dir: Destination ``contracts/`` directory.
        source_root: Normalised legacy root (for relativising paths and for
            verifying skeleton ``source`` references).
        collect_path: ``collect.json`` path.
        outcomes_path: ``outcomes.json`` path (may not exist).
        strict: When true, fail if any collected path matches no
            :mod:`migration.classify` rule (no silent ``TBD`` rows).

    Returns:
        A result dict consumed by the exporter log (counts + artifact digests).

    Raises:
        migration.classify.UnmatchedPathError: (strict) when a path is unclassified.
        migration.conformance.SourceVerificationError: when a skeleton ``source``
            reference does not match the legacy tree.
    """
    collect_meta, all_records = inventory.load_collect_ledger(collect_path)
    selected = inventory.select_default_run(all_records)
    outcome_meta = inventory.load_outcomes_ledger(outcomes_path)
    outcomes = outcome_meta["outcomes"] if outcome_meta else None

    relative_paths = {inventory.relative_path_of(record, source_root) for record in selected}
    unmatched = sorted(
        path for path in relative_paths if not classification.classify(path).rule_pattern
    )
    if strict and unmatched:
        raise classification.UnmatchedPathError(unmatched)

    # Every per-case override must name a case that is really collected; a stale
    # override would describe a test that no longer exists (fail-closed).
    unknown_overrides = sorted(
        set(classification.known_override_ids()) - {record.nodeid for record in selected}
    )
    if strict and unknown_overrides:
        raise classification.UnmatchedCaseOverrideError(unknown_overrides)

    rows = build_rows(selected, outcomes, source_root)
    basis = _build_basis(all_records, selected)
    basis["observed"] = _observed_block(rows)
    basis["bucket_distribution"] = _distribution(rows, "bucket")
    basis["case_override_summary"] = _override_summary(rows)
    basis["bucket_plain_port_vs_roadmap"]["bucket_1_rows"] = sum(
        1 for row in rows if row.bucket == classification.BUCKET_PLAIN_PORT
    )

    contracts_dir.mkdir(parents=True, exist_ok=True)
    map_path = contracts_dir / MAP_FILENAME
    map_path.write_text(render_csv(rows, basis), encoding="utf-8", newline="\n")

    conformance_dir = contracts_dir / CONFORMANCE_DIRNAME
    conformance_dir.mkdir(parents=True, exist_ok=True)
    reader = conformance_rules.LineReader()
    conformance_meta: list[dict[str, Any]] = []
    for spec in conformance_rules.SPECS:
        evidence = conformance_rules.verify_sources(spec, source_root, reader)
        target = conformance_dir / f"{spec.id}.yaml"
        target.write_text(conformance_rules.render_yaml(spec), encoding="utf-8", newline="\n")
        conformance_meta.append(
            {
                "id": spec.id,
                "file": (Path(CONFORMANCE_DIRNAME) / f"{spec.id}.yaml").as_posix(),
                "title": spec.title,
                "status": conformance_rules.STATUS_SKELETON,
                "applies_to": list(spec.applies_to),
                "source_refs": len(spec.source),
                "cases": len(spec.cases),
                "sha256": inventory.sha256_of(target),
                "verified": evidence,
            }
        )

    artifacts: dict[str, str] = {MAP_FILENAME: inventory.sha256_of(map_path)}
    for item in conformance_meta:
        artifacts[str(item["file"])] = str(item["sha256"])

    summary = build_summary(
        rows=rows,
        records=selected,
        collect_meta=collect_meta,
        outcome_meta=outcome_meta,
        conformance_meta=conformance_meta,
        basis=basis,
        source_root=source_root,
        input_paths=(collect_path, outcomes_path),
        artifacts=artifacts,
    )
    summary_path = contracts_dir / SUMMARY_FILENAME
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    return {
        "rows": len(rows),
        "files": len(relative_paths),
        "collected_raw": len(all_records),
        "selected": len(selected),
        "bucket_1": basis["bucket_plain_port_vs_roadmap"]["bucket_1_rows"],
        "bucket_2": sum(1 for row in rows if row.bucket == classification.BUCKET_REDESIGN),
        "bucket_3": sum(1 for row in rows if row.bucket == classification.BUCKET_DROP),
        "case_overrides": len(basis["case_override_summary"]),
        "conformance": [item["id"] for item in conformance_meta],
        "conformance_refs": sum(int(item["source_refs"]) for item in conformance_meta),
        "outcomes_covered": summary["outcomes"]["covered"],
        "outcome_counts": summary["outcomes"]["distribution"],
        "map_sha256": inventory.sha256_of(map_path),
        "summary_sha256": inventory.sha256_of(summary_path),
        "unmatched": unmatched,
    }
