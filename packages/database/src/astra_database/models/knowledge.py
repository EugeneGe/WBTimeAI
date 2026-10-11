"""Knowledge 组 ORM 表（设计 §2.6 / §2.15.1；W5 裁定 R1 / T2-27）。

- :class:`KnowledgeBase`：知识库身份与生命周期（``(tenant_id, name)`` 唯一）；
- :class:`Document`：文档（源文件 / url / 文本；承载索引状态机）；
- :class:`DocumentChunk`：分块（``(document_id, ordinal)`` 唯一——**断点续跑锚**）；
- :class:`Embedding`：向量（``chunk_id`` 唯一 1:1；``embedding.chunk_id → document_chunk.id``
  为**唯一跨表强链**）；
- :class:`AgentKnowledge`：KnowledgeBase↔AgentVersion 绑定（唯一键
  ``(agent_version_id, knowledge_base_id)``，同构 ``agent_skill`` / ``agent_tool``）。

🔴 外键拓扑（W5 裁定 B2/B3，**无双向外键**）：``embedding.chunk_id`` 非空 + FK；
   ``document_chunk.embedding_id`` **可空、不加 FK**（仅反查缓存）。
🔴 ORM 保留字（B12）：``document_chunk.metadata`` 列以属性名 ``meta``
   映射（``mapped_column("metadata", ...)``），避免与 ``Base.metadata`` 冲突。
🔴 ``embedding.vector`` 单列**固定维度**＝ ``capability.embedding_dimensions``（默认 1536，B4）。

🔴 本模块落在 ``astra_database``（ORM 允许位置）；域实体在 ``astra_knowledge.domain``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType, VectorType

__all__ = [
    "KnowledgeBase",
    "Document",
    "DocumentChunk",
    "Embedding",
    "AgentKnowledge",
]

#: ``embedding.vector`` 单列固定维度（＝ ``capability.embedding_dimensions`` 默认值，B4）。
#: 🔴 与 ``astra_config.defaults.DEFAULT_EMBEDDING_DIMENSIONS`` 及迁移 ``0013`` 保持一致。
EMBEDDING_DIMENSIONS = 1536


class KnowledgeBase(Base, TimestampMixin):
    """KnowledgeBase：知识库身份与生命周期（设计 §2.6）。"""

    __tablename__ = "knowledge_base"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_knowledge_base_tenant_name"),)

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    embedding_model: Mapped[dict[str, Any]] = mapped_column(
        JSONType(), nullable=False, default=dict
    )
    chunk_config: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by: Mapped[str] = mapped_column(
        GUID(), ForeignKey("user.id"), nullable=False, index=True
    )


class Document(Base, TimestampMixin):
    """Document：知识库内的文档（承载索引状态机）。"""

    __tablename__ = "document"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    knowledge_base_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("knowledge_base.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    task_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("task.id"), nullable=True, index=True
    )


class DocumentChunk(Base):
    """DocumentChunk：文档分块（``(document_id, ordinal)`` 唯一——断点续跑锚，B10）。

    🔴 ``metadata`` 为 SQLAlchemy 保留字：ORM 属性名以 ``meta`` 暴露（B12）。
    🔴 ``embedding_id`` 可空、**无 DB 外键**（B2/B3，避双向外键环）。
    """

    __tablename__ = "document_chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_document_chunk_document_ordinal"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    document_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("document.id"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer(), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONType(), nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class Embedding(Base):
    """Embedding：分块向量（``chunk_id`` 唯一 1:1；**唯一跨表强链**）。"""

    __tablename__ = "embedding"
    __table_args__ = (UniqueConstraint("chunk_id", name="uq_embedding_chunk_id"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    chunk_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("document_chunk.id"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer(), nullable=False)
    vector: Mapped[list[float]] = mapped_column(VectorType(EMBEDDING_DIMENSIONS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class AgentKnowledge(Base, TimestampMixin):
    """AgentKnowledge：绑定到 **AgentVersion** 的 KnowledgeBase（随版本版本化）。"""

    __tablename__ = "agent_knowledge"
    __table_args__ = (
        UniqueConstraint(
            "agent_version_id",
            "knowledge_base_id",
            name="uq_agent_knowledge_version_kb",
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    agent_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent_version.id"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("knowledge_base.id"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
