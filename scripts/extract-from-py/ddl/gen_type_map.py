#!/usr/bin/env python
"""生成 ``contracts/db/type-map.csv``（C-03 / V0.0.1）。

**人只写映射策略，数字全部由脚本从编译结果读出**（路线图 §3.3.2 判据）。

关键口径（M-01，P0 级修正）：类型以 **PG 方言真正 emit 出来的类型**为准，**不是**
``str(col.type)`` 的声明名。实测差异本身就是证据：

===========================  ====================  ====================
声明（``str(col.type)``）      PG emit               SQLite emit
===========================  ====================  ====================
``GUID(length=36)``          ``UUID``              ``CHAR(36)``
``DateTime(timezone=True)``   ``TIMESTAMP WITH TIME ZONE``  ``DATETIME``
``JSONType()``               ``JSONB``             ``JSON``
``VectorType()``             ``VECTOR(1536)``      ``JSON``（降级）
===========================  ====================  ====================

把声明名当方言类型会踩到两个真坑：``uuid`` vs ``char(36)`` 在 PG 上是**外键类型不兼容**；
``timestamptz`` 写成无时区 ``timestamp`` 会造成**时间比较静默偏移**。

用法::

    python scripts/extract-from-py/ddl/gen_type_map.py
    python scripts/extract-from-py/ddl/gen_type_map.py --check
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# 本目录必须可 import：既支持 `python path/to/<script>.py` 直接运行，
# 也支持被 `ddl.exporter` / `run.py` 以模块方式导入（两种情况下 `__package__` 不同，
# 只判断 `__package__` 会让裸 import `_env` 在其中一种情况下失败）。
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import _env

# 🔴 解释器守卫必须在 `import _extract`（进而 `import sqlalchemy`）**之前**执行：
#    被系统 Python 启动时，这里是唯一能切回旧仓 .venv 的机会（否则在 import 期就 ModuleNotFoundError）。
_env.ensure_legacy_runtime(_env.resolve_env(_env.source_hint(sys.argv[1:])))

# 必须在解释器守卫之后导入（_extract 依赖 SQLAlchemy，import 期就要能 import 到）
import _extract

#: 产物相对 ``contracts/`` 的路径。
TYPE_MAP_RELPATH = Path("db") / "type-map.csv"

#: CSV 列顺序（前置固定列，禁止随意调整顺序——外部台账按列位解析）。
#:
#: ``declared_type`` 用 ``repr(col.type)``（真实 ORM 类型，如 ``GUID(length=36)``）；
#: ``declared_str_type`` 是 ``str(col.type)`` 的结果——**故意并排保留**：它对 TypeDecorator
#: 渲染的是 impl（``CHAR(36)``），正是 M-01 说的「把声明名当方言 emit 类型」的陷阱来源。
COLUMNS: tuple[str, ...] = (
    "table",
    "column",
    "declared_type",
    "declared_str_type",
    "pg_emit_type",
    "sqlite_emit_type",
    "ts_target",
    "strategy",
    "dialect_sensitive",
)

#: 映射策略表：**声明类型类名 → (TS 目标类型, 策略 token)**。
#:
#: 只有这张表是「人写的」；每一行的列名 / 两侧 emit 类型都由脚本填。
_POLICY: dict[str, tuple[str, str]] = {
    "GUID": ("string", "uuid-string"),                 # PG uuid / SQLite CHAR(36)，统一按字符串读写
    "DateTime": ("string", "timestamptz-iso8601"),      # 117/117 全带时区，禁止退化为无时区 timestamp
    "JSONType": ("unknown", "jsonb-opaque"),           # PG JSONB / SQLite JSON，契约层不解构内部结构
    "VectorType": ("number[]", "vector-1536-number-array"),  # PG vector(1536)；SQLite 降级 JSON
    "Boolean": ("boolean", "bool-passthrough"),
    "Integer": ("number", "int32-number"),
    "Float": ("number", "double-number"),
    "Numeric": ("string", "decimal-string"),           # 定点小数按字符串传，避免 IEEE754 精度丢失
    "Text": ("string", "text-passthrough"),
    "String": ("string", "varchar-passthrough"),       # 长度约束在 DB 侧，TS 侧不重复编码
}

#: PG emit 类型兜底策略（声明类名未登记时按 emit 类型判，保证**任何列都有记录**）。
_FALLBACK_BY_PG_TYPE: dict[str, tuple[str, str]] = {
    "UUID": ("string", "uuid-string"),
    "TIMESTAMP WITH TIME ZONE": ("string", "timestamptz-iso8601"),
    "JSONB": ("unknown", "jsonb-opaque"),
    "JSON": ("unknown", "json-opaque"),
    "BOOLEAN": ("boolean", "bool-passthrough"),
    "INTEGER": ("number", "int32-number"),
    "FLOAT": ("number", "double-number"),
    "TEXT": ("string", "text-passthrough"),
}

#: 文档记载的口径（仅用于对账打印，**不参与计算**）。
#: 🔴 文档的 `405` 已由 team-lead 裁定**作废**（重复计数：`62` 已含那 2 个 `VectorType`，末项 `+2` 再加一次），
#: 因此这里只登记两个可复算的口径，另把 405 记为 `voided` 以便打印时明确「已作废」而不是「对不上」。
DOCUMENTED_SENSITIVE = {"emit_diff": 401, "declared_family": 403, "voided": 405}

#: 方言敏感族的声明类名（口径 B）。
#: 含纯 `JSON`：`plugin.permissions` / `plugin.manifest` 声明为 `sa.JSON`，在口径B（按声明族）里
#: 属敏感族，但两侧 emit 都是 `JSON`，故不在口径A —— 这正是 401 与 403 差 2 的来源。
_DIALECT_FAMILY = ("GUID", "DateTime", "JSON", "JSONType", "VectorType")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="gen_type_map.py",
        description="由编译结果生成 contracts/db/type-map.csv（逐列映射，一行不落）",
    )
    parser.add_argument("--source", default=None, help="旧仓根目录（默认 $WBTIME_SOURCE）")
    parser.add_argument("--out", default=None, help="输出 CSV 路径（默认 <contracts>/db/type-map.csv）")
    parser.add_argument("--check", action="store_true", help="只校验已入库 CSV 是否与本次结果一致")
    return parser.parse_args(argv)


def _resolve_policy(declared_class: str, pg_emit: str) -> tuple[str, str]:
    """按「声明类名 → PG emit 类型」两级查找映射策略。

    Args:
        declared_class: ``type(col.type).__name__``。
        pg_emit: PG 方言 emit 出的类型串。

    Returns:
        ``(ts_target, strategy)``；未登记时返回 ``("unknown", "unmapped")`` 并计入告警。
    """
    if declared_class in _POLICY:
        return _POLICY[declared_class]
    if pg_emit in _FALLBACK_BY_PG_TYPE:
        return _FALLBACK_BY_PG_TYPE[pg_emit]
    if pg_emit.startswith(("VARCHAR", "CHAR")):
        return ("string", "varchar-passthrough")
    if pg_emit.startswith("NUMERIC"):
        return ("string", "decimal-string")
    return ("unknown", "unmapped")


def build_rows(metadata: Any) -> list[dict[str, str]]:
    """逐列构造映射行（表名升序、列序保持 DDL 定义序）。

    Args:
        metadata: ORM metadata。

    Returns:
        每行一个 dict，键为 :data:`COLUMNS`。
    """
    rows: list[dict[str, str]] = []
    for table in sorted(metadata.tables.values(), key=lambda item: item.name):
        for column in table.columns:
            declared = repr(column.type)
            declared_class = type(column.type).__name__
            pg_emit = column.type.compile(dialect=_extract.PG_DIALECT)
            sqlite_emit = column.type.compile(dialect=_extract.SQLITE_DIALECT)
            ts_target, strategy = _resolve_policy(declared_class, pg_emit)
            rows.append(
                {
                    "table": table.name,
                    "column": column.name,
                    "declared_type": declared,
                    "declared_str_type": str(column.type),
                    "pg_emit_type": pg_emit,
                    "sqlite_emit_type": sqlite_emit,
                    "ts_target": ts_target,
                    "strategy": strategy,
                    "dialect_sensitive": "true" if pg_emit != sqlite_emit else "false",
                }
            )
    return rows


def render_csv(rows: Sequence[dict[str, str]]) -> str:
    """稳定渲染 CSV（``\\n`` 换行、无 BOM、列序固定、不写索引）。"""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _report(rows: Sequence[dict[str, str]], path: Path) -> None:
    """打印实跑计数与两个口径的实测值（供施工记录引用）。"""
    sensitive = [row for row in rows if row["dialect_sensitive"] == "true"]
    by_pg = Counter(row["pg_emit_type"] for row in sensitive)
    family = [row for row in rows if row["declared_type"].split("(")[0] in _DIALECT_FAMILY]
    unmapped = [row for row in rows if row["strategy"] == "unmapped"]
    misleading = [row for row in rows if row["declared_str_type"] != row["pg_emit_type"]]

    print("=" * 78)
    print("type-map.csv · 实跑输出")
    print("=" * 78)
    print(f"output                   : {path.as_posix()}")
    print(f"总列数（逐列映射行数）    : {len(rows)}   （文档基线 629）")
    print(f"口径A emit 差异列（敏感） : {len(sensitive)}   "
          f"（文档基线 {DOCUMENTED_SENSITIVE['emit_diff']}）")
    for pg_type, count in sorted(by_pg.items(), key=lambda item: (-item[1], item[0])):
        print(f"    {pg_type:28s} = {count:4d}")
    print(
        f"口径B 声明敏感族列        : {len(family)}   "
        f"（可复算口径 {DOCUMENTED_SENSITIVE['declared_family']}；文档 405 已作废=重复计数）"
    )
    for name in _DIALECT_FAMILY:
        count = sum(1 for row in family if row["declared_type"].split("(")[0] == name)
        print(f"    {name:28s} = {count:4d}")
    print(f"str(type) 与 PG emit 不一致 : {len(misleading)}   （M-01 陷阱面：这一批就是「按声明名建表会错」的列）")
    for pg_type, count in sorted(
        Counter(row["pg_emit_type"] for row in misleading).items(), key=lambda item: (-item[1], item[0])
    ):
        print(f"    pg_emit={pg_type:24s} = {count:4d}")
    print(f"未映射列（应为 0）        : {len(unmapped)}")
    for row in unmapped[:10]:
        print(f"    ! {row['table']}.{row['column']} declared={row['declared_type']} "
              f"pg={row['pg_emit_type']}")
    print("-" * 78)


def main(argv: Sequence[str] | None = None) -> int:
    """入口：生成（或校验）type-map.csv。

    Returns:
        进程退出码：0 = 成功/无漂移；1 = 校验发现漂移或存在未映射列。
    """
    args = _parse_args(argv)
    env = _env.resolve_env(args.source)
    _env.ensure_legacy_runtime(env)
    metadata = _env.install_metadata(env)

    rows = build_rows(metadata)
    text = render_csv(rows)
    path = Path(args.out).resolve() if args.out else env.contracts_dir / TYPE_MAP_RELPATH

    if args.check:
        _report(rows, path)
        if not path.is_file():
            print(f"[FAIL] {path.as_posix()} 不存在", file=sys.stderr)
            return 1
        if path.read_text(encoding="utf-8") != text:
            print("[FAIL] --check：type-map.csv 与本次抽取结果不一致", file=sys.stderr)
            return 1
        print("[OK] --check：type-map.csv 与本次抽取结果一致")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    _report(rows, path)
    unmapped = sum(1 for row in rows if row["strategy"] == "unmapped")
    print(f"[OK] 已写入 {len(rows)} 行 → {path.as_posix()}")
    if unmapped:
        print(
            f"[WARN] {unmapped} 列未命中映射策略：请在 _POLICY / _FALLBACK_BY_PG_TYPE 登记，"
            "禁止留空",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
