"""Knowledge 相关 DTO（W6 / T2-35；设计 §2.6 / §2.12；应用层，零框架依赖）。

- :class:`KnowledgeBaseDTO`：知识库聚合视图（身份 / 检索配置 / 生命周期）；
- :class:`DocumentDTO`：文档视图（**携带 `status` 供前端展示索引进度**）；
- :class:`SearchHitDTO`：检索命中（**引用可回溯** `chunk_id` / `source`）；
- :class:`KnowledgeSearchResultDTO`：检索试跑结果（`mode` 提示当前检索路：语义 / 关键字）。

🔴 与 :mod:`astra_application.dto.workflow` 同口径：DTO 为**纯值**，仅由领域实体构造；
   应用层**不感知** Web / ORM（``test_application_import_boundary`` 强制）。

🔴 约定（A27）：业务 DTO 顶层键**不得**同时使用 ``{code, message, data, request_id}``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astra_knowledge import Document, KnowledgeBase

from .base import DTO

__all__ = [
    "KnowledgeBaseDTO",
    "DocumentDTO",
    "SearchHitDTO",
    "KnowledgeSearchResultDTO",
    "KNOWLEDGE_SEARCH_MODE_SEMANTIC",
    "KNOWLEDGE_SEARCH_MODE_KEYWORD",
]

#: 检索路字面值（供前端提示「语义检索 / 关键字检索」）。
KNOWLEDGE_SEARCH_MODE_SEMANTIC = "semantic"
KNOWLEDGE_SEARCH_MODE_KEYWORD = "keyword"


@dataclass
class KnowledgeBaseDTO(DTO):
    """知识库聚合 DTO（身份 / 检索配置 / 生命周期）。"""

    id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    name: str = ""
    description: str | None = None
    embedding_model: dict[str, Any] = field(default_factory=dict)
    chunk_config: dict[str, Any] = field(default_factory=dict)
    status: str = "ACTIVE"
    created_by: str = ""
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: KnowledgeBase) -> KnowledgeBaseDTO:
        """由 KnowledgeBase 实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            workspace_id=entity.workspace_id,
            name=entity.name,
            description=entity.description,
            embedding_model=dict(entity.embedding_model or {}),
            chunk_config=dict(entity.chunk_config or {}),
            status=entity.status,
            created_by=entity.created_by,
            created_at=entity.created_at,
        )


@dataclass
class DocumentDTO(DTO):
    """文档 DTO（``status`` 供前端展示索引进度：``PENDING→…→READY``）。"""

    id: str
    knowledge_base_id: str = ""
    title: str = ""
    source_type: str = "file"
    storage_key: str | None = None
    mime: str | None = None
    size: int | None = None
    checksum: str | None = None
    status: str = "PENDING"
    error: str | None = None
    task_id: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: Document) -> DocumentDTO:
        """由 Document 实体构造 DTO。"""
        return cls(
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
            created_at=entity.created_at,
        )


@dataclass
class SearchHitDTO(DTO):
    """检索命中（引用可回溯）。

    Attributes:
        chunk_id: 分块标识（引用锚）。
        content: 块文本（可截断展示）。
        score: 相关度分数（**越大越相关**）。
        source: 来源引用（默认 ＝ ``document_id``）。
        metadata: 附加元数据（``mode`` / ``document_id`` / ``ordinal`` 等）。
    """

    chunk_id: str
    content: str = ""
    score: float = 0.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeSearchResultDTO(DTO):
    """检索试跑结果（命中 + 当前检索路 `mode`）。"""

    query: str = ""
    mode: str = KNOWLEDGE_SEARCH_MODE_KEYWORD
    kb_ids: list[str] = field(default_factory=list)
    hits: list[SearchHitDTO] = field(default_factory=list)
