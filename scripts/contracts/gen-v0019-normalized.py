#!/usr/bin/env python3
"""V0.3.0 契约增量 v0019 —— 双档 ``*.normalized.json`` DDL 快照生成器（幂等）。

为什么需要这个脚本
------------------
v0018 的两份 ``schema.v0018.{pg,sqlite}.normalized.json`` 由 py 线 ORM ``metadata``
编译 + 迁移链 raw DDL 合并得到（``scripts/extract-from-py/ddl/export_ddl.py``）。
v0019 是 **TS 线** 增量（``agent_run.stop_reason``，见 ``contracts/v0019.README.md``），
仓内没有可编译的 ORM metadata，故 normalized 快照只能由既有冻结产物派生：

* 结构基线 = v0018 的 normalized 快照（**只读**：不改、不重钉其 sha256）；
* 唯一增量列的 **类型与可空性直接取自冻结的 v0019 ``.sql`` 文本**
  （``schema.v0019.{pg,sqlite}.sql``），而不是由本脚本另写一份类型字面量 ——
  这样「快照」与「冻结 DDL」在生成期就被钉在一起，不可能各说各话；
* ``counts`` 块 **逐项由结构重算**（不是硬编码 ``+1``）：先在 v0018 基线上重算一遍
  并断言与基线自带 counts **整体相等**（校准：证明重算口径对基线成立），再对插入列
  之后的结构重算一次。校准失败即退出 2，绝不落盘。
* 不可从结构复算的计数（``unique_indexes`` / ``partial_indexes`` /
  ``unique_constraints`` / ``extension_statements`` / ``virtual_tables`` /
  ``shadow_tables``）**原样继承** v0018，不在本脚本里重新发明。

幂等性
------
每次执行都以 v0018 为底重建（不读、不累积上一版 v0019），序列化参数固定为
``json.dumps(..., ensure_ascii=False, indent=2) + "\\n"`` —— 与 v0018 产物的字节格式
一致（实测 v0018 两份文件按该参数 round-trip 后字节完全相同）。因此重复执行产出
**字节相同**，``--check`` 只做「生成结果 vs 磁盘字节」比较。

产物
----
* ``contracts/schema.v0019.pg.normalized.json``
* ``contracts/schema.v0019.sqlite.normalized.json``

断言（生成期硬门）
------------------
61 表 / **630 列** / 索引对象 PG 176（174 metadata + 2 hnsw）· SQLite 174 /
PG 侧 ``method == "hnsw"`` 恰好 2；PG 与 SQLite 的表名序列、逐表列名序列与
可空性**逐项相等**；``agent_run.stop_reason`` 双侧都存在。

用法
----
    python scripts/contracts/gen-v0019-normalized.py          # 生成/覆盖 2 个产物
    python scripts/contracts/gen-v0019-normalized.py --check  # 只校验，漂移则退出 1

退出码：``0`` 生成成功 / 与磁盘一致；``1`` ``--check`` 发现漂移；``2`` 输入缺失或
内部断言（校准 / 增量 / 双档一致性）失败。

Python: 仅标准库。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

__all__ = [
    "TARGET_TABLE",
    "TARGET_COLUMN",
    "SCHEMA_VERSION",
    "BASE_SNAPSHOT",
    "TARGET_SNAPSHOT",
    "FROZEN_SQL",
    "build_documents",
    "main",
]

#: 快照文档的类型别名（结构在 ``tables`` / ``counts`` 里嵌套，只做可读性标注）。
MappingLike = dict[str, Any]

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"

#: 本脚本产出的快照版本号（写进 ``schema_version``）。
SCHEMA_VERSION = "v0019"

#: 双档方言标识（与 ``contracts/`` 文件名中的 ``pg`` / ``sqlite`` 一致）。
DIALECTS: tuple[str, ...] = ("pg", "sqlite")

#: 基线（只读）与产物（写入）的文件名模板，相对 ``contracts/``。
BASE_SNAPSHOT = "schema.v0018.{dialect}.normalized.json"
TARGET_SNAPSHOT = "schema.v0019.{dialect}.normalized.json"
FROZEN_SQL = "schema.v0019.{dialect}.sql"

#: 唯一增量：表 / 列，以及插入锚点（列在 SQL 文本里的前一个兄弟列）。
TARGET_TABLE = "agent_run"
TARGET_COLUMN = "stop_reason"
INSERT_AFTER = "error"

#: 生成期硬门（数字来自 DoD#3 的 61 / 629 / 174 + 2 = 176，本轮 +1 列 ⇒ 630）。
EXPECTED_TABLES = 61
EXPECTED_COLUMNS = 630
EXPECTED_HNSW = 2
EXPECTED_INDEX_OBJECTS: dict[str, int] = {"pg": 176, "sqlite": 174}

#: 产物自述的派生链（供审计：谁生成、从哪来）。``generated_by`` 保持 ``null``：
#: 按 ``contract_manifest.FIELD_SEMANTICS``，``generated_by`` 记录的是「内容由哪个
#: exporter 从上游事实派生」，本文件是人登记的增量快照 ⇒ 台账里登记为 ``null``；
#: 落盘者记录在 ``derived_by``，派生输入记录在 ``derived_from``。
DERIVED_BY = "scripts/contracts/gen-v0019-normalized.py"

#: 列定义里终止「类型」部分的修饰词（与 ``check_ddl_parity`` 的解析口径一致）。
_MODIFIER_RE: re.Pattern[str] = re.compile(
    r"\b(?:NOT\s+NULL|NULL|DEFAULT|PRIMARY\s+KEY|REFERENCES|UNIQUE|CHECK|COLLATE|"
    r"CONSTRAINT|GENERATED|AUTOINCREMENT|COMMENT)\b",
    re.IGNORECASE,
)
_NOT_NULL_RE: re.Pattern[str] = re.compile(r"\bNOT\s+NULL\b", re.IGNORECASE)


def _fail(message: str) -> None:
    """Print an error and abort with exit code ``2``.

    Args:
        message: Human-readable reason (Chinese, matching the repo's ledger style).

    Raises:
        SystemExit: Always, with code ``2``.
    """
    print(f"[v0019-normalized] ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def _load_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from ``path``, failing closed on absence or bad shape.

    Args:
        path: File to read (UTF-8).

    Returns:
        The decoded mapping.

    Raises:
        SystemExit: The file is missing, unreadable, not JSON, or not an object.
    """
    if not path.is_file():
        _fail(f"缺少输入 {path.as_posix()}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        _fail(f"无法解析 {path.as_posix()}: {error}")
    if not isinstance(document, dict):
        _fail(f"{path.as_posix()} 不是 JSON 对象")
    return document


def _load_text(path: Path) -> str:
    """Read a UTF-8 text artifact (a leading BOM is tolerated).

    Args:
        path: File to read.

    Returns:
        The decoded text.

    Raises:
        SystemExit: The file is missing or not decodable.
    """
    if not path.is_file():
        _fail(f"缺少输入 {path.as_posix()}")
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        _fail(f"无法读取 {path.as_posix()}: {error}")


def _render(document: MappingLike) -> bytes:
    """Serialise a snapshot exactly the way the v0018 artifacts are serialised.

    Args:
        document: The snapshot document.

    Returns:
        UTF-8 bytes, ``indent=2``, ``ensure_ascii=False``, one trailing newline.
    """
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# 1. counts 重算（口径固定，先在基线上校准）
# ---------------------------------------------------------------------------
def _recompute_counts(document: MappingLike) -> dict[str, Any]:
    """Recompute every counter that is derivable from the snapshot's own structure.

    Args:
        document: A snapshot document with ``tables`` / ``raw_indexes`` /
            ``extensions`` / ``triggers`` / ``dialect_only`` / ``counts``.

    Returns:
        A new ``counts`` mapping: the derivable counters recomputed, every other
        counter inherited unchanged (in its original key order).
    """
    counts: dict[str, Any] = dict(document.get("counts") or {})
    tables: list[MappingLike] = list(document.get("tables") or [])
    raw_indexes: list[MappingLike] = list(document.get("raw_indexes") or [])
    dialect_only: list[MappingLike] = list(document.get("dialect_only") or [])

    metadata_indexes = sum(len(table.get("indexes") or []) for table in tables)

    # 口径与 check_ddl_parity.SchemaEntities.from_normalized 一致：dialect_only 的对象
    # 集合 = 顶层 dialect_only[] 数组 ∪ raw_indexes[]（raw DDL 索引同样是方言专属，
    # PG 侧那 2 条 hnsw 就只出现在 raw_indexes 里、数组为空），按**名字**去重后计数。
    objects_by_name: dict[str, str] = {}
    for entry in dialect_only:
        name = str(entry.get("name") or "")
        if name:
            objects_by_name[name] = str(entry.get("kind") or "unknown")
    for entry in raw_indexes:
        name = str(entry.get("name") or "")
        if name and name not in objects_by_name:
            objects_by_name[name] = "index"
    by_kind: dict[str, int] = {}
    for kind in objects_by_name.values():
        by_kind[kind] = by_kind.get(kind, 0) + 1

    counts["tables"] = len(tables)
    counts["columns"] = sum(len(table.get("columns") or []) for table in tables)
    counts["metadata_indexes"] = metadata_indexes
    counts["raw_indexes"] = len(raw_indexes)
    counts["index_objects_total"] = metadata_indexes + len(raw_indexes)
    counts["foreign_keys"] = sum(len(table.get("foreign_keys") or []) for table in tables)
    counts["extensions"] = len(document.get("extensions") or [])
    counts["triggers"] = len(document.get("triggers") or [])
    counts["dialect_only_objects"] = len(objects_by_name)
    if "dialect_only_by_kind" in counts:
        # 保持基线里的 kind 顺序（无关语义，但能让 v0019 的字节 diff 只落在真实增量上）。
        previous = counts.get("dialect_only_by_kind") or {}
        ordered: dict[str, int] = {
            kind: by_kind[kind] for kind in previous if kind in by_kind
        }
        ordered.update(
            {kind: value for kind, value in by_kind.items() if kind not in ordered}
        )
        counts["dialect_only_by_kind"] = ordered
    return counts


def _calibrate(dialect: str, base: MappingLike) -> None:
    """Prove the recomputation口径 holds on the untouched v0018 baseline.

    If :func:`_recompute_counts` does not reproduce the baseline's own ``counts``
    exactly, the formula is wrong and every downstream number would be wrong with
    it — so this aborts instead of writing a plausible-looking snapshot.

    Args:
        dialect: ``pg`` / ``sqlite`` (for the error message only).
        base: The untouched v0018 snapshot.

    Raises:
        SystemExit: The recomputed counts differ from the baseline's counts.
    """
    stored = base.get("counts") or {}
    recomputed = _recompute_counts(base)
    if recomputed != stored:
        differences = sorted(
            key
            for key in set(stored) | set(recomputed)
            if stored.get(key) != recomputed.get(key)
        )
        detail = ", ".join(
            f"{key}: stored={stored.get(key)!r} recomputed={recomputed.get(key)!r}"
            for key in differences
        )
        _fail(f"{dialect}: counts 重算口径在 v0018 基线上不成立（{detail}）")


# ---------------------------------------------------------------------------
# 2. 增量列：从冻结的 v0019 SQL 文本里取类型与可空性
# ---------------------------------------------------------------------------
def _column_definition(definition: str) -> tuple[str, bool]:
    """Split one column definition into ``(type, nullable)``.

    Args:
        definition: The part of a column line after the column name, e.g.
            ``"VARCHAR(50) NOT NULL DEFAULT 'x'"``.

    Returns:
        The whitespace-collapsed type text and whether the column accepts ``NULL``.
    """
    match = _MODIFIER_RE.search(definition)
    type_text = definition[: match.start()] if match else definition
    return " ".join(type_text.split()), not _NOT_NULL_RE.search(definition)


def _column_from_sql(sql_text: str, *, dialect: str, table: str, column: str) -> dict[str, Any]:
    """Lift one column's type/nullability out of a frozen ``CREATE TABLE`` block.

    Args:
        sql_text: Full ``.sql`` artifact text.
        dialect: ``pg`` / ``sqlite`` (for error messages only).
        table: Table whose ``CREATE TABLE`` block is scanned.
        column: Column to lift.

    Returns:
        A normalized-snapshot column record ``{"name", "type", "nullable", "default"}``.

    Raises:
        SystemExit: The table block or the column is missing / ambiguous.
    """
    pattern = re.compile(
        rf"CREATE\s+TABLE\s+{re.escape(table)}\s*\(\n(?P<body>.*?)\n\);",
        re.DOTALL,
    )
    match = pattern.search(sql_text)
    if match is None:
        _fail(f"{dialect}: schema.v0019.{dialect}.sql 里找不到 CREATE TABLE {table} 块")

    found: list[str] = []
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line or not line.startswith(f"{column} "):
            continue
        found.append(line)
    if len(found) != 1:
        _fail(
            f"{dialect}: {table}.{column} 在冻结 SQL 里出现 {len(found)} 次（期望 1）"
        )

    definition = found[0].rstrip(",").strip()
    tokens = definition.split(None, 1)
    if len(tokens) != 2 or tokens[0] != column:
        _fail(f"{dialect}: 无法解析列定义 {definition!r}")
    type_text, nullable = _column_definition(tokens[1])
    if not type_text:
        _fail(f"{dialect}: {table}.{column} 没有类型（{definition!r}）")
    return {"name": column, "type": type_text, "nullable": nullable, "default": None}


# ---------------------------------------------------------------------------
# 3. 组装一份 v0019 快照
# ---------------------------------------------------------------------------
def _insert_column(document: MappingLike, column: MappingLike) -> None:
    """Insert ``column`` into ``TARGET_TABLE`` right after ``INSERT_AFTER``.

    Args:
        document: The v0019 snapshot being assembled (mutated in place).
        column: The column record to insert.

    Raises:
        SystemExit: The target table / anchor is missing, or the column already
            exists (which would mean the baseline is contaminated).
    """
    tables: list[MappingLike] = list(document.get("tables") or [])
    table = next((item for item in tables if str(item.get("name")) == TARGET_TABLE), None)
    if table is None:
        _fail(f"基线里没有表 {TARGET_TABLE}")
    columns: list[MappingLike] = table.get("columns") or []
    if any(str(item.get("name")) == TARGET_COLUMN for item in columns):
        _fail(f"基线 {TARGET_TABLE} 已存在 {TARGET_COLUMN} —— v0018 基线可能已被污染")
    anchor = next(
        (index for index, item in enumerate(columns) if str(item.get("name")) == INSERT_AFTER),
        None,
    )
    if anchor is None:
        _fail(f"{TARGET_TABLE} 里找不到插入锚点列 {INSERT_AFTER}")
    columns.insert(anchor + 1, dict(column))
    table["columns"] = columns


def _note(dialect: str, column: MappingLike) -> str:
    """Render the provenance note appended to the snapshot's ``notes`` array.

    Args:
        dialect: ``pg`` / ``sqlite``.
        column: The inserted column record.

    Returns:
        One Chinese sentence naming the increment, its source and the caliber.
    """
    nullable = "NULL" if column["nullable"] else "NOT NULL"
    return (
        f"v0019 增量（唯一）：{TARGET_TABLE}.{TARGET_COLUMN} {column['type']} {nullable}，"
        f"类型与可空性取自冻结的 {FROZEN_SQL.format(dialect=dialect)}；"
        f"其余结构、索引、外键、dialect_only 逐项继承 "
        f"{BASE_SNAPSHOT.format(dialect=dialect)}（v0018 一字未改）；"
        f"counts 由本脚本按结构重算（先在 v0018 基线上校准相等后才落盘）"
    )


def _build(dialect: str) -> MappingLike:
    """Assemble one v0019 snapshot for ``dialect``.

    Args:
        dialect: ``pg`` / ``sqlite``.

    Returns:
        The assembled snapshot document (not yet serialised).

    Raises:
        SystemExit: Any input is missing, or calibration / increment assertions fail.
    """
    base_path = CONTRACTS / BASE_SNAPSHOT.format(dialect=dialect)
    sql_path = CONTRACTS / FROZEN_SQL.format(dialect=dialect)
    base = _load_json(base_path)
    sql_text = _load_text(sql_path)

    _calibrate(dialect, base)
    baseline_columns = int((base.get("counts") or {}).get("columns") or -1)

    column = _column_from_sql(sql_text, dialect=dialect, table=TARGET_TABLE, column=TARGET_COLUMN)

    # 注意顺序：先把 calibration 跑完，再动 base 的结构（二者共用同一份内存对象）。
    tables = base.get("tables") or []
    document: MappingLike = {
        "dialect": base.get("dialect"),
        "schema_version": SCHEMA_VERSION,
        "frozen_contract": base.get("frozen_contract"),
        "generated_by": None,
        "derived_by": DERIVED_BY,
        "derived_from": [
            BASE_SNAPSHOT.format(dialect=dialect),
            FROZEN_SQL.format(dialect=dialect),
        ],
        "counts": dict(base.get("counts") or {}),
        "tables": tables,
        "raw_indexes": list(base.get("raw_indexes") or []),
        "extensions": list(base.get("extensions") or []),
        "triggers": list(base.get("triggers") or []),
        "dialect_only": list(base.get("dialect_only") or []),
        "notes": list(base.get("notes") or []),
    }

    _insert_column(document, column)
    document["counts"] = _recompute_counts(document)
    document["notes"] = [*document["notes"], _note(dialect, column)]

    recomputed_columns = int(document["counts"].get("columns") or -1)
    if recomputed_columns != baseline_columns + 1:
        _fail(
            f"{dialect}: 列数 {baseline_columns} -> {recomputed_columns}（期望 +1）"
        )
    return document


# ---------------------------------------------------------------------------
# 4. 双档一致性断言（生成期硬门）
# ---------------------------------------------------------------------------
def _table_by_name(document: MappingLike) -> dict[str, MappingLike]:
    """Index a snapshot's tables by name.

    Args:
        document: A snapshot document.

    Returns:
        Table name -> table record.
    """
    return {str(table.get("name")): table for table in document.get("tables") or []}


def _assert_pair(documents: dict[str, MappingLike]) -> None:
    """Assert the two snapshots agree on every dialect-neutral fact.

    Checked: table name sequence, per-table column name sequence, per-table
    nullability, the aggregate counts, the ``hnsw`` count on PG, and the presence
    of the increment on both sides.

    Args:
        documents: ``{"pg": snapshot, "sqlite": snapshot}``.

    Raises:
        SystemExit: Any assertion fails (all failures are listed in the message).
    """
    pg = documents["pg"]
    sqlite = documents["sqlite"]
    problems: list[str] = []

    pg_tables = _table_by_name(pg)
    sqlite_tables = _table_by_name(sqlite)
    if list(pg_tables) != list(sqlite_tables):
        problems.append(
            "双档表名序列不一致："
            f"pg={len(pg_tables)} / sqlite={len(sqlite_tables)}"
        )
    for name in [item for item in pg_tables if item in sqlite_tables]:
        pg_columns = [
            (str(column.get("name")), bool(column.get("nullable")))
            for column in pg_tables[name].get("columns") or []
        ]
        sqlite_columns = [
            (str(column.get("name")), bool(column.get("nullable")))
            for column in sqlite_tables[name].get("columns") or []
        ]
        if pg_columns != sqlite_columns:
            problems.append(f"{name}: 列名 / 可空性双档不一致")

    for dialect in DIALECTS:
        counts = documents[dialect].get("counts") or {}
        if counts.get("tables") != EXPECTED_TABLES:
            problems.append(f"{dialect}: tables {counts.get('tables')} != {EXPECTED_TABLES}")
        if counts.get("columns") != EXPECTED_COLUMNS:
            problems.append(f"{dialect}: columns {counts.get('columns')} != {EXPECTED_COLUMNS}")
        expected_indexes = EXPECTED_INDEX_OBJECTS[dialect]
        if counts.get("index_objects_total") != expected_indexes:
            problems.append(
                f"{dialect}: index_objects_total {counts.get('index_objects_total')} "
                f"!= {expected_indexes}"
            )

    hnsw = [
        entry
        for entry in pg.get("raw_indexes") or []
        if str(entry.get("method") or "").lower() == "hnsw"
    ]
    if len(hnsw) != EXPECTED_HNSW:
        problems.append(f"pg: hnsw 索引 {len(hnsw)} 个 != {EXPECTED_HNSW}")

    for dialect in DIALECTS:
        table = _table_by_name(documents[dialect]).get(TARGET_TABLE)
        if table is None:
            problems.append(f"{dialect}: 缺少表 {TARGET_TABLE}")
            continue
        names = [str(column.get("name")) for column in table.get("columns") or []]
        if TARGET_COLUMN not in names:
            problems.append(f"{dialect}: {TARGET_TABLE} 缺少列 {TARGET_COLUMN}")

    if problems:
        _fail("双档一致性断言失败：" + "；".join(problems))


def build_documents() -> dict[str, MappingLike]:
    """Build both v0019 snapshots and run the generation-time assertions.

    Returns:
        ``{"pg": snapshot, "sqlite": snapshot}``.

    Raises:
        SystemExit: See :func:`_build` and :func:`_assert_pair`.
    """
    documents = {dialect: _build(dialect) for dialect in DIALECTS}
    _assert_pair(documents)
    return documents


# ---------------------------------------------------------------------------
# 5. CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments without the program name (``None`` -> ``sys.argv[1:]``).

    Returns:
        ``0`` generated / consistent, ``1`` ``--check`` drift, ``2`` input or
        assertion failure.
    """
    parser = argparse.ArgumentParser(
        prog="gen-v0019-normalized.py",
        description="生成 / 校验 v0019 双档 normalized DDL 快照（幂等，以 v0018 为底）",
    )
    parser.add_argument("--check", action="store_true", help="只校验，不写文件（漂移退出 1）")
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    documents = build_documents()

    if arguments.check:
        for dialect in DIALECTS:
            name = TARGET_SNAPSHOT.format(dialect=dialect)
            target = CONTRACTS / name
            if not target.is_file():
                print(f"[v0019-normalized] MISSING {name}", file=sys.stderr)
                return 1
            if target.read_bytes() != _render(documents[dialect]):
                print(f"[v0019-normalized] DRIFT {name}", file=sys.stderr)
                return 1
        print("[v0019-normalized] CHECK OK（2 产物与生成器一致）")
        return 0

    for dialect in DIALECTS:
        name = TARGET_SNAPSHOT.format(dialect=dialect)
        (CONTRACTS / name).write_bytes(_render(documents[dialect]))

    print("[v0019-normalized] 生成完成：")
    for dialect in DIALECTS:
        counts = documents[dialect]["counts"]
        print(
            f"  {dialect:6} tables={counts['tables']} columns={counts['columns']} "
            f"metadata_indexes={counts['metadata_indexes']} "
            f"raw_indexes={counts['raw_indexes']} "
            f"index_objects_total={counts['index_objects_total']} "
            f"foreign_keys={counts['foreign_keys']} "
            f"dialect_only_objects={counts['dialect_only_objects']}"
        )
    print(
        f"  {TARGET_TABLE}.{TARGET_COLUMN} 双侧已插入；hnsw="
        f"{sum(1 for e in documents['pg']['raw_indexes'] if str(e.get('method') or '').lower() == 'hnsw')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
