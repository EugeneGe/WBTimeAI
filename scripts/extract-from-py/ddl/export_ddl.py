#!/usr/bin/env python
"""生成 DDL 冻结面四件套（C-03 / V0.0.1）。

产物（默认写入 ``<repo>/contracts/``）：

* ``schema.v0018.pg.sql``                PG 侧完整 DDL（表 + 索引 + raw hnsw）
* ``schema.v0018.pg.normalized.json``    PG 侧 normalized 快照
* ``schema.v0018.sqlite.sql``            SQLite 侧完整 DDL（含 FTS5 虚表 + 影子表 + 触发器）
* ``schema.v0018.sqlite.normalized.json`` SQLite 侧 normalized 快照

用法（任选其一，脚本会自动切到旧仓 ``.venv`` 解释器）::

    python scripts/extract-from-py/ddl/export_ddl.py
    python scripts/extract-from-py/ddl/export_ddl.py --source D:/WBT/WBTimeAI_old
    python scripts/extract-from-py/ddl/export_ddl.py --check     # 只校验，不落盘

**三源合并**是本脚本的全部要点，缺一源即红（见 ``ddl/README.md``）：
① ORM metadata 编译 → ② 迁移链 raw DDL（2 个 hnsw）→ ③ SQLite 专属（FTS5）。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
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

#: 输出文件清单（相对 ``contracts/``）。
PG_SQL = "schema.v0018.pg.sql"
PG_JSON = "schema.v0018.pg.normalized.json"
SQLITE_SQL = "schema.v0018.sqlite.sql"
SQLITE_JSON = "schema.v0018.sqlite.normalized.json"

#: 文档 / 路线图记载的基线（**只用于对账与告警**，绝不用于凑数）。
DOCUMENTED_BASELINE: dict[str, int] = {
    "tables": 61,
    "metadata_indexes": 174,
    "unique_indexes": 7,
    "partial_indexes": 1,
    "raw_indexes": 2,
    "columns": 629,
}

#: 必须出现的 2 个 hnsw 索引名（少一个就说明源② 抽取失败）。
EXPECTED_HNSW = ("ix_embedding_vector_hnsw", "ix_memory_vector_hnsw")


def _sha256(text: str) -> str:
    """返回 UTF-8 文本的 sha256（与落盘字节完全对应）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="export_ddl.py",
        description="DDL 冻结面三源合并导出（PG + SQLite 双侧）",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="旧仓根目录（默认 $WBTIME_SOURCE 或 D:/WBT/WBTimeAI_old）",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="产物目录（默认 <repo>/contracts）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验已入库产物与本次抽取结果是否一致，不写文件（漂移则退出码 1）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="只打印计数摘要，不打印逐对象溯源表",
    )
    return parser.parse_args(argv)


def build_payloads(env: _env.Env) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    """执行三源合并。

    Args:
        env: 已解析的环境（旧仓根目录 / 导入根 / 解释器）。

    Returns:
        ``(payloads, pg_snapshot, sqlite_snapshot)``——三源合并后的全部产物内容与两份快照。

    Raises:
        RuntimeError: hnsw 抽取数量与基线不符（说明源② 失真，必须人工介入）。
    """
    raw_statements = _extract.extract_raw_statements(env.source)
    hnsw = [item for item in raw_statements if item.kind == "index"]
    names = {item.name for item in hnsw}
    missing = [name for name in EXPECTED_HNSW if name not in names]
    if missing:
        raise RuntimeError(
            f"源② 抽取失败：缺少 hnsw 索引 {missing}；"
            f"实际抽到 {sorted(names)}（检查 migrations/versions 里 op.execute 的字符串形状）"
        )

    sqlite_only = _extract.materialize_fts5_objects(raw_statements)

    metadata = _env.install_metadata(env)
    pg_snapshot = _extract.build_pg_snapshot(metadata, raw_statements)
    sqlite_snapshot = _extract.build_sqlite_snapshot(metadata, sqlite_only)

    payloads = {
        PG_SQL: _extract.render_pg_sql(metadata, pg_snapshot),
        PG_JSON: _extract.dump_json(pg_snapshot),
        SQLITE_SQL: _extract.render_sqlite_sql(metadata, sqlite_snapshot),
        SQLITE_JSON: _extract.dump_json(sqlite_snapshot),
    }
    return payloads, pg_snapshot, sqlite_snapshot


