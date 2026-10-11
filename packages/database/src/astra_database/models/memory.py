"""Memory 组 ORM 表（设计 §2.7 / §2.15；W6 裁定 B1 / B10 / T2-32）。

- :class:`Memory`：一条记忆（承载 ``kind`` / 作用域 / 可见性 / 内容 / 权重 / **自带向量**
  ``vector`` / TTL）；
- :class:`MemoryRelation`：记忆关系（``from → to`` + ``relation``，唯一键
  ``(from_memory_id, to_memory_id, relation)``）。

🔴 **记忆向量落点（W6 裁定 B1 / §1.3-①）**：``memory`` 表**自带可空列** ``vector``
   类型 :class:`~astra_database.types.VectorType`（PG ``vector(d)`` ↔ 其它 ``JSON``）。
   **不复用** Knowledge ``embedding`` 表（``embedding.chunk_id`` 非空 FK→``document_chunk``，
   无法承载记忆向量，且跨迁移改动破坏 W5 单链）；**本表不含 ``embedding_id`` 列**。
🔴 外键拓扑（W6 裁定 §5.1，**无跨表环**）：``memory → tenant / workspace / agent_run``；
   ``memory_relation → memory``（**仅自表双向 FK**）。
🔴 ``memory.vector`` 单列**固定维度** ＝ ``capability.embedding_dimensions``（默认 1536，同
   ``0013``；§13-c）；SQLite 下为 ``JSON``、``vector_search=false`` 时恒 ``NULL``。

🔴 本模块落在 ``astra_database``（ORM 允许位置）；域实体在 ``astra_memory.domain``。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, VectorType

__all__ = ["Memory", "MemoryRelation", "MEMORY_VECTOR_DIMENSIONS"]

#: ``memory.vector`` 单列固定维度（＝ ``capability.embedding_dimensions`` 默认值；§13-c）。
#: 🔴 与 ``astra_config.defaults.DEFAULT_EMBEDDING_DIMENSIONS`` 及迁移 ``0014`` 保持一致。
MEMORY_VECTOR_DIMENSIONS = 1536


class Memory(Base, TimestampMixin):
    """``memory``：一条记忆（隔离三元组 + 强制 ``tenant_id``；自带可空向量，B1）。"""

    __tablename__ = "memory"
    __table_args__ = (
        Index("ix_memory_tenant_scope_kind", "tenant_id", "scope_type", "scope_id", "kind"),
        Index("ix_memory_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    visibility: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)
    importance: Mapped[float] = mapped_column(Float(), nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float(), nullable=False, default=0.0)
    source_run_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent_run.id"), nullable=True, index=True
    )
    vector: Mapped[list[float] | None] = mapped_column(
        VectorType(MEMORY_VECTOR_DIMENSIONS), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryRelation(Base):
    """``memory_relation``：记忆关系（唯一键 ``(from, to, relation)``，B10）。"""

    __tablename__ = "memory_relation"
    __table_args__ = (
        UniqueConstraint(
            "from_memory_id",
            "to_memory_id",
            "relation",
            name="uq_memory_relation_from_to_relation",
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    from_memory_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("memory.id"), nullable=False, index=True
    )
    to_memory_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("memory.id"), nullable=False, index=True
    )
    relation: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
