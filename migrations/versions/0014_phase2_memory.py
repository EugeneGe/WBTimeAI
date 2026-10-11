"""Phase 2 · W6 / T2-32：Memory 组表（``memory`` / ``memory_relation``）+ PG 可选 HNSW 索引。

Revision ID: 0014_phase2_memory
Revises: 0013_phase2_knowledge
Create Date: 2026-10-11

设计依据：设计 §2.7 / §2.15；**W6 开工前架构裁定** §1 / §5（B1 / B9 / B10 / §13）。

约定：
- **纯新增**：仅创建 2 张 Memory 组表（+ PG 可选 HNSW 索引）；**不改动** ``0001–0013``
  任何表（**不改** W5 ``0013``，B1 否决「复用 ``embedding`` 表」）；
- 🔴 **显式方言分支** ``dialect = op.get_bind().dialect.name``（**禁 try/except 推断**）；
- 🔴 **记忆向量落点（B1）**：``memory.vector`` 为**自带可空列** ``VectorType(dim)``
  （PG ``vector(d)`` ↔ 其它 ``JSON``）；**不含** ``embedding_id`` 列；
- 🔴 PG ``CREATE EXTENSION IF NOT EXISTS vector``：savepoint 包裹，缺权限 → **WARN + 该列降级
  JSON``、**不阻塞**（唯一允许的 ``try/except`` 功能性降级，**不用于方言判定**）；
- 🔴 PG ``hnsw`` 索引 ``ix_memory_vector_hnsw``（``vector_cosine_ops``，``m=16`` /
  ``ef_construction=64``，**与 ``0013`` 同参数**）；仅当扩展 + ``pgvector`` Python 包均可用时创建；
- 🔴 唯一键：``memory_relation`` ``(from_memory_id, to_memory_id, relation)``（B10）；
  ``memory`` 召回索引 ``(tenant_id, scope_type, scope_id, kind)`` + ``expires_at``（B10）；
- 🔴 外键**单向**（**无跨表环**，§5.1）：``memory → tenant / workspace / agent_run``；
  ``memory_relation → memory``（**仅自表双向 FK**）；
- 🔴 主键 UUIDv7（``GUID``）；时间戳 UTC；向量走 ``VectorType``；``expires_at`` 可空。

🔴 不可逆：``downgrade`` DROP 2 表 → **记忆数据（含 ``USER`` 私有记忆）与向量丢失**
   （回滚前须先导出）。
🔴 ``downgrade`` **严禁 ``DROP EXTENSION vector``**（QA-31 / W6 裁定 §B9）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType, VectorType

# revision identifiers, used by Alembic.
revision: str = "0014_phase2_memory"
down_revision: str | None = "0013_phase2_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_logger = logging.getLogger("alembic.runtime.migration")

#: ``memory.vector`` 单列固定维度（＝ ``capability.embedding_dimensions`` 默认值，§13-c）。
_MEMORY_DIMENSIONS = 1536

#: Memory HNSW 索引名（冻结契约，§1.3-①）。
_HNSW_INDEX_NAME = "ix_memory_vector_hnsw"


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
    """PG：savepoint 包裹 ``CREATE EXTENSION IF NOT EXISTS vector``（幂等；``0013`` 已建则跳过）。

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
            "0014：CREATE EXTENSION vector 失败（缺权限？），"
            "memory.vector 降级为 JSON、语义召回退化关键字路：%s",
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
    """返回 ``memory.vector`` 列类型（方言感知，集中一处）。

    - PostgreSQL 且扩展启用：``VectorType(dim)``（``pgvector`` 可用时渲染 ``vector(d)``）；
    - PostgreSQL 但扩展不可用：``JSONType()``（降级，``C2-28``：非权威方言不跑 autogenerate）；
    - 其它（SQLite）：``VectorType(dim)``（渲染 JSON，与 ORM 一致，保零漂移）。
    """
    if dialect == "postgresql" and not vector_ok:
        return JSONType()
    return VectorType(_MEMORY_DIMENSIONS)


def upgrade() -> None:
    """创建 Memory 组两表 + PG 可选 HNSW 索引。"""
    dialect = op.get_bind().dialect.name
    vector_ok = _try_enable_pg_vector() if dialect == "postgresql" else False
    vector_type = _vector_column_type(dialect, vector_ok=vector_ok)

    # -- 1. memory ----------------------------------------------------------
    op.create_table(
        "memory",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("scope_type", sa.String(length=50), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("visibility", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(length=50), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_run_id", GUID(), nullable=True),
        sa.Column("vector", vector_type, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_memory_tenant_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], name="fk_memory_workspace_id"),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["agent_run.id"], name="fk_memory_source_run_id"
        ),
    )
    op.create_index("ix_memory_tenant_id", "memory", ["tenant_id"])
    op.create_index("ix_memory_workspace_id", "memory", ["workspace_id"])
    op.create_index("ix_memory_source_run_id", "memory", ["source_run_id"])
    op.create_index(
        "ix_memory_tenant_scope_kind",
        "memory",
        ["tenant_id", "scope_type", "scope_id", "kind"],
    )
    op.create_index("ix_memory_expires_at", "memory", ["expires_at"])

    # -- 2. memory_relation（仅自表双向 FK；唯一 (from,to,relation)） ---------
    op.create_table(
        "memory_relation",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("from_memory_id", GUID(), nullable=False),
        sa.Column("to_memory_id", GUID(), nullable=False),
        sa.Column("relation", sa.String(length=50), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["from_memory_id"], ["memory.id"], name="fk_memory_relation_from_memory_id"
        ),
        sa.ForeignKeyConstraint(
            ["to_memory_id"], ["memory.id"], name="fk_memory_relation_to_memory_id"
        ),
        sa.UniqueConstraint(
            "from_memory_id",
            "to_memory_id",
            "relation",
            name="uq_memory_relation_from_to_relation",
        ),
    )
    op.create_index("ix_memory_relation_from_memory_id", "memory_relation", ["from_memory_id"])
    op.create_index("ix_memory_relation_to_memory_id", "memory_relation", ["to_memory_id"])

    # -- 3. 方言专属对象（PG 可选 HNSW；SQLite 无专属对象） ------------------
    if dialect == "postgresql" and vector_ok and _pgvector_python_available():
        op.execute(
            f"CREATE INDEX {_HNSW_INDEX_NAME} ON memory "
            "USING hnsw (vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    """回滚：逆序删除 2 表 + PG HNSW 索引（**数据丢失**，见模块级不可逆说明）。

    🔴 **严禁 ``DROP EXTENSION vector``**（QA-31 / W6 裁定 §B9）。
    """
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":  # pragma: no cover - 依赖 PG 环境
        op.execute(f"DROP INDEX IF EXISTS {_HNSW_INDEX_NAME}")

    op.drop_index("ix_memory_relation_to_memory_id", table_name="memory_relation")
    op.drop_index("ix_memory_relation_from_memory_id", table_name="memory_relation")
    op.drop_table("memory_relation")

    op.drop_index("ix_memory_expires_at", table_name="memory")
    op.drop_index("ix_memory_tenant_scope_kind", table_name="memory")
    op.drop_index("ix_memory_source_run_id", table_name="memory")
    op.drop_index("ix_memory_workspace_id", table_name="memory")
    op.drop_index("ix_memory_tenant_id", table_name="memory")
    op.drop_table("memory")