def _report(
    payloads: dict[str, str],
    pg_snapshot: dict[str, Any],
    sqlite_snapshot: dict[str, Any],
    out_dir: Path,
    source: str,
    quiet: bool,
) -> None:
    """打印实跑计数、基线对账与逐对象溯源表（供施工记录原样引用）。"""
    print("=" * 78)
    print("DDL 冻结面三源合并 · 实跑输出")
    print("=" * 78)
    print(f"source      : {source}")
    print(f"out_dir     : {out_dir.as_posix()}")
    print(f"interpreter : {sys.executable}")
    print("-" * 78)
    if pg_snapshot is not None:
        counts = pg_snapshot["counts"]
        print("源① ORM metadata 编译（PG 方言 emit）")
        for key in (
            "tables",
            "columns",
            "metadata_indexes",
            "unique_indexes",
            "partial_indexes",
            "unique_constraints",
            "foreign_keys",
        ):
            baseline = DOCUMENTED_BASELINE.get(key)
            suffix = "" if baseline is None else f"   （文档基线 {baseline}）"
            verdict = ""
            if baseline is not None and baseline != counts[key]:
                verdict = "  ⚠️ 与文档不符，以实测为准"
            print(f"  {key:22s} = {counts[key]:5d}{suffix}{verdict}")
        print("源② 迁移链 raw DDL")
        print(f"  raw_indexes            = {counts['raw_indexes']:5d}   （文档基线 2）")
        print(
            f"  extensions             = {counts['extensions']:5d} 个（去重后）"
            f" / {counts['extension_statements']} 条语句（0013、0014 各写一次，幂等）"
        )
        print(f"  合并后索引对象总数     = {counts['index_objects_total']:5d}")
        print("-" * 78)
    for name, text in payloads.items():
        print(f"{name:40s} {len(text.encode('utf-8')):>9,d} B  sha256={_sha256(text)}")
    print("-" * 78)

    if quiet:
        return

    print("逐对象溯源（源② hnsw，PG 专属；SQLite 侧不存在，属合法 dialect_only 差异）")
    for raw_index in pg_snapshot["raw_indexes"]:
        print(f"  [{raw_index['method']}] {raw_index['name']} ON {raw_index['table']}")
        print(f"      source : {raw_index['source']}")
        print(f"      options: {raw_index['options']}")
        print(f"      sql    : {raw_index['sql']}")

    print("-" * 78)
    print(
        f"逐对象溯源（源③ SQLite 专属，"
        f"{sqlite_snapshot['counts']['dialect_only_objects']} 个；PG DDL 里 0 处）"
    )
    for item in sqlite_snapshot["dialect_only"]:
        print(f"  [{item['kind']:13s}] {item['name']}")
        print(f"      table  : {item['table']}")
        print(f"      source : {item['source']}")
        print(f"      sql    : {item['sql']}")

    pg_only = {item["name"] for item in pg_snapshot["raw_indexes"]}
    sqlite_names = {item["name"] for item in sqlite_snapshot["dialect_only"]}
    print("-" * 78)
    print("双侧差异对账（每条差异都必须能解释，禁止「差异 = 遗漏」）")
    print(f"  PG 独有（dialect_only: pg）  : {sorted(pg_only)}")
    print(f"  SQLite 独有（dialect_only:sqlite）: {sorted(sqlite_names)}")
    print(
        f"  交集（两侧都应存在）       : "
        f"{sorted(pg_only & sqlite_names) or '[] （无交集 = 正确：两类专属对象互不相交）'}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """入口：导出（或校验）四件套。

    Returns:
        进程退出码：0 = 成功/无漂移；1 = 校验发现漂移；2 = 抽取失败。
    """
    args = _parse_args(argv)
    env = _env.resolve_env(args.source)
    _env.ensure_legacy_runtime(env)

    out_dir = Path(args.out_dir).resolve() if args.out_dir else env.contracts_dir
    try:
        payloads, pg_snapshot, sqlite_snapshot = build_payloads(env)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    if args.check:
        drift: list[str] = []
        for name, text in payloads.items():
            target = out_dir / name
            if not target.is_file():
                drift.append(f"{name}: 缺失")
                continue
            if target.read_text(encoding="utf-8") != text:
                drift.append(f"{name}: 内容漂移（sha256 不一致）")
        _report(payloads, pg_snapshot, sqlite_snapshot, out_dir, env.source, args.quiet)
        if drift:
            print("[FAIL] --check 发现漂移：")
            for item in drift:
                print(f"  - {item}")
            return 1
        print("[OK] --check：四件套与本次抽取结果完全一致")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in payloads.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
    _report(payloads, pg_snapshot, sqlite_snapshot, out_dir, env.source, args.quiet)
    print(f"[OK] 已写入 {len(payloads)} 个文件 → {out_dir.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
