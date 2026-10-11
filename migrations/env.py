"""Alembic 迁移环境。

DB URL 从 :func:`astra_config.get_settings` 读取（离线 / 在线均支持）。
``target_metadata`` 取自 ``astra_database.base.Base.metadata``，并通过导入
``astra_database.models`` 保证所有表已注册到元数据。
"""

from __future__ import annotations

from logging.config import fileConfig

import astra_database.models  # noqa: F401  —— 确保模型注册到 Base.metadata
from alembic import context
from astra_config import get_settings
from astra_database.base import Base
from astra_database.engine import create_engine_from_settings

# Alembic Config 对象
config = context.config

# 日志配置（alembic.ini 已定义 logging 段）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据（供 autogenerate）
target_metadata = Base.metadata

#: DB-only 对象——存在 DB schema、但**不在** ORM 元数据中，零漂移断言
#: （autogenerate / ``alembic check``）须忽略之。🔴 仅此清单，其余对象**零放宽**。
#: 与测试侧 ``tests/integration/migrations/_fts_filter.py`` **同口径**（双侧保持一致）。
#:
#: - ``ix_embedding_vector_hnsw`` / ``ix_memory_vector_hnsw``：迁移 ``0013`` / ``0014``
#:   仅在 pgvector 可用时于 **PG** 建（方言专属 DB-only 索引，ORM 无声明）。
#: - ``document_chunk_fts`` 及其影子表：迁移 ``0013`` 在 **SQLite** 建的 FTS5 虚表
#:   （``_data`` / ``_idx`` / ``_content`` / ``_docsize`` / ``_config`` 以该前缀开头）。
_HNSW_DB_ONLY_INDEXES = frozenset({"ix_embedding_vector_hnsw", "ix_memory_vector_hnsw"})
_FTS_TABLE_PREFIX = "document_chunk_fts"


def get_database_url() -> str:
    """从统一配置层解析数据库连接串。"""
    return get_settings().database_url


def include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """autogenerate 对象过滤器：仅剔除 DB-only 的 HNSW 索引与 FTS5 虚表。

    返回 ``False`` 表示在 autogenerate / ``alembic check`` 中**忽略**该对象。
    除下述两类 **DB-only** 对象外，一律返回 ``True``（**零放宽**）：

    - ``type_ == "index"`` 且名在 :data:`_HNSW_DB_ONLY_INDEXES`（PG 专属 HNSW）；
    - ``type_ == "table"`` 且名以 :data:`_FTS_TABLE_PREFIX` 开头（SQLite 专属 FTS5）。
    """
    if type_ == "index" and name in _HNSW_DB_ONLY_INDEXES:
        return False
    if type_ == "table" and isinstance(name, str) and name.startswith(_FTS_TABLE_PREFIX):
        return False
    return True


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不连接数据库。"""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库并执行迁移。"""
    connectable = create_engine_from_settings(get_settings())
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
