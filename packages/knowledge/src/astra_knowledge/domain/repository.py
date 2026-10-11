"""``astra_knowledge`` 仓储接口（**仅 Protocol**，零 ORM；设计 §2.6 / W5 裁定 §4.3）。

- :class:`KnowledgeBaseRepository` / :class:`DocumentRepository` /
  :class:`DocumentChunkRepository` / :class:`EmbeddingRepository` /
  :class:`AgentKnowledgeRepository`：Knowledge 聚合仓储接口。

SQLAlchemy 实现落本包 ``repositories/``（能力包显式允许的 ORM 落点）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from astra_domain import Repository

from .entities import (
    AgentKnowledge,
    Document,
    DocumentChunk,
    Embedding,
    KnowledgeBase,
)

__all__ = [
    "KnowledgeBaseRepository",
    "DocumentRepository",
    "DocumentChunkRepository",
    "EmbeddingRepository",
    "AgentKnowledgeRepository",
]


@runtime_checkable
class KnowledgeBaseRepository(Repository[KnowledgeBase], Protocol):
    """KnowledgeBase 仓储接口（多租户隔离；``(tenant_id, name)`` 唯一）。"""

    def get_by_name(self, tenant_id: str, name: str) -> KnowledgeBase | None:
        """按 ``(tenant_id, name)`` 获取知识库，不存在返回 ``None``。"""
        ...

    def list_by_tenant(self, tenant_id: str) -> list[KnowledgeBase]:
        """列出某租户下的全部知识库。"""
        ...

    def list_by_workspace(self, workspace_id: str) -> list[KnowledgeBase]:
        """列出某工作区下的全部知识库。"""
        ...


@runtime_checkable
class DocumentRepository(Repository[Document], Protocol):
    """Document 仓储接口。"""

    def list_by_kb(self, knowledge_base_id: str) -> list[Document]:
        """列出某知识库下的全部文档。"""
        ...

    def list_by_status(self, status: str) -> list[Document]:
        """按状态列出文档。"""
        ...

    def get_by_task(self, task_id: str) -> Document | None:
        """按 ``task_id`` 获取文档，不存在返回 ``None``。"""
        ...

    def update_status(
        self, document_id: str, status: str, *, error: str | None = None
    ) -> Document | None:
        """更新文档状态（并可选记录 ``error``），不存在返回 ``None``。"""
        ...


@runtime_checkable
class DocumentChunkRepository(Repository[DocumentChunk], Protocol):
    """DocumentChunk 仓储接口。"""

    def list_by_document(
        self, document_id: str, *, order_by_ordinal: bool = True
    ) -> list[DocumentChunk]:
        """列出某文档的全部分块（默认按 ``ordinal`` 升序）。"""
        ...

    def add_many(self, entities: list[DocumentChunk]) -> list[DocumentChunk]:
        """批量新增分块并返回（索引任务分块落库）。"""
        ...

    def exists_ordinals(self, document_id: str) -> set[int]:
        """返回某文档**已完成**的全部 ``ordinal`` 集合（断点续跑锚）。"""
        ...

    def set_embedding_id(self, chunk_id: str, embedding_id: str | None) -> None:
        """回填 ``document_chunk.embedding_id``（四步写入第 ④ 步；反查缓存）。"""
        ...

    def search_fts(
        self,
        query: str,
        *,
        knowledge_base_ids: list[str],
        top_k: int = 5,
    ) -> list[tuple[DocumentChunk, float]]:
        """SQLite FTS5 关键字路：按 ``MATCH`` + ``bm25`` 检索（返回 ``(chunk, score)``）。

        🔴 仅在 SQLite（``capability.vector_search`` 为假）时可用；PostgreSQL 走
        :meth:`EmbeddingRepository.search_semantic`（不经本方法）。``score`` 越大越相关。
        """
        ...


@runtime_checkable
class EmbeddingRepository(Repository[Embedding], Protocol):
    """Embedding 仓储接口（``chunk_id`` 唯一 1:1）。"""

    def get_by_chunk(self, chunk_id: str) -> Embedding | None:
        """按 ``chunk_id`` 获取向量，不存在返回 ``None``。"""
        ...

    def add_many(self, entities: list[Embedding]) -> list[Embedding]:
        """批量新增向量并返回。"""
        ...

    def search_semantic(
        self,
        vector: list[float],
        *,
        knowledge_base_ids: list[str],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[DocumentChunk, float]]:
        """PG 语义路：按余弦相似度检索（返回 ``(chunk, score)`` 按分数降序）。

        🔴 仅在 ``capability.vector_search`` 为真（PostgreSQL + pgvector）时可用；
        SQLite 走 ``FtsRetriever`` 关键字路（不经本方法）。
        """
        ...


@runtime_checkable
class AgentKnowledgeRepository(Repository[AgentKnowledge], Protocol):
    """AgentKnowledge 绑定仓储接口。"""

    def list_by_agent_version(self, agent_version_id: str) -> list[AgentKnowledge]:
        """列出某 AgentVersion 绑定的全部 KnowledgeBase。"""
        ...
