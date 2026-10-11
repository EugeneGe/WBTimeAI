"""ORM 行 ↔ 领域实体映射（KnowledgeBase / Document / DocumentChunk / Embedding /
AgentKnowledge）。

将 ``astra_database.models.knowledge`` 的 SQLAlchemy 行与领域实体互转。

🔴 可空时间戳映射用 :func:`_opt_dt` / ``ensure_utc``，**禁** ``_dt()`` 误填（承接 ``P2-51``）。
🔴 ``document_chunk.metadata`` 列在 ORM 侧以属性名 ``meta`` 暴露（W5 裁定 B12），
   本模块负责 ``meta ↔ meta`` 映射。
🔴 落在能力包 ``repositories/``（显式允许的 ORM 落点，能力包仅禁 Web）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import ensure_utc, utcnow
from astra_database.models.knowledge import AgentKnowledge as OrmAgentKnowledge
from astra_database.models.knowledge import Document as OrmDocument
from astra_database.models.knowledge import DocumentChunk as OrmDocumentChunk
from astra_database.models.knowledge import Embedding as OrmEmbedding
from astra_database.models.knowledge import KnowledgeBase as OrmKnowledgeBase

from ..domain import (
    AgentKnowledge,
    Document,
    DocumentChunk,
    Embedding,
    KnowledgeBase,
)

__all__ = [
    "knowledge_base_to_domain",
    "knowledge_base_to_orm",
    "document_to_domain",
    "document_to_orm",
    "document_chunk_to_domain",
    "document_chunk_to_orm",
    "embedding_to_domain",
    "embedding_to_orm",
    "agent_knowledge_to_domain",
    "agent_knowledge_to_orm",
]


def _opt_dt(value: datetime | None) -> datetime | None:
    """归一化**可空**时间戳：``None`` 保持 ``None``，否则转 UTC（禁误填）。"""
    return ensure_utc(value) if value is not None else None


def _dt(value: datetime | None) -> datetime:
    """归一化**非空**时间戳：``None`` 时回退当前 UTC（仅用于非空列 / 基类字段）。"""
    return ensure_utc(value) if value is not None else utcnow()


# -- KnowledgeBase ----------------------------------------------------------


def knowledge_base_to_domain(row: OrmKnowledgeBase) -> KnowledgeBase:
    """ORM KnowledgeBase 行 → 领域 ``KnowledgeBase``。"""
    return KnowledgeBase(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        workspace_id=row.workspace_id,
        name=row.name,
        description=row.description,
        embedding_model=dict(row.embedding_model or {}),
        chunk_config=dict(row.chunk_config or {}),
        status=row.status,
        created_by=row.created_by,
    )


def knowledge_base_to_orm(entity: KnowledgeBase) -> OrmKnowledgeBase:
    """领域 ``KnowledgeBase`` → ORM 行。"""
    return OrmKnowledgeBase(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        name=entity.name,
        description=entity.description,
        embedding_model=dict(entity.embedding_model or {}),
        chunk_config=dict(entity.chunk_config or {}),
        status=entity.status,
        created_by=entity.created_by,
    )


# -- Document ---------------------------------------------------------------


def document_to_domain(row: OrmDocument) -> Document:
    """ORM Document 行 → 领域 ``Document``。"""
    return Document(
        id=row.id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        knowledge_base_id=row.knowledge_base_id,
        title=row.title,
        source_type=row.source_type,
        storage_key=row.storage_key,
        mime=row.mime,
        size=row.size,
        checksum=row.checksum,
        status=row.status,
        error=row.error,
        task_id=row.task_id,
    )


def document_to_orm(entity: Document) -> OrmDocument:
    """领域 ``Document`` → ORM 行。"""
    return OrmDocument(
        id=entity.id,
        knowledge_base_id=entity.knowledge_base_id,
        title=entity.title,
        source_type=entity.source_type,
        storage_key=entity.storage_key,
        mime=entity.mime,
        size=entity.size,
        checksum=entity.checksum,
        status=entity.status,
        error=entity.error,
        task_id=entity.task_id,
    )


# -- DocumentChunk ----------------------------------------------------------


def document_chunk_to_domain(row: OrmDocumentChunk) -> DocumentChunk:
    """ORM DocumentChunk 行 → 领域 ``DocumentChunk``（``meta`` 属性映射 ``metadata`` 列）。"""
    created_at = _dt(getattr(row, "created_at", None))
    return DocumentChunk(
        id=row.id,
        created_at=created_at,
        updated_at=created_at,
        document_id=row.document_id,
        ordinal=row.ordinal,
        content=row.content,
        token_count=row.token_count,
        meta=dict(getattr(row, "meta", None) or {}),
        embedding_id=row.embedding_id,
    )


def document_chunk_to_orm(entity: DocumentChunk) -> OrmDocumentChunk:
    """领域 ``DocumentChunk`` → ORM 行（``meta`` → ``metadata`` 列）。"""
    return OrmDocumentChunk(
        id=entity.id,
        document_id=entity.document_id,
        ordinal=entity.ordinal,
        content=entity.content,
        token_count=entity.token_count,
        meta=dict(entity.meta or {}) or None,
        embedding_id=entity.embedding_id,
        created_at=_dt(entity.created_at),
    )


# -- Embedding --------------------------------------------------------------


def embedding_to_domain(row: OrmEmbedding) -> Embedding:
    """ORM Embedding 行 → 领域 ``Embedding``。"""
    return Embedding(
        id=row.id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "created_at", None)),
        chunk_id=row.chunk_id,
        model=row.model,
        dimensions=row.dimensions,
        vector=[float(item) for item in (row.vector or [])],
    )


def embedding_to_orm(entity: Embedding) -> OrmEmbedding:
    """领域 ``Embedding`` → ORM 行。"""
    return OrmEmbedding(
        id=entity.id,
        chunk_id=entity.chunk_id,
        model=entity.model,
        dimensions=entity.dimensions,
        vector=[float(item) for item in entity.vector],
        created_at=_dt(entity.created_at),
    )


# -- AgentKnowledge ---------------------------------------------------------


def agent_knowledge_to_domain(row: OrmAgentKnowledge) -> AgentKnowledge:
    """ORM AgentKnowledge 行 → 领域 ``AgentKnowledge``。"""
    return AgentKnowledge(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        agent_version_id=row.agent_version_id,
        knowledge_base_id=row.knowledge_base_id,
        enabled=bool(row.enabled),
        config=dict(row.config) if row.config is not None else None,
    )


def agent_knowledge_to_orm(entity: AgentKnowledge) -> OrmAgentKnowledge:
    """领域 ``AgentKnowledge`` → ORM 行。"""
    config: dict[str, Any] | None = dict(entity.config) if entity.config is not None else None
    return OrmAgentKnowledge(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        agent_version_id=entity.agent_version_id,
        knowledge_base_id=entity.knowledge_base_id,
        enabled=entity.enabled,
        config=config,
    )
