"""外部 oracle 重算与比对门禁（V0.0.2 · T03；N-2 关闭证据）。

设计依据：施工 ``README.md`` §1.3（三档 oracle）/ §3.3（退出码）/ §5-T03。

本脚本**只做编排**：把「外部真值」（``oracle/legacy_scan.py`` 的 ``LegacyFacts``，或
O-C 快照）与 ``contracts/`` 的四个面做**集合级**比对，最后**强制**打印覆盖率行。

做 / 不做：

* 做：F1 paths / operations、F2 ddl（表 / 列 / 索引名 / raw hnsw）、F3 SSE 通道、F4 错误码；
* 不做：任何「内部自洽」重算（那是 ``verify_semantics.py``）——重复实现等于给判据多开
  一个可被削弱的入口（施工 §10.8 的同一条纪律）。

退出码（施工 §3.3）：:

    0   与外部 oracle 一致（**仅** O-A 档可达）
    20  与外部 oracle 不一致（差异行点名具体对象）
    21  oracle 不可得（O-C 降级档 / 无 ``_old`` / 快照缺失或不可读 / BLOCKED）
    22  产物装载失败（``contracts/`` 缺失、空集合、结构不符）
    2   用法错误
    9   ``--self-test`` 失败

命令行：:

    python -B scripts/oracle_recompute.py --oracle legacy
    python -B scripts/oracle_recompute.py --oracle legacy --write-snapshot
    python -B scripts/oracle_recompute.py --oracle snapshot --legacy-root /nonexistent
    python -B scripts/oracle_recompute.py --assert-independent
    python -B scripts/oracle_recompute.py --self-test
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Sequence

sys.dont_write_bytecode = True

_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - depends on invocation style
    sys.path.insert(0, str(_SCRIPTS_DIR))

import _gate_io  # noqa: E402  (唯一共享层；含退出码 / Diff / log)
from oracle import snapshot as snapshot_module  # noqa: E402
from oracle.legacy_scan import (  # noqa: E402
    LegacyFacts,
    LegacyOracle,
    OracleUnavailable,
    ReadonlyViolation,
)

#: 四个 oracle 面（覆盖率行的分母口径，施工 §1.3）。
ORACLE_FACES: Final[tuple[str, ...]] = ("F1", "F2", "F3", "F4")

#: 内部自洽判据数量（23 条 ``C*`` 减去 4 个外部可重算面）。
INTERNAL_ONLY_CRITERIA: Final[int] = 19

#: 合同产物文件名（装载失败的报错要能点名）。
OPENAPI_ARTIFACT: Final[str] = "openapi.v1.frozen.json"
DDL_ARTIFACT: Final[str] = "schema.v0018.pg.normalized.json"
SSE_ARTIFACT: Final[str] = "sse/channels.json"
ERRORS_ARTIFACT: Final[str] = "errors.json"

#: 期望的 schema 版本（迁移 head）。不一致只登记，不擅自改判。
EXPECTED_SCHEMA_VERSION: Final[str] = "v0018"

#: hnsw 硬断言条数（施工 §5-T02 / §1.3）。
EXPECTED_HNSW_COUNT: Final[int] = 2

#: 每个面最多打印多少条差异行（其余折叠计数）。
MAX_DIFF_LINES: Final[int] = 20

#: 最多打印多少条 note 行（迁移解析会产生重复的同类 note）。
MAX_NOTE_LINES: Final[int] = 8


def _dedupe(values: Sequence[str]) -> list[str]:
    """Deduplicate strings while preserving order (notes repeat per loop item).

    Args:
        values: Raw note strings.

    Returns:
        Ordered unique strings.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


class ContractLoadError(RuntimeError):
    """Raised when ``contracts/`` artifacts cannot be loaded or are vacuous."""


