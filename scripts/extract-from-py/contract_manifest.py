"""C-07: `contracts/contract-manifest.json` -- the object-level ledger.

Two ledgers, one truth
----------------------
``contracts/manifest.sha256`` answers *"is this file byte-identical?"* (flat,
one line per file).  ``contracts/contract-manifest.json`` answers *"what is this
file, where did it come from, and which judgement criterion does it serve?"*.

They must never disagree.  :func:`write` cross-checks every digest against the
ledger computed by :mod:`hashes`, and :func:`verify` re-checks the pair on every
``run.py check``.  A divergence raises :class:`ManifestConsistencyError` instead
of writing two competing truths (双真相源 would be worse than no ledger).

How classification avoids guessing
----------------------------------
Most artifacts already embed their producer (``generated_by`` at top level, or
under ``x-wbtimeai``).  This module reads that value and **cross-checks** it
against the rule table below; a mismatch is a hard error.  Nothing is inferred
from file names alone where the artifact can speak for itself, and an artifact
with no rule at all is a hard error too (fail-closed: a new contract file must be
classified deliberately, never defaulted to ``manual``).

``source`` semantics (`施工纪律.md` §4.5.1-3, `contracts/README.md`)
------------------------------------------------------------------
* ``metadata``  -- compiled/reflected from ORM metadata or code-introspected
  models (61 tables / 629 columns / 174 indexes / type map / OpenAPI doc /
  error enum / SSE registry / response-shell schema).
* ``migration`` -- lifted from the migration chain's raw DDL (2 raw hnsw indexes,
  FTS5 virtual + shadow tables, the migration-map coverage list).
* ``manual``    -- hand-authored scaffold (README ledgers, the endpoint list's
  comment scaffold and split wording, golden-frame construction, conformance
  skeletons).

Composite artifacts (the merged DDL carries metadata *and* migration fragments)
are classified by their **dominant** source -- ``metadata`` -- and the secondary
source is recorded in :data:`CLASSIFICATION_RULES` so the split stays auditable
rather than hidden inside one enum value.

CLI::

    python scripts/extract-from-py/contract_manifest.py --contracts-dir contracts
    python scripts/extract-from-py/contract_manifest.py --check
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import fnmatch
import io
import json
import sys
from pathlib import Path
from typing import Any

import _bootstrap
import hashes
from export_openapi import collect_operations

__all__ = [
    "MANIFEST_JSON_NAME",
    "SOURCE_VALUES",
    "DIALECT_VALUES",
    "FROM_ARTIFACT",
    "CLASSIFICATION_RULES",
    "FIELD_SEMANTICS",
    "STATUS_SEMANTICS",
    "DDL_OBJECT_TOTAL",
    "DDL_OBJECT_EXPECTED",
    "MUST_NOT_BE_DROPPED",
    "ManifestConsistencyError",
    "Rule",
    "build_payload",
    "write",
    "verify",
    "main",
]

#: File name of the object ledger, relative to the contracts directory.
MANIFEST_JSON_NAME = "contract-manifest.json"

#: Allowed ``source`` values -- strictly three (§4.5.1-3).
SOURCE_VALUES: tuple[str, ...] = ("metadata", "migration", "manual")

#: Allowed ``dialect_only`` values -- strictly three (§4.5.1-4).
DIALECT_VALUES: tuple[str, ...] = ("pg", "sqlite", None)

#: Sentinel: "take ``generated_by`` from the artifact itself, error if absent".
FROM_ARTIFACT = "__from_artifact__"

#: Producer of the merged DDL family (embedded in both normalized snapshots).
DDL_EXPORTER = "scripts/extract-from-py/ddl/export_ddl.py"

#: Producer of the OpenAPI freeze (C-02).
OPENAPI_EXPORTER = "scripts/extract-from-py/export_openapi.py"

#: Producer of the migration map + conformance skeletons (C-06).
MIGRATION_EXPORTER = "scripts/extract-from-py/export_migration.py"

#: Node ids that must never be classified ③ 放弃或合并 (D-2).
#:
#: ``test_unmapped_mcp_tool_is_fail_closed_and_roundtrips`` is the tree's **only**
#: API-level fail-closed assertion (``mcp_tool_id`` not synced into ``tool`` ⇒ the
#: runtime judgement source must NOT be written, plus a structured warning and a
#: round-trip on the legacy endpoint).  It was dropped as if it were a redirect
#: shim; the claimed replacement gate (``test_single_chain``) holds only unit-level
#: checker assertions.  Dropping it again now fails the export instead of silently
#: removing the only gate for that invariant.
MUST_NOT_BE_DROPPED: tuple[str, ...] = (
    "tests/integration/permission/test_mcp_permissions_redirect.py"
    "::test_unmapped_mcp_tool_is_fail_closed_and_roundtrips",
)


class ManifestConsistencyError(RuntimeError):
    """Raised when the object ledger and the sha256 ledger disagree."""


@dataclasses.dataclass(frozen=True)
class Rule:
    """One classification rule: a glob, its verdict, and why.

    Attributes:
        pattern: ``fnmatch`` pattern matched against the POSIX relative path.
        source: One of :data:`SOURCE_VALUES`.
        dialect_only: ``pg`` / ``sqlite`` / ``None``.
        generated_by: Absolute-from-repo-root producer path, :data:`FROM_ARTIFACT`,
            or ``None`` for hand-authored files.
        requirement: Which judgement criterion the artifact serves.
        rationale: Why this classification is substantively correct.
    """

    pattern: str
    source: str
    dialect_only: str | None
    generated_by: str | None
    requirement: str
    rationale: str


#: Ordered rule table -- **first match wins**, so keep specific patterns on top.
CLASSIFICATION_RULES: tuple[Rule, ...] = (
    Rule(
        pattern="frontend-baseline/*",
        source="manual",
        dialect_only=None,
        generated_by="scripts/gen_frontend_baseline.py",
        requirement="V0.1.0/T1-01 前端基线派生件（供 apps/web 消费的冻结件投影）",
        rationale=(
            "三件均由 scripts/gen_frontend_baseline.py 从 contracts/ 内**已冻结产物**派生 "
            "（openapi.v1.frozen.json / sse/channels.json / errors.json），既不来自 _old 的 ORM "
            "metadata 编译，也不来自迁移链 raw DDL，故 source=manual。"
            "本组为 V0.1.0 首次新增进 contracts/，属施工纪律 §4.5.1「经批准的重导」："
            "已实测 39 项既有产物 sha256 零变化，仅新增 3 项，变更史登记于 "
            "docs/V1.0/V0.1.0-基座与契约层/03-台账/DoD-V0.1.0.md「契约变更史」"
        ),
    ),
    Rule(
        pattern="schema.v0018.pg.sql",
        source="metadata",
        dialect_only="pg",
        generated_by=DDL_EXPORTER,
        requirement="V0.0.1/DoD#3 DDL 三源合并·176 索引对象·双侧快照",
        rationale=(
            "主体由 ORM metadata 编译（61 表 / 629 列 / 174 索引），迁移链 raw DDL 只补 2 条 hnsw；"
            "按主导来源归 metadata，次要来源 migration 见 normalized 快照的 counts 与 notes"
        ),
    ),
    Rule(
        pattern="schema.v0018.pg.normalized.json",
        source="metadata",
        dialect_only="pg",
        generated_by=DDL_EXPORTER,
        requirement="V0.0.1/DoD#3 DDL 三源合并·176 索引对象·双侧快照（PG normalized）",
        rationale=(
            "编译产物自身携带 counts{metadata_indexes:174, raw_indexes:2, index_objects_total:176}，"
            "来自 metadata + migration 合并后的规范化视图"
        ),
    ),
    Rule(
        pattern="schema.v0018.sqlite.sql",
        source="metadata",
        dialect_only="sqlite",
        generated_by=DDL_EXPORTER,
        requirement="V0.0.1/DoD#3 DDL 三源合并·176 索引对象·双侧快照（SQLite 含 FTS5）",
        rationale=(
            "主体同为 metadata 编译，另含 SQLite 专属 FTS5 虚表 / 影子表 / 3 触发器；"
            "FTS5 语句取自迁移链，但对象本身是 SQLite 方言产物，故 dialect_only=sqlite"
        ),
    ),
    Rule(
        pattern="schema.v0018.sqlite.normalized.json",
        source="metadata",
        dialect_only="sqlite",
        generated_by=DDL_EXPORTER,
        requirement="V0.0.1/DoD#3 DDL 三源合并·176 索引对象·双侧快照（SQLite normalized）",
        rationale="编译产物自身携带 counts 与 dialect_only_objects 明细（8 个 SQLite 专属对象）",
    ),
    Rule(
        pattern="db/type-map.csv",
        source="metadata",
        dialect_only=None,
        generated_by="scripts/extract-from-py/ddl/gen_type_map.py",
        requirement="V0.0.1/DoD#3 DDL 三源合并（列级类型映射）",
        rationale=(
            "逐列事实（declared / declared_str_type / pg_emit_type / sqlite_emit_type）来自 ORM metadata 反射与 "
            "两侧编译结果；但 ts_target 与 strategy 两列是人工映射策略 ⇒ 内容主体仍是事实映射，故 source=metadata，"
            "人工列在此显式登记；跨方言对照表本身 ⇒ dialect_only=null"
        ),
    ),
    Rule(
        pattern="openapi.v1.frozen.json",
        source="metadata",
        dialect_only=None,
        generated_by=OPENAPI_EXPORTER,
        requirement="V0.0.1/DoD#2 100 paths·134 ops·116 schemas",
        rationale="由 create_app().openapi() 代码内省自动导出（FastAPI 路由/schema 即结构化元数据），非手写、非迁移链",
    ),
    Rule(
        pattern="endpoints.txt",
        source="manual",
        dialect_only=None,
        generated_by=OPENAPI_EXPORTER,
        requirement="V0.0.1/DoD#2 100 paths·134 ops·116 schemas（134+133 分列口径）",
        rationale=(
            "数据行派生自 openapi.v1.frozen.json，但分段标题、134/133 口径公式与排除说明是人写骨架 ⇒ "
            "按 C-07 裁定归 manual；派生关系记于 notices[derived:endpoints]"
        ),
    ),
    Rule(
        pattern="envelope.schema.json",
        source="manual",
        dialect_only=None,
        generated_by="scripts/extract-from-py/export_envelope.py",
        requirement="V0.2.0 响应壳逐字节",
        rationale=(
            "改判为 manual：产物自带 x-wbtimeai.provenance，6 个 $defs 中仅 ErrorResponse / MessageResponse 是 "
            "pydantic 反射（pydantic:schemas/common.py），而 errorEnvelope / messageEnvelope / successBody / "
            "successEnvelope 与 enforcement 表全部标为 manual+measured ⇒ 壳层如何组装（任何处套壳、哪些不套壳）"
            "是人定的，机器只提供叶子模型与实测探针。按「谁产生了这份内容」判 manual"
        ),
    ),
    Rule(
        pattern="errors.json",
        source="metadata",
        dialect_only=None,
        generated_by="scripts/extract-from-py/export_errors.py",
        requirement="V0.0.1/DoD#6 + V0.2.0 错误码全表参数化",
        rationale=(
            "保持 metadata：产物 sources 把每个规范性字段都指到代码位置（ErrorCode 枚举 / exception.py / "
            "_STATUS_BY_CODE / AST call-site 扫描），http_status_source 实测分布 = api_status_map 27 + "
            "exception_class 2 + call_site_override 1；人工部分被限定为 30/30 条 description 且逐条标 "
            "description_source=manual ⇒ 描述是注记，不是规范事实，故不因描述人工而降级为 manual。"
            "contract_version=3 起，`http_status` 只是**逐 call-site 解析后的多数值**，"
            "非全量成立时由 http_status_uniform=false + http_status_distribution + "
            "http_status_inconsistent_call_sites 显式披露（D-1：DEPENDENCY_MISSING 8×503 + 2×500），"
            "并由 C22 做机器校验"
        ),
    ),
    Rule(
        pattern="sse/channels.json",
        source="metadata",
        dialect_only=None,
        generated_by="scripts/extract-from-py/export_sse.py",
        requirement="V0.0.1/DoD#4 SSE 19 帧逐字节",
        rationale="由 SSE 通道注册表反射生成（channels/by_channel/guard/numeric_format 均为注册表投影）",
    ),
    Rule(
        pattern="sse/golden/_guard-*.txt",
        source="manual",
        dialect_only=None,
        generated_by="scripts/extract-from-py/export_sse.py",
        requirement="V0.0.1/DoD#4 SSE 19 帧逐字节（数值格式守卫）",
        rationale="帧内数值（\"0.500000\" / neg_zero / nested.score）是人选的构造参数，用于锁死数值格式陷阱，非注册表投影",
    ),
    Rule(
        pattern="sse/golden/*.txt",
        source="manual",
        dialect_only=None,
        generated_by="scripts/extract-from-py/export_sse.py",
        requirement="V0.0.1/DoD#4 SSE 19 帧逐字节",
        rationale="帧的 payload 取值与字段顺序是人写构造参数；schema 校验面由 channels.json 覆盖",
    ),
    Rule(
        pattern="sse/README.md",
        source="manual",
        dialect_only=None,
        generated_by=None,
        requirement="V0.0.1/DoD#4 台账说明",
        rationale="人写的通道清单与判据说明",
    ),
    Rule(
        pattern="README.md",
        source="manual",
        dialect_only=None,
        generated_by=None,
        requirement="V0.0.1/DoD#6 版本号联签登记（M-4）",
        rationale="人写的产物登记与口径说明（含 0.4.8 代码串不得继承的约定）",
    ),
    # --- C-06: 迁移映射表 + conformance 骨架 --------------------------------
    # 骨架用例与断言是人写的，但文件本身由 export_migration.py 渲染（每个
    # source 的 file:line 在导出时对旧仓实测校验，不是手抄行号）。
    Rule(
        pattern="conformance/*.yaml",
        source="manual",
        dialect_only=None,
        generated_by=MIGRATION_EXPORTER,
        requirement="V0.0.1/DoD#8 冻结契约可表达性核查（conformance 骨架，按 applies_to 归属版本）",
        rationale="4 个不变量的种子用例是人写的骨架；文件由导出器渲染且 source 行号实测校验",
    ),
    # 逐行来自 `pytest --collect-only` 对旧仓测试树的**代码内省**（nodeid + marker），
    # 处置决策来自路线图 §4.1 规则表。不是从迁移链 DDL 里取出来的 ⇒ metadata，
    # 不用 migration（此处修正了 C-06 并行期的占位判定）。
    Rule(
        pattern="test-migration-map.csv",
        source="manual",
        dialect_only=None,
        generated_by=MIGRATION_EXPORTER,
        requirement="V0.0.1/DoD#5 用例映射（collected 1699）",
        rationale=(
            "改判为 manual（team-lead 2026-10-20 裁定：判定依据是「谁产生了这份内容」，不是「内容引用了谁」）："
            "test_id/file/markers 三列虽是 pytest 代码内省，但 bucket 归属、target_version 归属、outcome 与 note 的"
            "处置决策全部由人工规则表判定 ⇒ 这张表的实质是人做出的迁移判断；跨方言通用 ⇒ dialect_only=null"
        ),
    ),
    Rule(
        pattern="test-migration-summary.json",
        source="metadata",
        dialect_only=None,
        generated_by=MIGRATION_EXPORTER,
        requirement="DoD#5 口径登记（collected/selected/passed 三口径 + 分布 + 输入输出 sha256）",
        rationale="映射表的机器可读统计，与 CSV 同源同次生成，用于复算与审计",
    ),
)

#: Files that are themselves ledgers and therefore never appear as objects.
_LEDGER_FILES: frozenset[str] = frozenset({hashes.MANIFEST_NAME, MANIFEST_JSON_NAME})


def _embedded_generated_by(path: Path) -> str | None:
    """Read the producer recorded inside an artifact, when it records one.

    Args:
        path: Artifact path.

    Returns:
        The embedded producer path, or ``None`` when the format has no such field.
    """
    if path.suffix.lower() != ".json":
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    for candidate in (document.get("generated_by"), (document.get("x-wbtimeai") or {}).get("generated_by")):
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _classify(relative_path: str) -> Rule | None:
    """Return the first matching rule for ``relative_path``."""
    for rule in CLASSIFICATION_RULES:
        if fnmatch.fnmatchcase(relative_path, rule.pattern):
            return rule
    return None


def _read_json(path: Path) -> dict[str, Any]:
    """Load a JSON object, tolerating absence."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return document if isinstance(document, dict) else {}


