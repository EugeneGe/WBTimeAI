"""迁移测试共享工具：从 autogenerate diff 中剔除 **DB-only** 对象。

DB-only 对象 = 存在于 DB schema、但**不在** ORM 元数据中的对象——零漂移断言
（等价 ``alembic check``）须忽略之。本清单与产品侧 ``migrations/env.py`` 的
``include_object`` **同口径**（双侧保持一致）：

- ``document_chunk_fts``（FTS5 虚表，迁移 ``0013`` 建）及其影子表
  （``_data`` / ``_idx`` / ``_content`` / ``_docsize`` / ``_config``）——**SQLite 专属**；
- ``ix_embedding_vector_hnsw`` / ``ix_memory_vector_hnsw``（HNSW 向量索引，迁移
  ``0013`` / ``0014`` 仅在 pgvector 可用时建）——**PG 专属**。

🔴 本过滤**仅**剔除清单内对象，对其它所有对象**零放宽**（断言口径不变）：

- PG 为**权威** autogenerate 方言，其 DB-only 对象为两个 HNSW 索引；
- SQLite 的 DB-only 对象为 FTS5 虚表 / 影子对象；
- 二者名不相交，合并为同一清单彼此无副作用。
"""

from __future__ import annotations

from typing import Any

#: FTS5 虚表名（其影子对象均以该前缀开头）。
FTS_TABLE_PREFIX = "document_chunk_fts"

#: DB-only 表名前缀（SQLite 侧 FTS5 虚表 / 影子对象；不在 ORM 元数据中）。
DB_ONLY_TABLE_PREFIXES: tuple[str, ...] = (FTS_TABLE_PREFIX,)

#: DB-only 索引名（PG 侧 HNSW 向量索引；不在 ORM 元数据中）。与 ``migrations/env.py``
#: 的 ``_HNSW_DB_ONLY_INDEXES`` 保持一致。
DB_ONLY_INDEX_NAMES: frozenset[str] = frozenset(
    {"ix_embedding_vector_hnsw", "ix_memory_vector_hnsw"}
)


def without_db_only_artifacts(diff: list[Any]) -> list[Any]:
    """返回剔除 DB-only 对象（HNSW 索引 / FTS5 虚表）后的 diff（其余条目原样保留）。"""
    residual: list[Any] = []
    for entry in diff:
        if isinstance(entry, tuple) and _entry_is_db_only(entry):
            continue
        residual.append(entry)
    return residual


def _entry_is_db_only(entry: tuple[Any, ...]) -> bool:
    """判断一条 diff 元组是否指向 DB-only 对象（HNSW 索引 / FTS5 虚表 / 影子对象）。

    alembic ``compare_metadata`` 的索引 / 表条目中携带 ``Index`` / ``Table`` 对象，
    其 ``name`` 属性即对象名（``"remove_index"`` / ``"remove_table"`` 等标签字符串无
    ``name``，天然跳过）。
    """
    for item in entry:
        name = getattr(item, "name", None)
        if not isinstance(name, str):
            continue
        if name in DB_ONLY_INDEX_NAMES:
            return True
        if name.startswith(DB_ONLY_TABLE_PREFIXES):
            return True
    return False


# --- 向后兼容别名（既有测试 ``from ._fts_filter import without_fts_artifacts``）---
without_fts_artifacts = without_db_only_artifacts
_entry_is_fts = _entry_is_db_only