# ---------------------------------------------------------------------------
# 期望侧：contracts/ 的四个面
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactStore:
    """The expected side: the four faces read out of ``contracts/``.

    Attributes:
        contracts_dir: Directory the artifacts came from (a clone during ATK-2).
        openapi_paths: ``openapi.v1.frozen.json`` path keys.
        openapi_operations: ``"METHOD /path"`` strings.
        ddl_tables: ``schema.v0018.pg.normalized.json`` table names.
        ddl_columns: ``(table, column)`` pairs.
        ddl_indexes: metadata index names (``tables[].indexes[].name``).
        ddl_raw_indexes: raw index names (``raw_indexes[].name``).
        ddl_hnsw_names: raw index names whose ``method`` is ``hnsw``.
        ddl_index_objects_total: declared ``counts.index_objects_total``.
        sse_channels: ``sse/channels.json#by_channel`` values.
        error_codes: ``errors.json#codes`` keys.
        schema_version: declared ``schema_version`` (audit only).
        notes: Audit notes collected while loading.
    """

    contracts_dir: str
    openapi_paths: frozenset[str]
    openapi_operations: frozenset[str]
    ddl_tables: frozenset[str]
    ddl_columns: frozenset[tuple[str, str]]
    ddl_indexes: frozenset[str]
    ddl_raw_indexes: frozenset[str]
    ddl_hnsw_names: frozenset[str]
    ddl_index_objects_total: int
    sse_channels: frozenset[str]
    error_codes: frozenset[str]
    schema_version: str
    notes: tuple[str, ...] = ()

    @classmethod
    def load(cls, contracts_dir: Path) -> ArtifactStore:
        """Load the four faces from ``contracts/``.

        Args:
            contracts_dir: ``<repo>/contracts`` or a temporary clone.

        Returns:
            A populated :class:`ArtifactStore`.

        Raises:
            ContractLoadError: If a file is missing/unparsable, or a face is
                empty (K-11: an empty set is INVALID, never a pass).
        """
        root = Path(contracts_dir).expanduser().resolve()
        notes: list[str] = []
        openapi = _load_json(root / OPENAPI_ARTIFACT)
        if not isinstance(openapi, dict) or not isinstance(openapi.get("paths"), dict):
            raise ContractLoadError(f"{OPENAPI_ARTIFACT}: missing `paths` object")
        paths: set[str] = set()
        operations: set[str] = set()
        for path, item in openapi["paths"].items():
            if not isinstance(item, dict):
                raise ContractLoadError(f"{OPENAPI_ARTIFACT}: path {path!r} is not an object")
            paths.add(str(path))
            for method in item:
                if str(method).lower() in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                    operations.add(f"{str(method).upper()} {path}")

        ddl = _load_json(root / DDL_ARTIFACT)
        if not isinstance(ddl, dict) or not isinstance(ddl.get("tables"), list):
            raise ContractLoadError(f"{DDL_ARTIFACT}: missing `tables` array")
        tables: set[str] = set()
        columns: set[tuple[str, str]] = set()
        indexes: set[str] = set()
        for table in ddl["tables"]:
            if not isinstance(table, dict) or "name" not in table:
                raise ContractLoadError(f"{DDL_ARTIFACT}: malformed table entry")
            name = str(table["name"])
            tables.add(name)
            for column in table.get("columns", []):
                if not isinstance(column, dict) or "name" not in column:
                    raise ContractLoadError(f"{DDL_ARTIFACT}: malformed column in {name}")
                columns.add((name, str(column["name"])))
            for index in table.get("indexes", []):
                if not isinstance(index, dict) or "name" not in index:
                    raise ContractLoadError(f"{DDL_ARTIFACT}: malformed index in {name}")
                indexes.add(str(index["name"]))
        raw_entries = ddl.get("raw_indexes", [])
        if not isinstance(raw_entries, list):
            raise ContractLoadError(f"{DDL_ARTIFACT}: `raw_indexes` is not an array")
        raw_names: set[str] = set()
        hnsw_names: set[str] = set()
        for entry in raw_entries:
            if not isinstance(entry, dict) or "name" not in entry:
                raise ContractLoadError(f"{DDL_ARTIFACT}: malformed raw_indexes entry")
            raw_names.add(str(entry["name"]))
            if str(entry.get("method", "")).lower() == "hnsw":
                hnsw_names.add(str(entry["name"]))
        counts = ddl.get("counts")
        declared_total = -1
        if isinstance(counts, dict) and isinstance(counts.get("index_objects_total"), int):
            declared_total = int(counts["index_objects_total"])
        else:
            notes.append(f"contracts: {DDL_ARTIFACT} has no counts.index_objects_total")
        schema_version = str(ddl.get("schema_version", ""))
        if schema_version != EXPECTED_SCHEMA_VERSION:
            notes.append(
                f"contracts: schema_version={schema_version!r} != {EXPECTED_SCHEMA_VERSION!r}"
            )

        sse = _load_json(root / SSE_ARTIFACT)
        if not isinstance(sse, dict) or not isinstance(sse.get("by_channel"), dict):
            raise ContractLoadError(f"{SSE_ARTIFACT}: missing `by_channel` object")
        # ⚠️ 方向注意：``_old`` 的 ``SSE_CHANNEL_BY_DOMAIN_TYPE`` 是
        # ``domain_type -> channel``，而 ``contracts/sse/channels.json#by_channel``
        # 是 ``channel -> domain_type``（同一张映射表的反向索引）。
        # 因此**两侧都取 channel 名**：外部取 dict 的值，contracts 取 dict 的键。
        channels = {str(key) for key in sse["by_channel"]}
        entries = sse.get("channels")
        if isinstance(entries, list) and entries:
            declared = {
                str(entry["channel"])
                for entry in entries
                if isinstance(entry, dict) and "channel" in entry
            }
            if declared and declared != channels:
                notes.append(
                    "contracts: sse/channels.json by_channel keys != channels[].channel "
                    f"({len(declared)} vs {len(channels)})"
                )

        errors = _load_json(root / ERRORS_ARTIFACT)
        if not isinstance(errors, dict) or not isinstance(errors.get("codes"), dict):
            raise ContractLoadError(f"{ERRORS_ARTIFACT}: missing `codes` object")
        codes = {str(key) for key in errors["codes"]}

        faces = {
            "openapi.paths": paths,
            "openapi.operations": operations,
            "ddl.tables": tables,
            "ddl.columns": columns,
            "ddl.indexes": indexes,
            "sse.channels": channels,
            "errors.codes": codes,
        }
        empty = sorted(name for name, value in faces.items() if not value)
        if empty:
            raise ContractLoadError(f"empty contract face(s), INVALID not PASS: {empty}")

        return cls(
            contracts_dir=str(root),
            openapi_paths=frozenset(paths),
            openapi_operations=frozenset(operations),
            ddl_tables=frozenset(tables),
            ddl_columns=frozenset(columns),
            ddl_indexes=frozenset(indexes),
            ddl_raw_indexes=frozenset(raw_names),
            ddl_hnsw_names=frozenset(hnsw_names),
            ddl_index_objects_total=declared_total,
            sse_channels=frozenset(channels),
            error_codes=frozenset(codes),
            schema_version=schema_version,
            notes=tuple(notes),
        )


