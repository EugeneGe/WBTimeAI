"""``KnowledgeService``——Knowledge 用例编排器（W6 / T2-35；设计 §2.6 / §2.12）。

**应用/用例层（第三类）**：编排「知识库列表 / 文档登记 / 检索试跑」，**不**承载实体
持久化、**不**提供被 Runtime 消费的 Protocol、**零** Web / ORM
（``test_application_import_boundary`` 强制）。

- :meth:`list_bases` / :meth:`get_base` / :meth:`create_base`：知识库（KB）用例；
- :meth:`list_documents` / :meth:`create_document`：文档用例（登记 → ``PENDING``，供索引任务消费）；
- :meth:`search`：检索试跑（经注入的 :class:`~astra_knowledge.KnowledgeRetriever` Rich 面
  ``search``，返回**引用可回溯** :class:`~astra_application.dto.knowledge.SearchHitDTO`）。

🔴 依赖 `astra_knowledge`（能力包，**仅** 领域 Protocol + Rich 检索器）；**不** import
   ``astra_api`` / ``astra_runtime``。多租户隔离：``tenant_id`` 经 KB 归属校验
   （跨租户 → ``NOT_FOUND``）。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode
from astra_knowledge import (
    DOCUMENT_SOURCE_TYPE_FILE,
    DOCUMENT_STATUS_PENDING,
    KNOWLEDGE_BASE_STATUS_ACTIVE,
    Document,
    DocumentRepository,
    KnowledgeBase,
    KnowledgeBaseRepository,
    KnowledgeRetriever,
)

from ..dto.knowledge import (
    KNOWLEDGE_SEARCH_MODE_KEYWORD,
    KNOWLEDGE_SEARCH_MODE_SEMANTIC,
    DocumentDTO,
    KnowledgeBaseDTO,
    KnowledgeSearchResultDTO,
    SearchHitDTO,
)
from .base import ApplicationService

__all__ = ["KnowledgeService"]

#: 检索试跑默认召回条数。
DEFAULT_SEARCH_TOP_K = 5


class KnowledgeService(ApplicationService):
    """Knowledge 用例编排器（DI 注入仓储 + Rich 检索器；零 ORM）。"""

    knowledge_bases: KnowledgeBaseRepository
    documents: DocumentRepository
    retriever: KnowledgeRetriever

    def __init__(
        self,
        *,
        knowledge_bases: KnowledgeBaseRepository,
        documents: DocumentRepository,
        retriever: KnowledgeRetriever,
    ) -> None:
        """装配用例编排器（全部依赖由**组合根**注入）。

        Args:
            knowledge_bases: KnowledgeBase 仓储（领域 Protocol）。
            documents: Document 仓储（领域 Protocol）。
            retriever: 知识检索器（Rich 面 ``search``；capability 选路已在其构造期确定）。
        """
        super().__init__(
            knowledge_bases=knowledge_bases,
            documents=documents,
            retriever=retriever,
        )

    # -- 知识库（KB） --------------------------------------------------------

    def list_bases(self, *, tenant_id: str) -> list[KnowledgeBaseDTO]:
        """列出某租户下的全部知识库。"""
        return [
            KnowledgeBaseDTO.from_entity(item)
            for item in self.knowledge_bases.list_by_tenant(tenant_id)
        ]

    def get_base(self, knowledge_base_id: str, *, tenant_id: str) -> KnowledgeBaseDTO:
        """返回某知识库 DTO（跨租户 / 不存在 → ``NOT_FOUND``）。"""
        return KnowledgeBaseDTO.from_entity(self._require_base(knowledge_base_id, tenant_id))

    def create_base(
        self,
        *,
        tenant_id: str,
        name: str,
        created_by: str,
        description: str | None = None,
        workspace_id: str | None = None,
        embedding_model: dict[str, Any] | None = None,
        chunk_config: dict[str, Any] | None = None,
    ) -> KnowledgeBaseDTO:
        """创建知识库（``(tenant_id, name)`` 唯一；冲突 → ``CONFLICT``）。

        Args:
            tenant_id: 租户标识。
            name: 知识库名（租户内唯一）。
            created_by: 创建者用户标识。
            description: 描述（可空）。
            workspace_id: 归属工作区（可空）。
            embedding_model: 嵌入模型配置（可空）。
            chunk_config: 分块配置（可空）。

        Returns:
            :class:`~astra_application.dto.knowledge.KnowledgeBaseDTO`。

        Raises:
            DomainError: 同租户同名已存在（``CONFLICT``）。
        """
        if self.knowledge_bases.get_by_name(tenant_id, name) is not None:
            raise DomainError(
                "知识库名已存在",
                code=ErrorCode.CONFLICT,
                data={"reason": "duplicate_name", "name": name},
            )
        base = KnowledgeBase(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            description=description,
            embedding_model=dict(embedding_model or {}),
            chunk_config=dict(chunk_config or {}),
            status=KNOWLEDGE_BASE_STATUS_ACTIVE,
            created_by=created_by,
        )
        return KnowledgeBaseDTO.from_entity(self.knowledge_bases.add(base))

    # -- 文档 ----------------------------------------------------------------

    def list_documents(self, knowledge_base_id: str, *, tenant_id: str) -> list[DocumentDTO]:
        """列出某知识库下的全部文档（跨租户 / KB 不存在 → ``NOT_FOUND``）。"""
        base = self._require_base(knowledge_base_id, tenant_id)
        return [DocumentDTO.from_entity(item) for item in self.documents.list_by_kb(base.id)]

    def create_document(
        self,
        knowledge_base_id: str,
        *,
        tenant_id: str,
        title: str,
        source_type: str = DOCUMENT_SOURCE_TYPE_FILE,
        storage_key: str | None = None,
        mime: str | None = None,
        size: int | None = None,
        checksum: str | None = None,
    ) -> DocumentDTO:
        """登记一份文档（初始 ``status=PENDING``，供索引任务消费）。

        Args:
            knowledge_base_id: 归属知识库标识。
            tenant_id: 租户标识（隔离不变量）。
            title: 标题。
            source_type: 源类型（``file`` / ``url`` / ``text``）。
            storage_key: ``Storage`` 对象键（可空）。
            mime: MIME 类型（可空）。
            size: 字节数（可空）。
            checksum: 内容摘要（可空）。

        Returns:
            :class:`~astra_application.dto.knowledge.DocumentDTO`（``status=PENDING``）。

        Raises:
            DomainError: 归属知识库不存在 / 跨租户（``NOT_FOUND``）。
        """
        base = self._require_base(knowledge_base_id, tenant_id)
        document = Document(
            tenant_id=tenant_id,
            knowledge_base_id=base.id,
            title=title,
            source_type=source_type,
            storage_key=storage_key,
            mime=mime,
            size=size,
            checksum=checksum,
            status=DOCUMENT_STATUS_PENDING,
        )
        return DocumentDTO.from_entity(self.documents.add(document))

    # -- 检索试跑 ------------------------------------------------------------

    def search(
        self,
        *,
        tenant_id: str,
        query: str,
        knowledge_base_id: str | None = None,
        workspace_id: str | None = None,
        top_k: int = DEFAULT_SEARCH_TOP_K,
    ) -> KnowledgeSearchResultDTO:
        """检索试跑（命中 + 引用 + 当前检索路 `mode`）。

        KB 解析优先级：显式 ``knowledge_base_id`` → 否则该租户全部（可选按 ``workspace_id`` 过滤）。

        Args:
            tenant_id: 租户标识。
            query: 查询文本。
            knowledge_base_id: 指定 KB（可空）。
            workspace_id: 按工作区收敛 KB 集合（可空；仅在未指定 KB 时生效）。
            top_k: 召回条数（``<=0`` 取默认）。

        Returns:
            :class:`~astra_application.dto.knowledge.KnowledgeSearchResultDTO`。

        Raises:
            DomainError: 显式指定的 KB 不存在 / 跨租户（``NOT_FOUND``）。
        """
        kb_ids = self._resolve_kb_ids(
            tenant_id, knowledge_base_id=knowledge_base_id, workspace_id=workspace_id
        )
        effective_top_k = int(top_k) if int(top_k) > 0 else DEFAULT_SEARCH_TOP_K
        hits: list[SearchHitDTO] = []
        if kb_ids:
            retrieved = self.retriever.search(query, kb_ids=kb_ids, top_k=effective_top_k)
            hits = [
                SearchHitDTO(
                    chunk_id=item.chunk_id,
                    content=item.content,
                    score=float(item.score),
                    source=item.source,
                    metadata=dict(item.metadata or {}),
                )
                for item in retrieved
            ]
        return KnowledgeSearchResultDTO(
            query=query,
            mode=self._search_mode(),
            kb_ids=kb_ids,
            hits=hits,
        )

    # -- 内部 ----------------------------------------------------------------

    def _require_base(self, knowledge_base_id: str, tenant_id: str) -> KnowledgeBase:
        """加载 KB 并校验租户归属（不存在 / 跨租户 → ``NOT_FOUND``）。"""
        base = self.knowledge_bases.get(knowledge_base_id)
        if base is None or (tenant_id and base.tenant_id != tenant_id):
            raise DomainError(
                "知识库不存在",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "knowledge_base_not_found", "knowledge_base_id": knowledge_base_id},
            )
        return base

    def _resolve_kb_ids(
        self,
        tenant_id: str,
        *,
        knowledge_base_id: str | None,
        workspace_id: str | None,
    ) -> list[str]:
        """解析检索命中的 KB 标识集合（显式优先 → 否则租户全部启用 KB）。"""
        if knowledge_base_id:
            return [self._require_base(knowledge_base_id, tenant_id).id]
        bases = self.knowledge_bases.list_by_tenant(tenant_id)
        resolved: list[str] = []
        for base in bases:
            if workspace_id and base.workspace_id and base.workspace_id != workspace_id:
                continue
            resolved.append(base.id)
        return list(dict.fromkeys(resolved))

    def _search_mode(self) -> str:
        """当前检索路（语义 / 关键字；由检索器构造期 capability 选路决定）。"""
        return (
            KNOWLEDGE_SEARCH_MODE_SEMANTIC
            if self.retriever.vector_search
            else KNOWLEDGE_SEARCH_MODE_KEYWORD
        )