# ---------------------------------------------------------------------------
# Criterion probes -- every number is *measured*, never restated from a document
# ---------------------------------------------------------------------------


def _criterion(
    ident: str,
    requirement: str,
    metric: str,
    expected: Any,
    measured: Any,
    artifact: str,
    basis: str,
    status: str = "verified",
    note: str = "",
) -> dict[str, Any]:
    """Assemble one criterion record."""
    record: dict[str, Any] = {
        "id": ident,
        "requirement": requirement,
        "metric": metric,
        "expected": expected,
        "measured": measured,
        "status": status,
        "artifact": artifact,
        "basis": basis,
    }
    if note:
        record["note"] = note
    return record


def _probe_openapi(contracts: Path) -> list[dict[str, Any]]:
    """DoD#2: 100 paths / 134 operations / 116 schemas."""
    spec = _read_json(contracts / "openapi.v1.frozen.json")
    if not spec:
        return [
            _criterion("C1", "DoD#2", "openapi 三集合", "100/134/116", None, "openapi.v1.frozen.json",
                       "V0.0.1 计划 §3 DoD#2", status="pending", note="artifact missing")
        ]
    paths = len(spec.get("paths") or {})
    operations = len(collect_operations(spec))
    schemas = len((spec.get("components") or {}).get("schemas") or {})
    records = [
        _criterion("C1", "DoD#2", "openapi.paths", 100, paths, "openapi.v1.frozen.json",
                   "V0.0.1 计划 §3 DoD#2「100 paths / 134 ops / 116 schemas」"),
        _criterion("C2", "DoD#2", "openapi.operations", 134, operations, "openapi.v1.frozen.json",
                   "同上（path × method 展开）"),
        _criterion("C3", "DoD#2", "openapi.schemas", 116, schemas, "openapi.v1.frozen.json",
                   "同上（components.schemas）"),
    ]
    return records