def _load_json(path: Path) -> Any:
    """Load a JSON artifact, mapping every failure onto :class:`ContractLoadError`."""
    if not path.is_file():
        raise ContractLoadError(f"artifact missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractLoadError(f"artifact unreadable: {path} ({exc})") from exc


# ---------------------------------------------------------------------------
# 判定结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FaceVerdict:
    """One compared face.

    Attributes:
        face: ``F1`` / ``F2`` / ``F3`` / ``F4``.
        label: Human-readable face name (``"openapi.paths"``).
        state: ``MATCH`` / ``MISMATCH``.
        external: What the external oracle says (count).
        contracts: What ``contracts/`` says (count).
        diffs: Object-level differences (empty when ``MATCH``).
    """

    face: str
    label: str
    state: str
    external: int
    contracts: int
    diffs: tuple[_gate_io.Diff, ...] = ()

    def render(self) -> str:
        """Render one ``[oracle]`` line: face, verdict and both counts."""
        return (
            f"{self.face} {self.label:<18} {self.state:<9} "
            f"external={self.external:<5} contracts={self.contracts:<5}"
        )


@dataclass(frozen=True)
class OracleVerdict:
    """The whole comparison (all faces) plus provenance.

    Attributes:
        tier: ``O-A(legacy)`` or ``O-C(snapshot)``.
        faces: Per-face verdicts.
        facts: The external facts actually used.
        notes: Honesty notes (skipped faces, unmappable sets, ...).
    """

    tier: str
    faces: tuple[FaceVerdict, ...]
    facts: LegacyFacts
    notes: tuple[str, ...] = ()

    @property
    def mismatched(self) -> bool:
        """Whether any face differs from ``contracts/``."""
        return any(face.state != "MATCH" for face in self.faces)

    @property
    def total_diffs(self) -> int:
        """Total object-level differences across faces."""
        return sum(len(face.diffs) for face in self.faces)

    def all_diffs(self) -> list[_gate_io.Diff]:
        """Flatten every face's diffs in face order."""
        collected: list[_gate_io.Diff] = []
        for face in self.faces:
            collected.extend(face.diffs)
        return collected


def _face(
    face: str,
    label: str,
    external: set[Any] | frozenset[Any],
    contracts: set[Any] | frozenset[Any],
) -> FaceVerdict:
    """Compare two sets and build a :class:`FaceVerdict`."""
    left = set(external)
    right = set(contracts)
    diffs = tuple(_gate_io.set_diff_report(left, right))
    return FaceVerdict(
        face=face,
        label=label,
        state="MATCH" if not diffs else "MISMATCH",
        external=len(left),
        contracts=len(right),
        diffs=diffs,
    )


def recompute(contracts: ArtifactStore, facts: LegacyFacts) -> OracleVerdict:
    """Compare the external facts against ``contracts/`` face by face.

    Args:
        contracts: Expected side (``contracts/``).
        facts: External side (``_old`` scan or O-C snapshot).

    Returns:
        An :class:`OracleVerdict`; ``verdict.mismatched`` is the gate result.
    """
    columns: set[tuple[str, str]] = set(facts.ddl_columns)
    verdicts: list[FaceVerdict] = [
        _face("F1", "openapi.paths", set(facts.openapi_paths), set(contracts.openapi_paths)),
        _face(
            "F1",
            "openapi.operations",
            set(facts.openapi_operations),
            set(contracts.openapi_operations),
        ),
        _face("F2", "ddl.tables", set(facts.ddl_tables), set(contracts.ddl_tables)),
        _face("F2", "ddl.columns", columns, set(contracts.ddl_columns)),
        _face("F2", "ddl.indexes", set(facts.ddl_indexes), set(contracts.ddl_indexes)),
        _face(
            "F2",
            "ddl.raw_indexes",
            {fact.name for fact in facts.ddl_raw_indexes},
            set(contracts.ddl_raw_indexes),
        ),
        _face("F3", "sse.channels", set(facts.sse_channels), set(contracts.sse_channels)),
        _face("F4", "errors.codes", set(facts.error_codes), set(contracts.error_codes)),
    ]
    hnsw_face = _face(
        "F2", "ddl.hnsw", set(facts.ddl_hnsw_names), set(contracts.ddl_hnsw_names)
    )
    if len(facts.ddl_hnsw_names) != EXPECTED_HNSW_COUNT or len(
        contracts.ddl_hnsw_names
    ) != EXPECTED_HNSW_COUNT:
        hnsw_face = dataclasses.replace(
            hnsw_face,
            state="MISMATCH",
            diffs=hnsw_face.diffs
            + (
                _gate_io.Diff(
                    kind="count",
                    subject="ddl.hnsw_indexes",
                    left=f"external={len(facts.ddl_hnsw_names)}",
                    right=f"contracts={len(contracts.ddl_hnsw_names)}",
                ),
            ),
        )
    verdicts.append(hnsw_face)
    return OracleVerdict(
        tier="O-A(legacy)",
        faces=tuple(verdicts),
        facts=facts,
        notes=facts.notes,
    )


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def _print_face(verdict: FaceVerdict) -> None:
    """Print one face line plus (capped) object-level diffs."""
    print(f"[oracle] {verdict.render()}")
    if not verdict.diffs:
        return
    for diff in verdict.diffs[:MAX_DIFF_LINES]:
        print(f"[oracle]   - {diff.render()}")
    remaining = len(verdict.diffs) - MAX_DIFF_LINES
    if remaining > 0:
        print(f"[oracle]   - ... {remaining} more diff(s) not shown")


def _print_coverage() -> None:
    """Print the mandatory coverage line (施工 §1.3 / §5-T03 要点 ③).

    **只报绿不报覆盖面 = 自证无效**：本行必须出现在每一次运行（含降级档与红档）。
    """
    print(
        "[oracle] oracle coverage: "
        f"{len(ORACLE_FACES)}/23 criteria externally recomputed; "
        f"{INTERNAL_ONLY_CRITERIA} remain internal-only"
    )
    print(
        "[oracle] coverage detail: "
        "F1 -> C1(paths)/C2(operations) | "
        "F2 -> C4(tables)/C5(columns)/C6(indexes 集合级)/C7(hnsw)/C8(index_objects_total) | "
        "F3 -> C10(channels) | "
        "F4 -> C13(error codes)"
    )
    print(
        "[oracle] coverage caveat: 分母按「面」计（4），C6/C8 仅**集合级**重算、"
        "列**类型**未外部重算 ⇒ 不得表述为「23 条全覆盖」"
    )


def _print_degraded() -> None:
    """Print the mandatory ``DEGRADED`` banner for the O-C tier."""
    print(
        f"[oracle] {snapshot_module.DEGRADED_MARKER}: oracle tier is O-C(snapshot) — "
        "weak truth (仓内可改文件；只防「忘记更新」，不防「蓄意同改」)"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser (kept separate so ``--help`` stays readable)."""
    parser = argparse.ArgumentParser(
        prog="oracle_recompute.py",
        description="Recompute F1-F4 from an external oracle and compare with contracts/.",
    )
    parser.add_argument(
        "--oracle",
        choices=("legacy", "snapshot"),
        default="legacy",
        help="legacy = O-A (read _old); snapshot = O-C degraded (refuses to pass)",
    )
    parser.add_argument("--contracts", type=Path, default=None, help="contracts dir (clone in ATK)")
    parser.add_argument("--legacy-root", type=Path, default=None, help="read-only _old root")
    parser.add_argument("--snapshot", type=Path, default=None, help="O-C snapshot path")
    parser.add_argument(
        "--write-snapshot",
        action="store_true",
        help="write the O-C snapshot (only allowed when the O-A scan succeeded)",
    )
    parser.add_argument("--assert-independent", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true", help="also print a JSON verdict")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without program name.

    Returns:
        ``0`` / ``20`` / ``21`` / ``22`` / ``2`` / ``9`` per 施工 §3.3.
    """
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = _SCRIPTS_DIR.parent
    contracts_dir = args.contracts or repo_root / "contracts"
    snapshot_path = args.snapshot or snapshot_module.default_snapshot_path(repo_root)

    if args.self_test:
        return _self_test(contracts_dir, snapshot_path)

    exit_code = 0
    if args.assert_independent:
        exit_code = max(exit_code, _report_independence())

    if args.write_snapshot and args.oracle != "legacy":
        print(
            "[oracle] ERROR: --write-snapshot is only allowed when --oracle legacy "
            "succeeds (施工 §5-T03 要点 ④)"
        )
        return _gate_io.EXIT_USAGE

    # 1) 期望侧。
    try:
        store = ArtifactStore.load(contracts_dir)
    except ContractLoadError as exc:
        print(f"[oracle] ARTIFACT-LOAD-FAILED {exc}")
        _print_coverage()
        return _gate_io.EXIT_ARTIFACT_LOAD
    for note in store.notes:
        print(f"[oracle] note {note}")
    print(
        f"[oracle] contracts: {store.contracts_dir} "
        f"(openapi={OPENAPI_ARTIFACT}, ddl={DDL_ARTIFACT} {store.schema_version})"
    )

    # 2) 外部侧。
    degraded = args.oracle == "snapshot"
    facts: LegacyFacts
    if degraded:
        _print_degraded()
        print(f"[oracle] snapshot: {snapshot_path}")
        try:
            facts, meta = snapshot_module.read_snapshot(snapshot_path)
        except OracleUnavailable as exc:
            print(f"[oracle] UNAVAILABLE {exc}")
            _print_coverage()
            print(
                "[oracle] VERDICT: DEGRADED-UNAVAILABLE (21) — degraded tier never passes"
            )
            return _gate_io.EXIT_ORACLE_UNAVAILABLE
        print(
            f"[oracle] snapshot meta: tier={meta.get('oracle_tier')} "
            f"generated_at={meta.get('generated_at')}"
        )
        if args.legacy_root is not None and not Path(args.legacy_root).is_dir():
            print(
                f"[oracle] note legacy root absent ({args.legacy_root}) — "
                "O-A unavailable, running the degraded tier only (DEGRADED)"
            )
    else:
        legacy_root = args.legacy_root or _gate_io.GatePaths.resolve(
            repo_root=repo_root
        ).legacy_root
        print(f"[oracle] oracle tier: O-A(legacy) root={legacy_root}")
        oracle = LegacyOracle(legacy_root, timeout_s=args.timeout)
        try:
            facts = oracle.scan()
        except ReadonlyViolation as exc:
            print(f"[oracle] READONLY-VIOLATION {', '.join(exc.paths)}")
            _print_coverage()
            return _gate_io.EXIT_ORACLE_UNAVAILABLE
        except OracleUnavailable as exc:
            print(f"[oracle] UNAVAILABLE {exc.reason}")
            _print_coverage()
            print("[oracle] VERDICT: UNAVAILABLE (21) — no truth, no pass")
            return _gate_io.EXIT_ORACLE_UNAVAILABLE
        if args.write_snapshot:
            try:
                snapshot_module.write_snapshot(
                    facts, snapshot_path, contracts_dir=contracts_dir, oracle_tier="O-A"
                )
            except snapshot_module.SnapshotError as exc:
                print(f"[oracle] SNAPSHOT-REFUSED {exc}")
                _print_coverage()
                return _gate_io.EXIT_ARTIFACT_LOAD
            digest = snapshot_module.snapshot_sha256(snapshot_path)
            print(f"[oracle] snapshot written: {snapshot_path} (sha256={digest})")

    # 3) 四面比对。
    verdict = recompute(store, facts)
    for face in verdict.faces:
        _print_face(face)
    notes = _dedupe(verdict.notes)
    for note in notes[:MAX_NOTE_LINES]:
        print(f"[oracle] note {note}")
    if len(notes) > MAX_NOTE_LINES:
        print(f"[oracle] note ... {len(notes) - MAX_NOTE_LINES} more note(s) suppressed")

    _print_coverage()

    if verdict.mismatched:
        print(
            f"[oracle] VERDICT: MISMATCH (20) — {verdict.total_diffs} object-level "
            "difference(s) against the external oracle"
        )
        if args.json:
            print(json.dumps(_verdict_payload(verdict, degraded), ensure_ascii=False, indent=2))
        return _gate_io.EXIT_ORACLE_MISMATCH

    if degraded:
        print(
            "[oracle] VERDICT: DEGRADED-CONSISTENT (21) — snapshot tier agrees, but the "
            "snapshot is a mutable in-repo file, so this is NOT an external-truth pass"
        )
        if args.json:
            print(json.dumps(_verdict_payload(verdict, degraded), ensure_ascii=False, indent=2))
        return max(exit_code, _gate_io.EXIT_ORACLE_UNAVAILABLE)

    print(
        "[oracle] VERDICT: PASS (0) — F1-F4 consistent with the external oracle "
        "(_old source tree)"
    )
    if args.json:
        print(json.dumps(_verdict_payload(verdict, degraded), ensure_ascii=False, indent=2))
    return max(exit_code, _gate_io.EXIT_OK)


def _verdict_payload(verdict: OracleVerdict, degraded: bool) -> dict[str, Any]:
    """Build the ``--json`` payload (consumed by T04's inject engine)."""
    return {
        "tier": "O-C(snapshot)" if degraded else verdict.tier,
        "degraded": degraded,
        "mismatched": verdict.mismatched,
        "total_diffs": verdict.total_diffs,
        "faces": [
            {
                "face": face.face,
                "label": face.label,
                "state": face.state,
                "external": face.external,
                "contracts": face.contracts,
                "diffs": [diff.to_dict() for diff in face.diffs],
            }
            for face in verdict.faces
        ],
        "coverage": {
            "faces": len(ORACLE_FACES),
            "criteria_total": 23,
            "criteria_externally_recomputed": len(ORACLE_FACES),
            "criteria_internal_only": INTERNAL_ONLY_CRITERIA,
        },
        "diff_subjects": sorted({diff.subject for diff in verdict.all_diffs()}),
    }


def _report_independence() -> int:
    """Run the ``--assert-independent`` check over the oracle modules."""
    from oracle.legacy_scan import assert_independent

    files = [
        Path(__file__).resolve().parent / "oracle" / "legacy_scan.py",
        Path(__file__).resolve().parent / "oracle" / "snapshot.py",
        Path(__file__).resolve(),
    ]
    report = assert_independent(files)
    print(
        f"[oracle] independence: files={len(report.scanned)} "
        f"violations={len(report.violations)} runtime={len(report.runtime)}"
    )
    for violation in report.violations:
        print(f"[oracle]   VIOLATION {violation}")
    for module in report.runtime:
        print(f"[oracle]   RUNTIME-MODULE {module}")
    print(f"[oracle] independence verdict: {'INDEPENDENT' if report.ok else 'SHARED-PARSER'}")
    return _gate_io.EXIT_OK if report.ok else _gate_io.EXIT_SELFTEST


# ---------------------------------------------------------------------------
# --self-test
# ---------------------------------------------------------------------------


def _self_test(contracts_dir: Path, snapshot_path: Path) -> int:
    """Prove the comparison is not vacuous.

    Five checks:

    1. ``contracts/`` vs a facts object rebuilt **from** ``contracts/`` → all MATCH;
    2. drop one hnsw from those facts → ``F2 ddl.hnsw`` MISMATCH naming the index;
    3. drop one path → ``F1 openapi.paths`` MISMATCH;
    4. drop one SSE channel → ``F3`` MISMATCH;
    5. an unreadable snapshot raises instead of returning an empty truth.

    Args:
        contracts_dir: Directory holding the frozen artifacts.
        snapshot_path: Path used for the missing-snapshot probe.

    Returns:
        ``0`` when all checks pass, ``9`` otherwise.
    """
    failures: list[str] = []
    checks = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        if condition:
            print(f"[oracle] self-test OK   {name}")
            return
        failures.append(f"{name}: {detail}")
        print(f"[oracle] self-test FAIL {name} {detail}")

    try:
        store = ArtifactStore.load(contracts_dir)
    except ContractLoadError as exc:
        print(f"[oracle] self-test ABORT cannot load contracts: {exc}")
        return _gate_io.EXIT_SELFTEST

    baseline = _facts_from_store(store)
    verdict = recompute(store, baseline)
    check(
        "baseline-all-match",
        not verdict.mismatched,
        " | ".join(face.render() for face in verdict.faces if face.state != "MATCH"),
    )

    # 2) 删 1 条 hnsw（只删外部侧）⇒ F2 hnsw 必红且点名该索引。
    victim = sorted(store.ddl_hnsw_names)[0] if store.ddl_hnsw_names else ""
    truncated_raw = tuple(
        fact for fact in baseline.ddl_raw_indexes if fact.name != victim
    )
    mutated = dataclasses.replace(baseline, ddl_raw_indexes=truncated_raw)
    mutated_verdict = recompute(store, mutated)
    hnsw_face = next(face for face in mutated_verdict.faces if face.label.startswith("ddl.hnsw"))
    check(
        "hnsw-deleted-detected",
        mutated_verdict.mismatched and hnsw_face.state == "MISMATCH",
        f"victim={victim!r} face={hnsw_face.render()}",
    )
    check(
        "hnsw-deleted-names-object",
        any(diff.subject == victim for diff in hnsw_face.diffs),
        f"diff subjects={[diff.subject for diff in hnsw_face.diffs]}",
    )

    # 3) 删 1 个 path。
    dropped_path = sorted(store.openapi_paths)[0]
    path_mutated = dataclasses.replace(
        baseline,
        openapi_paths=tuple(p for p in baseline.openapi_paths if p != dropped_path),
        openapi_operations=tuple(
            op for op in baseline.openapi_operations if not op.endswith(" " + dropped_path)
        ),
    )
    path_verdict = recompute(store, path_mutated)
    check(
        "path-deleted-detected",
        path_verdict.mismatched,
        f"dropped={dropped_path!r} diffs={path_verdict.total_diffs}",
    )

    # 4) 删 1 条 SSE 通道。
    dropped_channel = sorted(store.sse_channels)[0]
    channel_mutated = dataclasses.replace(
        baseline,
        sse_channels=tuple(c for c in baseline.sse_channels if c != dropped_channel),
    )
    channel_verdict = recompute(store, channel_mutated)
    check(
        "sse-channel-deleted-detected",
        channel_verdict.mismatched,
        f"dropped={dropped_channel!r} diffs={channel_verdict.total_diffs}",
    )

    # 5) 不可读快照 ⇒ OracleUnavailable（不是"空真值"）。
    missing = snapshot_path.parent / "__no_such_snapshot__.json"
    try:
        snapshot_module.read_snapshot(missing)
        check("missing-snapshot-unavailable", False, "no OracleUnavailable raised")
    except OracleUnavailable as exc:
        check("missing-snapshot-unavailable", True, str(exc))

    print(f"[oracle] self-test: {checks - len(failures)}/{checks} passed")
    if failures:
        for failure in failures:
            print(f"[oracle] self-test detail {failure}")
        return _gate_io.EXIT_SELFTEST
    return _gate_io.EXIT_OK


def _facts_from_store(store: ArtifactStore) -> LegacyFacts:
    """Build a :class:`LegacyFacts` whose faces equal ``contracts/`` exactly.

    Used only by ``--self-test`` as the "no difference" baseline; it is **never**
    treated as external truth by the gate itself.
    """
    from oracle.legacy_scan import RawIndexFact

    return LegacyFacts(
        legacy_root="<self-test: derived from contracts>",
        scanned_at="1970-01-01T00:00:00Z",
        openapi_paths=tuple(sorted(store.openapi_paths)),
        openapi_operations=tuple(sorted(store.openapi_operations)),
        ddl_tables=tuple(sorted(store.ddl_tables)),
        ddl_columns=tuple(sorted(store.ddl_columns)),
        ddl_indexes=tuple(sorted(store.ddl_indexes)),
        ddl_raw_indexes=tuple(
            RawIndexFact(
                name=name,
                table="<self-test>",
                method="hnsw" if name in store.ddl_hnsw_names else "btree",
                operator_class=None,
                sql="",
            )
            for name in sorted(store.ddl_raw_indexes)
        ),
        sse_channels=tuple(sorted(store.sse_channels)),
        error_codes=tuple(sorted(store.error_codes)),
        notes=("self-test baseline derived from contracts",),
        chain=(),
    )


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
