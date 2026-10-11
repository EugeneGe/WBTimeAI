"""F1b 守卫测试：DB-only 对象过滤（``migrations/env.py`` 与测试侧同口径）。

本测试为 **零漂移口径守卫**，不依赖任何 DB 连接，覆盖：

- **静态**：``migrations/env.py`` 定义 ``include_object``，且 **两处**
  ``context.configure(...)``（offline / online）均挂载之；
- **行为**：从 ``env.py`` 真实提取 ``include_object`` 逻辑，断言其
  **仅**放行 DB-only 对象（PG HNSW 索引 / SQLite FTS5 虚表），其余对象零放宽；
- **同口径**：测试侧 ``_fts_filter`` 的 DB-only 清单与 ``env.py`` 语义一致，
  且 ``without_db_only_artifacts`` 对合成 diff 的剔除面与 ``include_object`` 对齐。
"""

from __future__ import annotations

import ast
from pathlib import Path

import sqlalchemy as sa

from ._fts_filter import (
    DB_ONLY_INDEX_NAMES,
    DB_ONLY_TABLE_PREFIXES,
    FTS_TABLE_PREFIX,
    without_db_only_artifacts,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_PATH = REPO_ROOT / "migrations" / "env.py"

_HNSW = ("ix_embedding_vector_hnsw", "ix_memory_vector_hnsw")


def _env_source() -> str:
    return _ENV_PATH.read_text(encoding="utf-8")


def _load_include_object() -> object:
    """从 ``env.py`` 提取常量 + ``include_object`` 函数定义并独立执行（不触发迁移）。"""
    tree = ast.parse(_env_source())
    wanted: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in {"_HNSW_DB_ONLY_INDEXES", "_FTS_TABLE_PREFIX"}
            for t in node.targets
        ):
            wanted.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "include_object":
            wanted.append(node)
    assert wanted, "env.py 未找到 include_object / 常量"
    module = ast.Module(body=wanted, type_ignores=[])
    namespace: dict[str, object] = {"frozenset": frozenset, "isinstance": isinstance}
    # 仅执行静态提取的常量与函数定义（不含触发迁移的模块级代码）。
    exec(compile(module, str(_ENV_PATH), "exec"), namespace)
    return namespace["include_object"]


def _configure_calls_include_object() -> int:
    """统计 ``context.configure(...)`` 中挂载 ``include_object=include_object`` 的次数。"""
    tree = ast.parse(_env_source())
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "configure"):
            continue
        for kw in node.keywords:
            if (
                kw.arg == "include_object"
                and isinstance(kw.value, ast.Name)
                and kw.value.id == "include_object"
            ):
                count += 1
    return count


def _synthetic_diff() -> list[object]:
    """构造覆盖 DB-only 与普通对象的合成 diff（用真实 ``Index`` / ``Table`` 对象）。"""
    meta = sa.MetaData()
    plain_table = sa.Table("tool_permission", meta, sa.Column("id", sa.String()))
    plain_index = sa.Index("ix_tool_name", plain_table.c.id)
    fts_table = sa.Table("document_chunk_fts_data", sa.MetaData())
    hnsw_index = sa.Index("ix_embedding_vector_hnsw", plain_table.c.id)
    return [
        ("remove_table", fts_table),  # DB-only（应剔除）
        ("remove_index", hnsw_index),  # DB-only（应剔除）
        ("remove_table", plain_table),  # 普通对象（应保留）
        ("add_index", plain_index),  # 普通对象（应保留）
    ]


def test_env_defines_include_object_on_both_configure_calls() -> None:
    """静态：``env.py`` 定义 ``include_object`` 且 offline / online 两处均挂载。"""
    assert "def include_object(" in _env_source()
    assert _configure_calls_include_object() == 2, "两处 context.configure 均须挂 include_object"


def test_include_object_filters_only_db_only_objects() -> None:
    """行为：``include_object`` 仅对 DB-only 对象返回 False，其余 True（零放宽）。"""
    include_object = _load_include_object()

    # DB-only：PG HNSW 索引。
    for name in _HNSW:
        assert include_object(None, name, "index", True, None) is False, name
    # DB-only：SQLite FTS5 虚表 / 影子表。
    for name in ("document_chunk_fts", "document_chunk_fts_data", "document_chunk_fts_idx"):
        assert include_object(None, name, "table", True, None) is False, name

    # 零放宽：普通对象一律放行。
    assert include_object(None, "ix_tool_name", "index", True, None) is True
    assert include_object(None, "tool_permission", "table", True, None) is True
    assert include_object(None, "embedding", "table", True, None) is True
    # 类型不匹配者不得误伤（表名恰为 HNSW 名 / 索引名恰为 FTS 前缀）。
    assert include_object(None, "ix_embedding_vector_hnsw", "table", True, None) is True
    assert include_object(None, "document_chunk_fts", "index", True, None) is True


def test_fts_filter_matches_include_object_scope() -> None:
    """同口径：``_fts_filter`` 常量与 ``include_object`` 语义一致；剔除面一致。"""
    assert DB_ONLY_INDEX_NAMES == frozenset(_HNSW)
    assert FTS_TABLE_PREFIX in DB_ONLY_TABLE_PREFIXES

    diff = _synthetic_diff()
    residual = without_db_only_artifacts(diff)
    # 仅剔除 FTS 虚表 + HNSW 索引（2 条），保留 2 条普通对象。
    assert residual == [diff[2], diff[3]], residual