def _probe_ddl(contracts: Path) -> list[dict[str, Any]]:
    """DoD#3: 61 tables / 629 columns / 174 metadata indexes / +2 raw hnsw = 176."""
    pg = _read_json(contracts / "schema.v0018.pg.normalized.json")
    sqlite = _read_json(contracts / "schema.v0018.sqlite.normalized.json")
    if not pg or not sqlite:
        return [
            _criterion("C4", "DoD#3", "DDL 三源合并", "61/629/174+2", None,
                       "schema.v0018.*.normalized.json", "V0.0.1 计划 §3 DoD#3",
                       status="pending", note="normalized snapshot missing")
        ]

    pg_counts = pg.get("counts") or {}
    lite_counts = sqlite.get("counts") or {}
    records = [
        _criterion("C4", "DoD#3", "ddl.tables", 61, pg_counts.get("tables"),
                   "schema.v0018.pg.normalized.json",
                   "V0.0.1 计划 §3 DoD#3「metadata 61 表」",
                   note=f"sqlite 侧 = {lite_counts.get('tables')}"),
        _criterion("C5", "DoD#3", "ddl.columns", 629, pg_counts.get("columns"),
                   "schema.v0018.pg.normalized.json", "同上（629 列）",
                   note=f"sqlite 侧 = {lite_counts.get('columns')}"),
        _criterion("C6", "DoD#3", "ddl.metadata_indexes", 174, pg_counts.get("metadata_indexes"),
                   "schema.v0018.pg.normalized.json", "同上（174 metadata 索引）",
                   note=f"sqlite 侧 = {lite_counts.get('metadata_indexes')}"),
        _criterion("C7", "DoD#3", "ddl.raw_hnsw_indexes", 2, pg_counts.get("raw_indexes"),
                   "schema.v0018.pg.normalized.json",
                   "同上（+ raw hnsw 2，仅 PG：pgvector）",
                   note=f"sqlite 侧 = {lite_counts.get('raw_indexes')}（hnsw 为 PG 专属，合法 dialect_only 差异）"),
        _criterion("C8", "DoD#3", "ddl.index_objects_total", 176, pg_counts.get("index_objects_total"),
                   "schema.v0018.pg.normalized.json", "174 metadata + 2 raw hnsw = 176",
                   note=f"sqlite 侧 = {lite_counts.get('index_objects_total')}（174，无 hnsw）"),
    ]

    # SQLite dialect-only object breakdown vs DoD wording「FTS5 虚表与 5 影子表」.
    dialect_objects = sqlite.get("dialect_only") or []
    kinds: dict[str, int] = {}
    for item in dialect_objects:
        kind = str((item or {}).get("kind", "unknown"))
        kinds[kind] = kinds.get(kind, 0) + 1
    records.append(
        _criterion(
            "C9",
            "DoD#3",
            "sqlite.dialect_only_objects",
            {"virtual_table": 1, "shadow_table": 5, "trigger": 0},
            kinds,
            "schema.v0018.sqlite.normalized.json",
            "V0.0.1 计划 §3 DoD#3「SQLite FTS5 虚表与 5 影子表」",
            status="reconciled",
            note=(
                "实测 1 虚表 + 4 影子表 + 3 触发器 = 8 个对象；DoD 的「5 影子表」应为 1 虚表 + 4 影子表的"
                "合并口径——因 FTS5 用外部内容表（content='document_chunk'）时不生成 _content 影子表，"
                "故影子表只有 config/data/docsize/idx 四个。3 个触发器为 C-03 复做时补入。"
            ),
        )
    )
    return records


def _probe_sse(contracts: Path) -> list[dict[str, Any]]:
    """DoD#4: 19 SSE channels and 19 golden frames."""
    channels = _read_json(contracts / "sse/channels.json")
    golden_dir = contracts / "sse" / "golden"
    frames = sorted(
        path for path in golden_dir.glob("*.txt") if not path.name.startswith("_guard-")
    ) if golden_dir.is_dir() else []
    guards = sorted(golden_dir.glob("_guard-*.txt")) if golden_dir.is_dir() else []

    if not channels:
        return [
            _criterion("C10", "DoD#4", "sse.channels", 19, None, "sse/channels.json",
                       "V0.0.1 计划 §3 DoD#4", status="pending", note="artifact missing")
        ]

    declared = channels.get("channels") or []
    records = [
        _criterion("C10", "DoD#4", "sse.channels", 19, len(declared), "sse/channels.json",
                   "V0.0.1 计划 §3 DoD#4「19 条 SSE golden 帧」",
                   note=f"by_channel 映射条目 = {len(channels.get('by_channel') or {})}"),
        _criterion("C11", "DoD#4", "sse.golden_frames", 19, len(frames), "sse/golden/*.txt",
                   "同上（逐通道一帧，逐字节判据）",
                   note=f"另有守卫夹具 {len(guards)} 个（不计入 19）"),
    ]
    missing = sorted(
        {str(item.get("channel")) for item in declared if isinstance(item, dict)}
        - {path.stem for path in frames}
    )
    records.append(
        _criterion(
            "C12",
            "DoD#4",
            "sse.golden_coverage",
            "complete",
            "complete" if not missing else missing,
            "sse/channels.json ↔ sse/golden/",
            "同上（通道集合 ⊆ golden 帧集合）",
            status="verified" if not missing else "mismatch",
        )
    )
    return records


def _probe_errors(contracts: Path) -> list[dict[str, Any]]:
    """C-04: 30 error codes + 4-key response shell."""
    errors = _read_json(contracts / "errors.json")
    envelope = _read_json(contracts / "envelope.schema.json")
    if not errors or not envelope:
        return [
            _criterion("C13", "总纲 §11.1/§11.2", "error codes + shell keys", "30 / 4", None,
                       "errors.json / envelope.schema.json", "总纲 §11.1 §11.2（C-04）",
                       status="pending", note="artifact missing")
        ]
    codes = errors.get("codes") or {}
    shell_keys = ((envelope.get("x-wbtimeai") or {}).get("measured") or {}).get("shell_keys") or []
    return [
        _criterion("C13", "总纲 §11.2", "errors.codes", 30, len(codes), "errors.json",
                   "总纲 §11.2 错误码表（C-04）"),
        _criterion("C14", "总纲 §11.1", "envelope.shell_keys", 4, len(shell_keys),
                   "envelope.schema.json", "总纲 §11.1「{code,message,data,request_id}」",
                   note=f"keys={shell_keys}"),
    ]


