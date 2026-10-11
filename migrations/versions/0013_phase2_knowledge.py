"""Phase 2 · W5 / T2-27：Knowledge 组表（``knowledge_base`` / ``document`` /
``document_chunk`` / ``embedding`` / ``agent_knowledge``）+ PG pgvector 扩展 + SQLite FTS5 虚表。

Revision ID: 0013_phase2_knowledge
Revises: 0012_phase2_workflow
Create Date: 2026-10-10

设计依据：设计 §2.6 / §2.15.1 / §2.15.4；**W5 开工前架构裁定** §1 / §2（R1 / R2 / B1~B12）。

约定：
- **纯新增**：仅创建 5 张 Knowledge 组表 + 方言专属对象；**不改动** ``0001–0012`` 任何表；
- 🔴 **显式方言分支** ``dialect = op.get_bind().dialect.name``（**禁 try/except 推断**）；
- 🔴 PG ``CREATE EXTENSION IF NOT EXISTS vector``：savepoint 包裹，缺权限 → **WARN + 该列降级
  JSON``、**不阻塞**（唯一允许的 ``try/except`` 功能性降级，**不用于方言判定**）；
- 🔴 SQLite：建 **FTS5 虚表** ``document_chunk_fts``（external-content
  ``content='document_chunk'``）+ ``ai`` / ``ad`` / ``au`` 三触发器；PG 不建；
- 🔴 PG ``hnsw`` 索引 ``ix_embedding_vector_hnsw``（``vector_cosine_ops``，``m=16`` /
  ``ef_construction=64``，B1）；仅当扩展 + ``pgvector`` Python 包均可用时创建；
- 🔴 唯一键：``knowledge_base`` ``(tenant_id, name)``；``document_chunk`` ``(document_id, ordinal)``
  （断点续跑锚，B10）；``embedding`` ``chunk_id``（1:1，B10）；``agent_knowledge``
  ``(agent_version_id, knowledge_base_id)``；
- 🔴 外键**严格单向**（无双向外键，B2/B3）：``embedding.chunk_id → document_chunk.id`` 非空 + FK；
  ``document_chunk.embedding_id`` **可空、无 FK**（仅反查缓存）；
- 🔴 主键 UUIDv7（``GUID``）；时间戳 UTC；JSON 走 ``JSONType``；向量走 ``VectorType``。

🔴 不可逆：``downgrade`` DROP 5 表 + FTS5 虚表 → **Knowledge 数据与向量丢失**
   （Storage 原文对象**不随之清理**，须显式枚举 ``storage_key`` 删除或声明不可逆）。
🔴 ``downgrade`` **严禁 ``DROP EXTENSION vector``**（QA-31）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType, VectorType

# revision identifiers, used by Alembic.
revision: str = "0013_phase2_knowledge"
down_revision: str | None = "0012_phase2_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_logger = logging.getLogger("alembic.runtime.migration")

#: ``embedding.vector`` 单列固定维度（＝ ``capability.embedding_dimensions`` 默认值，B4）。
_EMBEDDING_DIMENSIONS = 1536

#: HNSW 索引名（冻结契约，B1）。
_HNSW_INDEX_NAME = "ix_embedding_vector_hnsw"

#: SQLite FTS5 虚表 / 触发器名。
_FTS_TABLE = "document_chunk_fts"
_FTS_TRIGGERS: tuple[str, ...] = (
    "document_chunk_ai",
    "document_chunk_ad",
    "document_chunk_au",
)


def _timestamps() -> list[sa.Column]:
    """返回统一的时间戳列定义（UTC，``created_at`` + ``updated_at``）。"""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def _created_at() -> sa.Column:
    """返回仅 ``created_at`` 的时间戳列（UTC）。"""
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def _try_enable_pg_vector() -> bool:
    """PG：savepoint 包裹 ``CREATE EXTENSION IF NOT EXISTS vector``。

    🔴 唯一允许的 ``try/except``：**功能性降级**（缺权限 → 降级 JSON + 明确 WARN，**不阻塞**），
       **不**用于方言判定（方言一律 ``op.get_bind().dialect.name``）。

    Returns:
        扩展是否可用（``True`` = 可用）。
    """
    bind = op.get_bind()
    savepoint = bind.begin_nested()
    try:
        bind.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as exc:  # noqa: BLE001 - 权限失败的功能性降级（不用于方言判定）
        savepoint.rollback()
        _logger.warning(
            "0013：CREATE EXTENSION vector 失败（缺权限？），"
            "embedding.vector 降级为 JSON、检索退化关键字路：%s",
            exc,
        )
        return False
    savepoint.commit()
    return True


def _pgvector_python_available() -> bool:
    """``pgvector`` Python 包是否可用（用于决定是否建 HNSW 索引）。"""
    try:
        import pgvector.sqlalchemy  # noqa: F401
    except ImportError:  # pragma: no cover - 取决于部署方是否安装 pgvector
        return False
    return True


def _vector_column_type(dialect: str, *, vector_ok: bool) -> Any:  # noqa: ANN401
    """返回 ``embedding.vector`` 列类型（方言感知，集中一处）。

    - PostgreSQL 且扩展启用：``VectorType(dim)``（``pgvector`` 可用时渲染 ``vector(d)``）；
    - PostgreSQL 但扩展不可用：``JSONType()``（降级，``C2-25``：非权威方言不跑 autogenerate）；
    - 其它（SQLite）：``VectorType(dim)``（渲染 JSON，与 ORM 一致，保零漂移）。
    """
    if dialect == "postgresql" and not vector_ok:
        return JSONType()
    return VectorType(_EMBEDDING_DIMENSIONS)


def _create_sqlite_fts() -> None:
    """SQLite：建 external-content FTS5 虚表 + ``ai`` / ``ad`` / ``au`` 三触发器（B11）。"""
    op.execute(
        f"CREATE VIRTUAL TABLE {_FTS_TABLE} USING fts5("
        "content, content='document_chunk', content_rowid='rowid')"
    )
    op.execute(
        f"CREATE TRIGGER document_chunk_ai AFTER INSERT ON document_chunk BEGIN "
        f"INSERT INTO {_FTS_TABLE}(rowid, content) VALUES (new.rowid, new.content); END"
    )
    op.execute(
        f"CREATE TRIGGER document_chunk_ad AFTER DELETE ON document_chunk BEGIN "
        f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); END"
    )
    op.execute(
        f"CREATE TRIGGER document_chunk_au AFTER UPDATE ON document_chunk BEGIN "
        f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}, rowid, content) "
        "VALUES ('delete', old.rowid, old.content); "
        f"INSERT INTO {_FTS_TABLE}(rowid, content) VALUES (new.rowid, new.content); END"
    )


def _drop_sqlite_fts() -> None:
    """SQLite：删除 FTS5 触发器与虚表（PG 不触）。"""
    for trigger in _FTS_TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute(f"DROP TABLE IF EXISTS {_FTS_TABLE}")


def upgrade() -> None:
    """创建 Knowledge 组五表 + 方言专属对象（PG 扩展 / SQLite FTS5）。"""
    dialect = op.get_bind().dialect.name
    vector_ok = _try_enable_pg_vector() if dialect == "postgresql" else False
    vector_type = _vector_column_type(dialect, vector_ok=vector_ok)

    # -- 1. knowledge_base ---------------------------------------------------
    op.create_table(
        "knowledge_base",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("embedding_model", JSONType(), nullable=False),
        sa.Column("chunk_config", JSONType(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_by", GUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_knowledge_base_tenant_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_knowledge_base_workspace_id"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], name="fk_knowledge_base_created_by"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_knowledge_base_tenant_name"),
    )
    op.create_index("ix_knowledge_base_tenant_id", "knowledge_base", ["tenant_id"])
    op.create_index("ix_knowledge_base_workspace_id", "knowledge_base", ["workspace_id"])
    op.create_index("ix_knowledge_base_created_by", "knowledge_base", ["created_by"])

    # -- 2. document --------------------------------------------------------
    op.create_table(
        "document",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("knowledge_base_id", GUID(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("mime", sa.String(length=255), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("task_id", GUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_base.id"],
            name="fk_document_knowledge_base_id",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name="fk_document_task_id"),
    )
    op.create_index("ix_document_knowledge_base_id", "document", ["knowledge_base_id"])
    op.create_index("ix_document_status", "document", ["status"])
    op.create_index("ix_document_task_id", "document", ["task_id"])

    # -- 3. document_chunk（metadata 列名；embedding_id 可空无 FK） -----------
    op.create_table(
        "document_chunk",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("document_id", GUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("metadata", JSONType(), nullable=True),
        sa.Column("embedding_id", GUID(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], name="fk_document_chunk_document_id"
        ),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_document_chunk_document_ordinal"),
    )
    op.create_index("ix_document_chunk_document_id", "document_chunk", ["document_id"])

    # -- 4. embedding（chunk_id 非空 + FK；唯一 chunk_id） -------------------
    op.create_table(
        "embedding",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("chunk_id", GUID(), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", vector_type, nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunk.id"], name="fk_embedding_chunk_id"),
        sa.UniqueConstraint("chunk_id", name="uq_embedding_chunk_id"),
    )
    op.create_index("ix_embedding_chunk_id", "embedding", ["chunk_id"])

    # -- 5. agent_knowledge -------------------------------------------------
    op.create_table(
        "agent_knowledge",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("agent_version_id", GUID(), nullable=False),
        sa.Column("knowledge_base_id", GUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", JSONType(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_agent_knowledge_tenant_id"),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_version.id"],
            name="fk_agent_knowledge_agent_version_id",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_base.id"],
            name="fk_agent_knowledge_knowledge_base_id",
        ),
        sa.UniqueConstraint(
            "agent_version_id",
            "knowledge_base_id",
            name="uq_agent_knowledge_version_kb",
        ),
    )
    op.create_index("ix_agent_knowledge_tenant_id", "agent_knowledge", ["tenant_id"])
    op.create_index("ix_agent_knowledge_agent_version_id", "agent_knowledge", ["agent_version_id"])
    op.create_index(
        "ix_agent_knowledge_knowledge_base_id", "agent_knowledge", ["knowledge_base_id"]
    )

    # -- 6. 方言专属对象 ----------------------------------------------------
    if dialect == "sqlite":
        _create_sqlite_fts()
    elif dialect == "postgresql" and vector_ok and _pgvector_python_available():
        op.execute(
            f"CREATE INDEX {_HNSW_INDEX_NAME} ON embedding "
            "USING hnsw (vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    """回滚：逆序删除 5 表 + 方言专属对象（**数据丢失**，见模块级不可逆说明）。

    🔴 **严禁 ``DROP EXTENSION vector``**（QA-31）。
    """
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _drop_sqlite_fts()
    elif dialect == "postgresql":  # pragma: no cover - 依赖 PG 环境
        op.execute(f"DROP INDEX IF EXISTS {_HNSW_INDEX_NAME}")

    op.drop_index("ix_agent_knowledge_knowledge_base_id", table_name="agent_knowledge")
    op.drop_index("ix_agent_knowledge_agent_version_id", table_name="agent_knowledge")
    op.drop_index("ix_agent_knowledge_tenant_id", table_name="agent_knowledge")
    op.drop_table("agent_knowledge")

    op.drop_index("ix_embedding_chunk_id", table_name="embedding")
    op.drop_table("embedding")

    op.drop_index("ix_document_chunk_document_id", table_name="document_chunk")
    op.drop_table("document_chunk")

    op.drop_index("ix_document_task_id", table_name="document")
    op.drop_index("ix_document_status", table_name="document")
    op.drop_index("ix_document_knowledge_base_id", table_name="document")
    op.drop_table("document")

    op.drop_index("ix_knowledge_base_created_by", table_name="knowledge_base")
    op.drop_index("ix_knowledge_base_workspace_id", table_name="knowledge_base")
    op.drop_index("ix_knowledge_base_tenant_id", table_name="knowledge_base")
    op.drop_table("knowledge_base")