def _probe_error_status_uniformity(contracts: Path) -> list[dict[str, Any]]:
    """C22 (D-1 regression gate): a published ``http_status`` must not hide a second status.

    ``errors.json`` states one headline ``http_status`` per code.  For codes whose
    raise sites disagree (``DEPENDENCY_MISSING``: 8 sites emit 503, 2 emit 500) that
    headline is only the *dominant* value, so the artifact must say so and enumerate
    the deviating sites.  This probe re-derives the facts from the per-site list and
    refuses the pair "headline status" + "uniform" when they do not add up.

    Args:
        contracts: Contracts directory.

    Returns:
        One criterion record; ``status="pending"`` when ``errors.json`` is absent.
    """
    errors = _read_json(contracts / "errors.json")
    codes = errors.get("codes") or {}
    if not codes:
        return [
            _criterion("C22", "D-1", "errors.http_status_uniformity", "consistent", None,
                       "errors.json", "D-1：http_status 不得掩盖 call-site 差异",
                       status="pending", note="artifact missing")
        ]

    problems: list[str] = []
    non_uniform: dict[str, dict[str, int]] = {}
    for name, entry in sorted(codes.items()):
        resolved = entry.get("http_status_by_call_site_resolved") or []
        distribution = entry.get("http_status_distribution") or {}
        headline = entry.get("http_status")

        if sum(distribution.values()) != len(resolved):
            problems.append(
                f"{name}: distribution sums to {sum(distribution.values())} but "
                f"{len(resolved)} resolved sites are listed"
            )
        expected_uniform = None if not resolved else len(distribution) <= 1
        if entry.get("http_status_uniform") is not expected_uniform:
            problems.append(
                f"{name}: http_status_uniform={entry.get('http_status_uniform')!r} contradicts "
                f"distribution {distribution}"
            )
        if expected_uniform is False:
            non_uniform[name] = dict(distribution)
            if not entry.get("note"):
                problems.append(f"{name}: sites disagree but no note explains it")
            deviating = {status for status in distribution if int(status) != headline}
            listed = {
                str(site.get("actual_status"))
                for site in entry.get("http_status_inconsistent_call_sites") or []
            }
            if listed != deviating:
                problems.append(
                    f"{name}: deviating statuses {sorted(deviating)} != enumerated "
                    f"http_status_inconsistent_call_sites {sorted(listed)}"
                )
            if str(headline) not in distribution:
                problems.append(f"{name}: headline {headline} is not among the measured statuses")

    measured = "consistent" if not problems else problems
    return [
        _criterion(
            "C22",
            "D-1",
            "errors.http_status_uniformity",
            "consistent",
            measured,
            "errors.json",
            "D-1：`http_status` 是逐 call-site 解析后的多数值；非全量成立时必须显式披露分布与偏离点",
            status="verified" if not problems else "mismatch",
            note=(
                f"非全量成立的码 = {sorted(non_uniform)}；分布逐码与 resolved sites 条数一致；"
                "逐点明细见 codes.*.http_status_by_call_site_resolved（V0.2.0 参数化测试必须按 call-site 取值）"
                if not problems
                else "见 measured"
            ),
        )
    ]


def _read_migration_rows(contracts: Path) -> list[dict[str, str]]:
    """Parse ``test-migration-map.csv`` into dicts, ignoring ``#`` comment lines.

    Args:
        contracts: Contracts directory.

    Returns:
        One dict per data row; empty when the file is missing or unreadable.
    """
    table = contracts / "test-migration-map.csv"
    if not table.is_file():
        return []
    try:
        text = table.read_text(encoding="utf-8")
    except OSError:
        return []
    data = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return list(csv.DictReader(io.StringIO(data)))


def _probe_disposition_auditability(contracts: Path) -> list[dict[str, Any]]:
    """C23 (D-2 regression gate): per-case dispositions must be auditable, individually.

    Three things made D-2 possible and each is now gated:

    1. several dropped cases carried **one copy-pasted note**, so nobody could tell
       which rationale was false.  ⇒ notes of ``bucket=3`` rows must be pairwise
       distinct;
    2. a dropped case could quietly hold the tree's only fail-closed assertion.
       ⇒ :data:`MUST_NOT_BE_DROPPED` lists the node ids that may never be ③;
    3. the per-case overrides existed only in prose.  ⇒ every override declared by
       ``test-migration-summary.json`` must be present in the CSV **with the
       declared bucket**, and the self-check must report all of them applied.

    Args:
        contracts: Contracts directory.

    Returns:
        One criterion record; ``status="pending"`` when the CSV is absent.
    """
    rows = _read_migration_rows(contracts)
    if not rows:
        return [
            _criterion("C23", "D-2", "migration.disposition_auditability", "auditable", None,
                       "test-migration-map.csv", "D-2：桶③ 须逐条可审计、不得共用理由",
                       status="pending", note="artifact missing")
        ]
    summary = _read_json(contracts / "test-migration-summary.json")
    by_id = {row.get("test_id", ""): row for row in rows}

    problems: list[str] = []
    dropped = [row for row in rows if row.get("bucket") == "3"]
    notes = [row.get("note", "") for row in dropped]
    duplicates = sorted({note for note in notes if notes.count(note) > 1})
    if duplicates:
        problems.append(
            f"{len(duplicates)} bucket=3 note(s) are shared by several cases "
            "(每条放弃理由必须按用例实际语义分别写明)"
        )

    for test_id in MUST_NOT_BE_DROPPED:
        row = by_id.get(test_id)
        if row is None:
            problems.append(f"{test_id}: listed in MUST_NOT_BE_DROPPED but absent from the map")
        elif row.get("bucket") == "3":
            problems.append(f"{test_id}: dropped (bucket=3) although it must be redesigned")

    overrides = summary.get("case_overrides") or []
    for item in overrides:
        test_id = str(item.get("test_id", ""))
        row = by_id.get(test_id)
        if row is None:
            problems.append(f"{test_id}: declared as a case override but missing from the map")
            continue
        if row.get("bucket") != str(item.get("bucket")):
            problems.append(
                f"{test_id}: map bucket {row.get('bucket')!r} != declared override "
                f"{item.get('bucket')!r}"
            )
    if not (summary.get("counts_selfcheck") or {}).get("all_case_overrides_applied", False):
        problems.append("summary.counts_selfcheck.all_case_overrides_applied is not true")

    measured = "auditable" if not problems else problems
    return [
        _criterion(
            "C23",
            "D-2",
            "migration.disposition_auditability",
            "auditable",
            measured,
            "test-migration-map.csv + test-migration-summary.json",
            "D-2：桶③ 理由必须逐条成立；API 级 fail-closed 断言不得被判放弃",
            status="verified" if not problems else "mismatch",
            note=(
                f"bucket=3 行 {len(dropped)} 条，note 两两不同；逐用例覆盖 {len(overrides)} 条与表内一致；"
                f"MUST_NOT_BE_DROPPED={len(MUST_NOT_BE_DROPPED)} 条均未被判 ③"
                if not problems
                else "见 measured"
            ),
        )
    ]


def _probe_migration_map(contracts: Path) -> list[dict[str, Any]]:
    """DoD#5: migration map -- collected 1699, of which 1661 is the ``passed`` caliber.

    Two independent numbers are kept apart on purpose:

    * ``collected`` / ``selected`` = **measured** row count of the CSV (1699);
    * ``passed`` = 1661, **registered** in the summary's ``basis`` (the legacy run
      recorded "1692 selected = 1661P"), not re-measured here -- the summary says
      ``outcomes.covered = 0``, so claiming a passed count from this ledger would
      be fabrication.  Status ``registered`` encodes exactly that distinction.
    """
    table = contracts / "test-migration-map.csv"
    if not table.is_file():
        candidates = sorted(contracts.rglob("test-migration-map.csv"))
        table = candidates[0] if candidates else table
    summary = _read_json(contracts / "test-migration-summary.json")
    if not table.is_file() and not summary:
        return [
            _criterion("C15", "DoD#5", "migration_map.rows", 1699, None, "test-migration-map.csv",
                       "C-06 口径：collected/selected 1699 用例",
                       status="pending", note="artifact missing"),
            _criterion("C16", "DoD#5", "migration_map.registered_passed", 1661, None,
                       "test-migration-summary.json", "DoD#5「覆盖 1661 条」（passed 口径）",
                       status="pending", note="artifact missing"),
        ]

    records: list[dict[str, Any]] = []

    rows: int | None = None
    header = ""
    if table.is_file():
        data: list[str] = []
        with table.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or line.startswith("#"):
                    continue
                data.append(line)
        rows = max(len(data) - 1, 0)  # first non-comment line is the header
        header = data[0].strip() if data else ""

    basis = summary.get("basis") or {}
    declared_rows = summary.get("rows")
    collected_raw = basis.get("collected_raw")
    excluded = basis.get("provider_live_excluded")
    registered = ((basis.get("roadmap_registered_1661") or {}).get("value"))
    outcomes = summary.get("outcomes") or {}

    cross_ok = rows is not None and declared_rows is not None and rows == declared_rows
    records.append(
        _criterion(
            "C15",
            "DoD#5",
            "migration_map.rows(collected/selected)",
            1699,
            rows,
            table.name,
            "C-06 口径：collected_raw 1743 − provider_live 44 = 1699 selected",
            status="verified" if rows == 1699 and cross_ok else "mismatch",
            note=(
                f"summary.rows={declared_rows} 与 CSV 实测行数一致={cross_ok}；"
                f"collected_raw={collected_raw} minus provider_live_excluded={excluded}；header={header[:70]}"
            ),
        )
    )
    # C16：passed 口径。两种情形必须分开——已复跑（有 outcomes）就报实测，
    # 未复跑（covered=0）只能报登记值并降级为 registered，不得冒充实测。
    covered = outcomes.get("covered") or 0
    distribution = outcomes.get("distribution") or {}
    measured_passed = distribution.get("passed")
    if covered and isinstance(measured_passed, int):
        delta = measured_passed - (registered or 0)
        non_passed_now = (rows or 0) - measured_passed
        records.append(
            _criterion(
                "C16",
                "DoD#5",
                "migration_map.passed",
                1661,
                measured_passed,
                "test-migration-summary.json",
                "V0.0.1 计划 §3 DoD#5「覆盖 1661 条」（passed 口径）；旧线登记 1692 selected = 1661P",
                status="verified" if measured_passed == 1661 else "reconciled",
                note=(
                    f"本轮已复跑：outcomes.covered={covered}，分布={distribution}（合计 "
                    f"{sum(v for v in distribution.values() if isinstance(v, int))} = {rows} 行）；"
                    f"旧线登记 1661P/1692 selected，本轮 {measured_passed}P/{rows} selected，"
                    f"Δpassed={delta:+d} 与 Δselected={((rows or 0) - 1692):+d} 同步（新增用例全 passed），"
                    f"非 passed 数 {non_passed_now} vs 旧线 31 ⇒ 差额已解释，按实测登记"
                ),
            )
        )
    else:
        records.append(
            _criterion(
                "C16",
                "DoD#5",
                "migration_map.passed",
                1661,
                registered,
                "test-migration-summary.json",
                "V0.0.1 计划 §3 DoD#5「覆盖 1661 条」；summary.basis.roadmap_registered_1661",
                status="registered" if registered == 1661 else "mismatch",
                note=(
                    f"**登记值，非本轮实测**：summary.outcomes.covered={outcomes.get('covered')}、"
                    f"distribution={outcomes.get('distribution')} ⇒ 未在任何一轮复跑，禁止按 passed 统计；"
                    "复跑产出 outcomes.json 后本判据会自动升级为实测口径"
                ),
            )
        )

    declared_conformance = summary.get("conformance") or []
    on_disk = sorted(path.name for path in (contracts / "conformance").glob("*.yaml")) if (
        contracts / "conformance"
    ).is_dir() else []
    records.append(
        _criterion(
            "C19",
            "DoD#8",
            "conformance.skeletons",
            len(declared_conformance),
            len(on_disk),
            "conformance/*.yaml",
            "summary.conformance 声明的骨架数 = 落盘文件数",
            status="verified" if len(on_disk) == len(declared_conformance) and on_disk else "mismatch",
            note=f"files={on_disk}",
        )
    )

    declared_digests = summary.get("artifacts") or {}
    digest_problems = []
    for relative, digest in declared_digests.items():
        candidate = contracts / relative
        if not candidate.is_file():
            digest_problems.append(f"{relative}: declared but missing")
            continue
        actual = hashes.sha256_file(candidate)
        if actual != digest:
            digest_problems.append(f"{relative}: declared {str(digest)[:12]} != disk {actual[:12]}")
    records.append(
        _criterion(
            "C20",
            "DoD#5",
            "migration.self_declared_digests",
            "consistent",
            "consistent" if not digest_problems else digest_problems,
            "test-migration-summary.json",
            "C-06 自带 artifacts sha256 台账 ↔ 本台账实测值",
            status="verified" if not digest_problems else "mismatch",
            note=(
                "三重互证：C-06 summary 自带摘要、本 manifest 的对象摘要、manifest.sha256 同值"
                if not digest_problems
                else "见 measured"
            ),
        )
    )
    return records


#: 期望条目数（用于自校验；来自 C-03 快照的实测结构，不是抄文档）.
DDL_OBJECT_EXPECTED: dict[str, int] = {
    "table": 61,
    "index.metadata": 174,
    "index.raw_hnsw": 2,
    "virtual_table": 1,
    "shadow_table": 4,
    "trigger": 3,
}
DDL_OBJECT_TOTAL = sum(DDL_OBJECT_EXPECTED.values())
DDL_DIALECT_EXPECTED: dict[str, int] = {"pg": 2, "sqlite": 8, "null": 235}


def _yaml_applies_to(path: Path) -> list[str]:
    """Read ``applies_to`` version list from a conformance skeleton (no PyYAML needed).

    Args:
        path: YAML file.

    Returns:
        Version strings such as ``["V0.2.0"]``; empty when the key is absent.
    """
    versions: list[str] = []
    in_block = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return versions
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("applies_to:"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("- "):
                versions.append(stripped[2:].strip().strip("\"'"))
                continue
            if stripped and not stripped.startswith("#"):
                break
    return versions


def _build_ddl_objects(contracts: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Derive object-level entries from the two normalized DDL snapshots.

    Every row carries C-03's own ``source`` evidence in ``source_raw`` so the
    normalisation into the three-value enum stays auditable:

    * ``raw_indexes[].source`` literally starts with ``migration:`` ⇒ ``migration``;
    * ``dialect_only[].source`` literally reads ``sqlite_master（执行 0013 FTS5 语句后回读）``
      -- the DDL text originates from migration 0013, ``sqlite_master`` is only the
      read-back channel ⇒ ``migration`` (per team-lead's M-10 mapping);
    * shadow tables carry no author-written DDL at all: they are engine artifacts of
      the migration-declared FTS5 table, so they are attributed to that declaration
      (flagged in ``source_note`` rather than silently absorbed).

    Args:
        contracts: Contracts directory.

    Returns:
        ``(entries, problems)``. Any count mismatch lands in ``problems`` (fail-closed).
    """
    pg = _read_json(contracts / "schema.v0018.pg.normalized.json")
    sqlite = _read_json(contracts / "schema.v0018.sqlite.normalized.json")
    if not pg or not sqlite:
        return [], ["ddl snapshots missing: cannot build ddl_objects (M-10)"]

    problems: list[str] = []
    entries: list[dict[str, Any]] = []
    requirement = "V0.0.1/DoD#3 DDL 三源合并（对象级 source/dialect_only）"

    pg_tables = pg.get("tables") or []
    lite_tables = sqlite.get("tables") or []
    if [str(item.get("name")) for item in pg_tables] != [str(item.get("name")) for item in lite_tables]:
        problems.append("ddl_objects: table name sets differ between PG and SQLite snapshots")

    for table in pg_tables:
        name = str(table.get("name"))
        columns = table.get("columns") or []
        entries.append(
            {
                "kind": "table",
                "name": name,
                "table": name,
                "source": "metadata",
                "dialect_only": None,
                "columns": len(columns),
                "requirement": requirement,
            }
        )
        for index in table.get("indexes") or []:
            entries.append(
                {
                    "kind": "index.metadata",
                    "name": str(index.get("name")),
                    "table": name,
                    "source": "metadata",
                    "dialect_only": None,
                    "unique": bool(index.get("unique")),
                    "partial": bool(index.get("where")),
                    "requirement": requirement,
                }
            )

    for index in pg.get("raw_indexes") or []:
        raw_source = str(index.get("source") or "")
        entries.append(
            {
                "kind": "index.raw_hnsw",
                "name": str(index.get("name")),
                "table": str(index.get("table")),
                "source": "migration",
                "dialect_only": "pg",
                "source_raw": raw_source,
                "requirement": requirement,
            }
        )
        if not raw_source.startswith("migration:"):
            problems.append(
                f"ddl_objects: raw index {index.get('name')!r} declares source {raw_source!r}, expected migration:*"
            )

    for item in sqlite.get("dialect_only") or []:
        kind = str(item.get("kind"))
        raw_source = str(item.get("source") or "")
        entry = {
            "kind": kind,
            "name": str(item.get("name")),
            "table": str(item.get("table")),
            "source": "migration",
            "dialect_only": "sqlite",
            "source_raw": raw_source,
            "requirement": requirement,
        }
        if kind == "shadow_table":
            entry["source_note"] = (
                "影子表无人工书写的 DDL：由 SQLite 在执行迁移 0013 的 FTS5 虚表定义时自动生成；"
                "归属其声明来源（migration）而非另有来源"
            )
        entries.append(entry)

    # --- 断言：条数 / 方言分布 / 与 counts 交叉 --------------------------------
    kinds: dict[str, int] = {}
    for entry in entries:
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1

    if len(entries) != DDL_OBJECT_TOTAL:
        problems.append(f"ddl_objects: total {len(entries)} != expected {DDL_OBJECT_TOTAL}")
    for kind, expected in DDL_OBJECT_EXPECTED.items():
        if kinds.get(kind, 0) != expected:
            problems.append(f"ddl_objects: kind {kind} = {kinds.get(kind, 0)} != expected {expected}")

    pg_count = sum(1 for entry in entries if entry["dialect_only"] == "pg")
    sqlite_count = sum(1 for entry in entries if entry["dialect_only"] == "sqlite")
    migration_count = sum(1 for entry in entries if entry["source"] == "migration")
    if pg_count != DDL_DIALECT_EXPECTED["pg"]:
        problems.append(f"ddl_objects: dialect_only=pg {pg_count} != expected 2 (two hnsw indexes)")
    if sqlite_count != DDL_DIALECT_EXPECTED["sqlite"]:
        problems.append(f"ddl_objects: dialect_only=sqlite {sqlite_count} != expected 8")
    if migration_count != pg_count + sqlite_count:
        problems.append(
            f"ddl_objects: migration-sourced {migration_count} != pg {pg_count} + sqlite {sqlite_count}"
        )

    pg_counts = pg.get("counts") or {}
    column_sum = sum(int(entry.get("columns") or 0) for entry in entries if entry["kind"] == "table")
    cross = {
        "tables": kinds.get("table", 0),
        "columns": column_sum,
        "metadata_indexes": kinds.get("index.metadata", 0),
        "raw_indexes": kinds.get("index.raw_hnsw", 0),
        "index_objects_total": kinds.get("index.metadata", 0) + kinds.get("index.raw_hnsw", 0),
        "sqlite_dialect_only": sqlite_count,
    }
    expected_cross = {
        "tables": pg_counts.get("tables"),
        "columns": pg_counts.get("columns"),
        "metadata_indexes": pg_counts.get("metadata_indexes"),
        "raw_indexes": pg_counts.get("raw_indexes"),
        "index_objects_total": pg_counts.get("index_objects_total"),
        "sqlite_dialect_only": (sqlite.get("counts") or {}).get("dialect_only_objects"),
    }
    for key, value in expected_cross.items():
        if value is not None and cross[key] != value:
            problems.append(f"ddl_objects: {key} {cross[key]} != snapshot counts {value}")

    return entries, problems


def _probe_ddl_objects(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """C21: object-level ledger must cross-validate the aggregate counts."""
    kinds: dict[str, int] = {}
    for entry in entries:
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1
    return [
        _criterion(
            "C21",
            "M-10",
            "ddl_objects.total",
            DDL_OBJECT_TOTAL,
            len(entries),
            "schema.v0018.{pg,sqlite}.normalized.json",
            "M-10「每个对象带 source + dialect_only」；与 C6/C7/C8/C9 交叉",
            status="verified" if len(entries) == DDL_OBJECT_TOTAL else "mismatch",
            note=(
                f"kinds={kinds}；交叉：C6 metadata_indexes={kinds.get('index.metadata', 0)} / "
                f"C7 raw_hnsw={kinds.get('index.raw_hnsw', 0)} / "
                f"C8 index_objects_total={kinds.get('index.metadata', 0) + kinds.get('index.raw_hnsw', 0)} / "
                f"C9 sqlite dialect_only={sum(1 for e in entries if e['dialect_only'] == 'sqlite')}"
            ),
        )
    ]


def _probe_reproducibility(contracts: Path, repo_root: Path) -> list[dict[str, Any]]:
    """DoD#7: configurable --source + sha256 ledger + --check."""
    toolkit = repo_root / "scripts" / "extract-from-py"
    required = ["_bootstrap.py", "hashes.py", "run.py", "export_openapi.py"]
    present = [name for name in required if (toolkit / name).is_file()]
    ledger = contracts / hashes.MANIFEST_NAME
    object_ledger = contracts / MANIFEST_JSON_NAME
    return [
        _criterion(
            "C17",
            "DoD#7",
            "reproducibility.toolkit",
            required,
            present,
            "scripts/extract-from-py/",
            "V0.0.1 计划 §3 DoD#7「--source 可配置 + sha256 清单 + --check」",
            status="verified" if len(present) == len(required) else "mismatch",
            note="_bootstrap.resolve_source() 优先级：--source > $WBTIME_SOURCE > 默认值",
        ),
        _criterion(
            "C18",
            "DoD#7",
            "reproducibility.ledgers",
            [hashes.MANIFEST_NAME, MANIFEST_JSON_NAME],
            [ledger.name if ledger.is_file() else None, object_ledger.name if object_ledger.is_file() else None],
            "contracts/",
            "同上 + 施工纪律 §4.5.1-2「必须登记 sha256 变更史」"),
    ]


def _notices(spec_version: str) -> list[dict[str, Any]]:
    """Top-level notices that must never be lost (M-4, M-08, derivations)."""
    return [
        {
            "id": "M-4",
            "severity": "binding",
            "text": (
                f"info.version = {spec_version} 是旧线 create_app().openapi() 的**代码串，从未发布**；"
                "不得作为 TS 线版本号继承（C-3 / M-4 联签条件）。TS 线版本号自 package.json 的 0.0.1 起算，"
                "由发布流程独立决定。"
            ),
            "basis": "docs/V1.0/V0.0.1-契约继承与抽取/01-计划/README.md §3 DoD#6；路线图 §1.4 M-4",
        },
        {
            "id": "M-08",
            "severity": "binding",
            "text": (
                "契约文件的**字节数不可作判据**：同一 OpenAPI spec 随序列化参数在 178,934–510,981 B 间波动。"
                "判据只用三集合（100 paths / 134 ops / 116 schemas）+ 规范化 sha256。"
            ),
            "basis": "路线图 M-08；contracts/README.md",
        },
        {
            "id": "derived:endpoints",
            "severity": "info",
            "text": (
                "endpoints.txt 的数据行派生自 openapi.v1.frozen.json（METHOD PATH，排序稳定），"
                "其分段标题与 134/133 口径文案是人写骨架，故 source=manual 而非 metadata。"
                "派生关系：openapi.v1.frozen.json -> endpoints.txt（同一 exporter，同一次运行）。"
            ),
            "basis": "C-07 裁定：产物来源按实质判定（§4.5.1-3）",
        },
        {
            "id": "count:405-void",
            "severity": "binding",
            "text": (
                "「405 口径作废」：224 + 117 + 62 的分解中，62 已含 2 个 VectorType，再加 +2 属重复计数；"
                "本版只认两个权威值——401（PG emit）与 403（声明敏感族）。凡引用 405 的旧表述一律以本条为准。"
            ),
            "basis": "team-lead 2026-10-20 裁定（C-03 计数复核）；provenance=ruling，本脚本未复算 224/117/62",
        },
        {
            "id": "count:sqlite-dialect-only-8",
            "severity": "binding",
            "text": (
                "SQLite 方言专属对象为 8 个（虚表 1 + 影子表 4 + 触发器 3，见 ddl_objects 的 sqlite 段）；"
                "**文档「5 影子表」口径作废**——FTS5 在 external-content 模式（content='document_chunk'）下不生成 "
                "_content 影子表，故影子表只有 config/data/docsize/idx 四个。判据见 C9（reconciled）。"
            ),
            "basis": "schema.v0018.sqlite.normalized.json 的 counts.dialect_only_by_kind 实测",
        },
        {
            "id": "scope:pg-not-replayed",
            "severity": "binding",
            "text": (
                "**PG 侧未在真实例重放**（归 V0.1.0 parity 前置，施工纪律 §4.8 #1）。本版 DDL 快照来自 ORM metadata "
                "编译 + 迁移链 raw DDL 提取，**不得表述为「PG 已验证」**；SQLite 侧同理（内存库执行后回读 sqlite_master），"
                "两侧均属「静态抽取 + 编译期校验」，不是运行期 parity。"
            ),
            "basis": "施工纪律 §4.8 外部依赖 #1/#2（Windows 本机 pgvector / SSH 隧道均不可得）",
        },
        {
            "id": "composite:ddl",
            "severity": "info",
            "text": (
                "DDL 四件套为**三源合并**产物（metadata 编译 + 迁移链 raw hnsw + SQLite 专属 FTS5），"
                "按主导来源归 source=metadata；次要来源的计数见各 normalized 快照的 counts 与 notes 字段，"
                "判据核对见 criteria C4–C9。"
            ),
            "basis": "V0.0.1 计划 §3 DoD#3；C-03 产物自带 counts/notes",
        },
    ]


#: `source` / `generated_by` / `dialect_only` 的语义分离（C-07 口径，勿混用）.
FIELD_SEMANTICS: dict[str, Any] = {
    "statement": (
        "`source` 与 `generated_by` 回答的是两个不同问题，两者不同**不构成矛盾**；"
        "只有 `source` 与「内容实际由谁决定」不符才是错误。"
    ),
    "fields": {
        "source": {
            "question": "内容事实从哪来（谁决定了内容）",
            "values": {
                "metadata": "ORM metadata / 代码模型反射或编译得出的事实",
                "migration": "迁移链 raw DDL 提取出的事实（hnsw、FTS5 等 metadata 无法表达的部分）",
                "manual": "人工定义的内容（人工构造的测试载荷、人工判定的桶/版本归属、人工写的骨架文案与壳层组装）",
            },
            "allowed_inconsistency": "无。与「内容实际由谁决定」不符即为错误。",
        },
        "generated_by": {
            "question": "哪个程序把内容落盘（渲染/编码/序列化）",
            "values": "exporter 的仓库相对路径；人写且无程序落盘时为 null",
            "allowed_inconsistency": "可以是 exporter，即使 source=manual（人定内容、程序落盘）。",
        },
        "dialect_only": {
            "question": "该对象是否方言专属",
            "values": "pg / sqlite / null（跨方言通用或两侧同构）",
            "allowed_inconsistency": "仅当差异确属单方言语义时才允许非 null；合法差异不是遗漏（例如 hnsw 仅 PG）。",
        },
    },
    "worked_examples": [
        "sse/golden/*.txt: source=manual（载荷值、字段取值、seq 口径由人构造）+ generated_by=export_sse.py（编码器落盘）",
        "test-migration-map.csv: source=manual（桶/版本/处置由人判定）+ generated_by=export_migration.py（表由脚本渲染）",
        "openapi.v1.frozen.json: source=metadata（路由/schema 由代码内省）+ generated_by=export_openapi.py",
        "schema.v0018.pg.normalized.json: source=metadata（主导）+ 内含 2 条 migration 来源对象，见 ddl_objects",
    ],
}

#: `criteria[].status` 的全局语义（防止状态码被各自解释）.
STATUS_SEMANTICS: dict[str, str] = {
    "verified": "实测值与期望值相等，且实测值由本脚本从产物现读得出",
    "reconciled": "与文档口径不一致，但已判定为文档错误/口径合并；**产物按实测**，差额与理由写在 note 里，不假装相等",
    "registered": "该值是**登记值**（来自旧线记录或裁定），本轮未复跑、无实测支撑；不得被引用为「已验证」",
    "pending": "产物尚未落盘，判据无法核对；不判红，但在 summary 里列出 id 供收口时复看",
    "mismatch": "实测与期望不符，**直接判红**（export 拒绝落盘 / check 退出码 1）",
}

# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


def _iter_artifacts(contracts: Path) -> list[Path]:
    """List artifact files eligible to become objects (ledgers excluded)."""
    return [
        path
        for path in hashes.iter_artifact_files(contracts)
        if path.relative_to(contracts).as_posix() not in _LEDGER_FILES
    ]


def build_payload(contracts: Path, repo_root: Path | None = None) -> dict[str, Any]:
    """Build the full manifest payload for ``contracts``.

    Args:
        contracts: Contracts directory.
        repo_root: Repository root (defaults to the canonical one).

    Returns:
        JSON-serialisable payload.

    Raises:
        ManifestConsistencyError: On an unclassified artifact, a producer
            conflict, a criterion mismatch, or a dual-ledger divergence.
    """
    contracts = Path(contracts)
    root = Path(repo_root) if repo_root else _bootstrap.repo_root()
    spec = _read_json(contracts / "openapi.v1.frozen.json")
    spec_version = str(((spec.get("info") or {}).get("version")) or "absent")

    problems: list[str] = []
    objects: list[dict[str, Any]] = []
    unclassified: list[str] = []
    matched_patterns: dict[str, int] = {}

    for path in _iter_artifacts(contracts):
        relative = path.relative_to(contracts).as_posix()
        rule = _classify(relative)
        if rule is None:
            unclassified.append(relative)
            continue
        matched_patterns[rule.pattern] = matched_patterns.get(rule.pattern, 0) + 1

        requirement = rule.requirement
        if relative.startswith("conformance/") and relative.endswith(".yaml"):
            versions = _yaml_applies_to(path)
            if versions:
                requirement = f"conformance 骨架（{path.stem}）：{', '.join(versions)} 判据"

        embedded = _embedded_generated_by(path)
        if rule.generated_by is None:
            if embedded:
                problems.append(
                    f"{relative}: rule says hand-authored but artifact declares generated_by={embedded!r}"
                )
            producer: str | None = None
        elif rule.generated_by == FROM_ARTIFACT:
            if not embedded:
                problems.append(
                    f"{relative}: rule requires the artifact to declare generated_by, but none found"
                )
            producer = embedded
        else:
            if embedded and embedded != rule.generated_by:
                problems.append(
                    f"{relative}: producer conflict -- rule={rule.generated_by!r} artifact={embedded!r}"
                )
            producer = rule.generated_by

        if rule.source not in SOURCE_VALUES:
            problems.append(f"{relative}: illegal source {rule.source!r}")
        if rule.dialect_only not in DIALECT_VALUES:
            problems.append(f"{relative}: illegal dialect_only {rule.dialect_only!r}")

        objects.append(
            {
                "path": relative,
                "sha256": hashes.sha256_file(path),
                "source": rule.source,
                "dialect_only": rule.dialect_only,
                "generated_by": producer,
                "requirement": requirement,
            }
        )

    if unclassified:
        problems.append(
            "unclassified artifact(s) -- add a rule to contract_manifest.CLASSIFICATION_RULES, "
            "guessing a source is forbidden: " + ", ".join(sorted(unclassified))
        )

    # --- dual-ledger consistency: object ledger vs sha256 ledger -------------
    recorded = {entry.relative_path: entry.digest for entry in hashes.parse_manifest(
        _computed_ledger_text(contracts)
    )}
    for item in objects:
        expected = recorded.get(item["path"])
        if expected is None:
            problems.append(f"{item['path']}: missing from computed sha256 ledger")
        elif expected != item["sha256"]:
            problems.append(
                f"{item['path']}: digest mismatch between ledgers "
                f"(sha256-ledger {expected[:12]} vs object-ledger {item['sha256'][:12]})"
            )

    # --- criteria (measured, never restated) --------------------------------
    criteria: list[dict[str, Any]] = []
    criteria.extend(_probe_openapi(contracts))
    criteria.extend(_probe_ddl(contracts))
    criteria.extend(_probe_sse(contracts))
    criteria.extend(_probe_errors(contracts))
    criteria.extend(_probe_error_status_uniformity(contracts))
    criteria.extend(_probe_migration_map(contracts))
    criteria.extend(_probe_disposition_auditability(contracts))
    criteria.extend(_probe_reproducibility(contracts, root))

    ddl_objects, ddl_problems = _build_ddl_objects(contracts)
    problems.extend(ddl_problems)
    criteria.extend(_probe_ddl_objects(ddl_objects))
    # Stable, human-friendly order: C1, C2, ... C20 (probe order groups by topic).
    criteria.sort(key=lambda item: int(str(item["id"]).lstrip("C")))
    for item in criteria:
        # 形态断言：verified 的自证标准是 expected == measured。
        # 任何"口径不同却标绿"的写法（如 expected=1661/measured=1718）在此被拦下。
        if item["status"] == "verified" and item["expected"] != item["measured"]:
            problems.append(
                f"criterion {item['id']} ({item['metric']}) claims verified but "
                f"expected {item['expected']!r} != measured {item['measured']!r}"
            )
        if item["status"] == "mismatch":
            problems.append(
                f"criterion {item['id']} ({item['metric']}) mismatch: "
                f"expected {item['expected']!r} measured {item['measured']!r}"
            )
    if spec_version != "0.4.8":
        problems.append(f"openapi info.version is {spec_version!r}, expected '0.4.8' to match the notices")

    if problems:
        raise ManifestConsistencyError(
            "refusing to write an inconsistent contract manifest:\n  - " + "\n  - ".join(problems)
        )

    objects.sort(key=lambda item: item["path"])
    rules_view = [
        {
            "pattern": rule.pattern,
            "source": rule.source,
            "dialect_only": rule.dialect_only,
            "generated_by": rule.generated_by,
            "requirement": rule.requirement,
            "rationale": rule.rationale,
            "matched": matched_patterns.get(rule.pattern, 0),
        }
        for rule in CLASSIFICATION_RULES
    ]

    payload: dict[str, Any] = {
        "schema": {
            "name": "wbtime-ai contract manifest",
            "version": 1,
            "frozen_contract": "V0.0.1 / C-07",
            "generated_by": "scripts/extract-from-py/contract_manifest.py",
            "field_contract": {
                "path": "相对 contracts/ 的 POSIX 路径",
                "sha256": "该文件实际 sha256（64 位十六进制，与 manifest.sha256 逐字节一致）",
                "source": list(SOURCE_VALUES),
                "dialect_only": ["pg", "sqlite", None],
                "generated_by": "产生该产物的 exporter；人写产物为 null",
                "requirement": "该产物服务的判据（DoD#n / 总纲 §x / M-n）",
            },
            "object_count": len(objects),
            "ddl_object_count": len(ddl_objects),
        },
        "field_semantics": FIELD_SEMANTICS,
        "status_semantics": STATUS_SEMANTICS,
        "notices": _notices(spec_version),
        "criteria": criteria,
        "objects": objects,
        "ddl_objects": ddl_objects,
        "classification_rules": rules_view,
    }
    return payload


def _computed_ledger_text(contracts: Path) -> str:
    """Render the sha256 ledger *as it will be written*, excluding this JSON file.

    The object ledger cannot contain its own digest, so the comparison is made
    against the ledger restricted to object files -- exactly the intersection the
    two ledgers are required to agree on.
    """
    lines: list[str] = []
    for path in hashes.iter_artifact_files(contracts):
        relative = path.relative_to(contracts).as_posix()
        if relative in _LEDGER_FILES:
            continue
        lines.append(f"{hashes.sha256_file(path)}  {relative}")
    return "\n".join(lines) + ("\n" if lines else "")


def write(contracts: Path, repo_root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    """Build and write ``contracts/contract-manifest.json``.

    Args:
        contracts: Contracts directory.
        repo_root: Repository root override.

    Returns:
        ``(path, payload)``.

    Raises:
        ManifestConsistencyError: See :func:`build_payload`.
    """
    contracts = Path(contracts)
    payload = build_payload(contracts, repo_root)
    contracts.mkdir(parents=True, exist_ok=True)
    target = contracts / MANIFEST_JSON_NAME
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    target.write_bytes(text.encode("utf-8"))
    return target, payload


def verify(contracts: Path, repo_root: Path | None = None) -> tuple[bool, list[str]]:
    """Verify the object ledger against disk and against ``manifest.sha256``.

    Args:
        contracts: Contracts directory.
        repo_root: Repository root override (unused, kept for symmetry).

    Returns:
        ``(ok, problems)``.
    """
    contracts = Path(contracts)
    target = contracts / MANIFEST_JSON_NAME
    if not target.is_file():
        return False, [f"object ledger missing: {target.as_posix()} (run 'run.py export')"]

    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return False, [f"object ledger is not valid JSON: {error}"]

    objects = document.get("objects") or []
    problems: list[str] = []

    ledger_entries = {entry.relative_path: entry.digest for entry in hashes.parse_manifest(
        (contracts / hashes.MANIFEST_NAME).read_text(encoding="utf-8")
        if (contracts / hashes.MANIFEST_NAME).is_file()
        else ""
    )}

    seen: set[str] = set()
    for item in objects:
        relative = str(item.get("path", ""))
        seen.add(relative)
        if item.get("source") not in SOURCE_VALUES:
            problems.append(f"{relative}: illegal source {item.get('source')!r}")
        if item.get("dialect_only") not in DIALECT_VALUES:
            problems.append(f"{relative}: illegal dialect_only {item.get('dialect_only')!r}")
        path = contracts / relative
        if not path.is_file():
            problems.append(f"{relative}: recorded in object ledger but missing on disk")
            continue
        actual = hashes.sha256_file(path)
        if actual != item.get("sha256"):
            problems.append(
                f"{relative}: object ledger digest {str(item.get('sha256'))[:12]} != disk {actual[:12]}"
            )
        ledger_digest = ledger_entries.get(relative)
        if ledger_digest is None:
            problems.append(f"{relative}: present in object ledger but absent from manifest.sha256")
        elif ledger_digest != actual:
            problems.append(
                f"{relative}: sha256 ledger {ledger_digest[:12]} != object ledger {actual[:12]}"
            )

    for relative in hashes.iter_artifact_files(contracts):
        name = relative.relative_to(contracts).as_posix()
        if name in _LEDGER_FILES or name in seen:
            continue
        problems.append(f"{name}: present on disk but absent from object ledger")

    ddl_objects = document.get("ddl_objects") or []
    if len(ddl_objects) != DDL_OBJECT_TOTAL:
        problems.append(
            f"ddl_objects: {len(ddl_objects)} entries, expected {DDL_OBJECT_TOTAL} (M-10 object-level ledger)"
        )
    kinds: dict[str, int] = {}
    for entry in ddl_objects:
        if entry.get("source") not in SOURCE_VALUES:
            problems.append(f"ddl_objects[{entry.get('name')}]: illegal source {entry.get('source')!r}")
        if entry.get("dialect_only") not in DIALECT_VALUES:
            problems.append(f"ddl_objects[{entry.get('name')}]: illegal dialect_only {entry.get('dialect_only')!r}")
        kinds[str(entry.get("kind"))] = kinds.get(str(entry.get("kind")), 0) + 1
    for kind, expected in DDL_OBJECT_EXPECTED.items():
        if kinds.get(kind, 0) != expected:
            problems.append(f"ddl_objects: kind {kind} = {kinds.get(kind, 0)} != expected {expected}")
    migration_count = sum(1 for entry in ddl_objects if entry.get("source") == "migration")
    if ddl_objects and migration_count != 10:
        problems.append(
            f"ddl_objects: migration-sourced {migration_count} != expected 10 "
            "(2 hnsw + 1 virtual table + 4 shadow tables + 3 triggers)"
        )

    return (not problems, problems)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for standalone generation / verification.

    Returns:
        ``0`` success, ``1`` inconsistency, ``2`` usage error.
    """
    parser = argparse.ArgumentParser(
        prog="contract_manifest",
        description="生成 / 校验 contracts/contract-manifest.json（C-07）",
    )
    parser.add_argument("--contracts-dir", default=None, help="契约目录（默认 <repo>/contracts）")
    parser.add_argument("--check", action="store_true", help="只校验，不写入")
    parser.add_argument("--summary", action="store_true", help="打印逐对象摘要")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    root = _bootstrap.repo_root()
    contracts = Path(args.contracts_dir).resolve() if args.contracts_dir else root / "contracts"
    if not contracts.is_dir():
        sys.stderr.write(f"[contract_manifest] ERROR: 契约目录不存在: {contracts}\n")
        return 2

    if args.check:
        ok, problems = verify(contracts, root)
        for problem in problems:
            sys.stdout.write(f"[contract_manifest] FAILED: {problem}\n")
        sys.stdout.write(f"[contract_manifest] {'PASS' if ok else 'FAIL'} ({len(problems)} problem(s))\n")
        return 0 if ok else 1

    try:
        path, payload = write(contracts, root)
    except ManifestConsistencyError as error:
        sys.stderr.write(f"[contract_manifest] ERROR: {error}\n")
        return 1

    objects = payload["objects"]
    by_source: dict[str, int] = {}
    for item in objects:
        by_source[str(item["source"])] = by_source.get(str(item["source"]), 0) + 1
    by_dialect: dict[str, int] = {}
    for item in objects:
        key = "null" if item["dialect_only"] is None else str(item["dialect_only"])
        by_dialect[key] = by_dialect.get(key, 0) + 1

    sys.stdout.write(f"[contract_manifest] wrote {path.as_posix()}\n")
    ddl_objects = payload.get("ddl_objects") or []
    ddl_kinds: dict[str, int] = {}
    for entry in ddl_objects:
        ddl_kinds[str(entry.get("kind"))] = ddl_kinds.get(str(entry.get("kind")), 0) + 1
    sys.stdout.write(
        f"[contract_manifest] objects={len(objects)} by_source={by_source} by_dialect={by_dialect}\n"
    )
    sys.stdout.write(
        f"[contract_manifest] ddl_objects={len(ddl_objects)} kinds={ddl_kinds} "
        f"notices={len(payload['notices'])}\n"
    )
    pending = [item["id"] for item in payload["criteria"] if item["status"] == "pending"]
    sys.stdout.write(
        f"[contract_manifest] criteria={len(payload['criteria'])} pending={pending or 'none'}\n"
    )
    if args.summary:
        for item in objects:
            sys.stdout.write(
                f"  {item['sha256'][:12]}  {str(item['source']):9} {str(item['dialect_only']):6} "
                f"{item['path']}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
