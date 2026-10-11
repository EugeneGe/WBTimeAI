"""``KnowledgeRetriever``（RP-02 真实实现；capability 选路；W5 / T2-30）。

- **Runtime 面（RP-02，冻结）**：:meth:`KnowledgeRetriever.retrieve` 结构化契合
  ``astra_runtime.reserved.knowledge_retriever.KnowledgeRetriever`` Protocol
  （``retrieve(query: KnowledgeQuery) -> list[KnowledgeChunk]``，**签名不变**）；
- **能力包面（Rich）**：:meth:`KnowledgeRetriever.search` 返回 :class:`RetrievedChunk`
  （含 ``chunk_id`` / ``content`` / ``score`` / ``source`` / ``metadata``——**引用可回溯**）；
- **capability 选路（冻结）**：``__init__`` 期一次性二选一注入
  :class:`~astra_knowledge.retriever_semantic.SemanticRetriever`（PG 语义路）或
  :class:`~astra_knowledge.retriever_fts.FtsRetriever`（SQLite FTS5 关键字路）；
  **禁运行时 try/except 推断**（W5 裁定 §2.4 / §5.2 / B5）；
- **KB 解析（B7）**：``agent_version_id`` 非空 → 经 ``agent_knowledge`` 绑定解析（``enabled``）；
  缺省 → **回落该 ``workspace_id`` 全部启用 KB**（§12-d 默认）。

🔴 真实实现落**能力包**（**不落 runtime**），由**组合根**注入（仿 ``skill_resolver``，F8）。
🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_domain`` + 本包领域 Protocol）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from astra_domain import KnowledgeChunk, KnowledgeQuery

from .domain import (
    AgentKnowledgeRepository,
    DocumentChunk,
    KnowledgeBaseRepository,
)
from .status import (
    KNOWLEDGE_BASE_STATUS_ACTIVE,
    KNOWLEDGE_BASE_STATUS_INDEXING,
)

__all__ = [
    "RetrievedChunk",
    "RetrieverBackend",
    "KnowledgeRetriever",
    "to_retrieved_chunk",
    "RETRIEVABLE_KB_STATUSES",
    "DEFAULT_KNOWLEDGE_TOP_K",
]

#: 默认召回条数。
DEFAULT_KNOWLEDGE_TOP_K = 5

#: 可检索的 KB 状态（``DISABLED`` 之外均视为「启用」，含过渡态 ``INDEXING``）。
RETRIEVABLE_KB_STATUSES: frozenset[str] = frozenset(
    {KNOWLEDGE_BASE_STATUS_ACTIVE, KNOWLEDGE_BASE_STATUS_INDEXING}
)


@dataclass
class RetrievedChunk:
    """检索命中的分块（能力包 Rich 输出；**引用可回溯**）。

    Attributes:
        chunk_id: 分块标识（引用锚）。
        content: 块文本。
        score: 相关度分数（**越大越相关**；语义路为余弦相似度，关键字路为 ``-bm25``）。
        source: 来源引用（默认 ＝ ``document_id``）。
        metadata: 附加元数据（``mode`` / ``document_id`` / ``ordinal`` 等）。
    """

    chunk_id: str
    content: str
    score: float = 0.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class RetrieverBackend(Protocol):
    """检索后端（两条路的结构化契约；构造期二选一注入）。"""

    def search(
        self,
        query: str,
        *,
        kb_ids: list[str],
        top_k: int = DEFAULT_KNOWLEDGE_TOP_K,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """按查询召回分块（无匹配返回空列表）。"""
        ...


def to_retrieved_chunk(chunk: DocumentChunk, score: float, *, mode: str) -> RetrievedChunk:
    """把 ``(DocumentChunk, score)`` 映射为 :class:`RetrievedChunk`（附 ``mode`` 供 UI 提示）。"""
    metadata = dict(chunk.meta or {})
    metadata["mode"] = mode
    metadata["document_id"] = chunk.document_id
    metadata["ordinal"] = chunk.ordinal
    return RetrievedChunk(
        chunk_id=chunk.id,
        content=chunk.content,
        score=float(score),
        source=str(chunk.document_id or ""),
        metadata=metadata,
    )


class KnowledgeRetriever:
    """知识检索器（RP-02 真实实现；capability 选路 + KB 绑定解析）。

    Args:
        vector_search: 能力包汇入的布尔值（组合根按 dialect + 扩展解析，B5）。
        semantic: PG 语义路后端（``vector_search=True`` 时使用）。
        fts: SQLite FTS5 关键字路后端（``vector_search=False`` 时使用）。
        knowledge_base_repository: KB 仓储（缺省绑定时的 workspace 回落）。
        binding_repository: ``agent_knowledge`` 绑定仓储（``agent_version_id`` 解析）。
        top_k: 未显式指定 ``query.top_k`` 时的默认召回条数。
    """

    def __init__(
        self,
        *,
        vector_search: bool,
        semantic: RetrieverBackend,
        fts: RetrieverBackend,
        knowledge_base_repository: KnowledgeBaseRepository | None = None,
        binding_repository: AgentKnowledgeRepository | None = None,
        top_k: int = DEFAULT_KNOWLEDGE_TOP_K,
    ) -> None:
        self._vector_search = bool(vector_search)
        # capability 选路：构造期一次性二选一（禁运行时 try/except 推断）。
        self._backend: RetrieverBackend = semantic if self._vector_search else fts
        self._kb_repository = knowledge_base_repository
        self._binding_repository = binding_repository
        self._top_k = int(top_k)

    @property
    def vector_search(self) -> bool:
        """是否启用向量（语义）检索。"""
        return self._vector_search

    @property
    def backend(self) -> RetrieverBackend:
        """已选定的检索后端（供装配 / 断言）。"""
        return self._backend

    def retrieve(self, query: KnowledgeQuery) -> list[KnowledgeChunk]:
        """RP-02 冻结入口：按查询召回并映射为 :class:`~astra_domain.KnowledgeChunk`。

        Args:
            query: 检索请求（``text`` / ``workspace_id`` / ``top_k`` / ``agent_version_id``）。

        Returns:
            召回的 :class:`~astra_domain.KnowledgeChunk` 列表（无匹配 / 无 KB → 空列表）。
        """
        kb_ids = self.resolve_kb_ids(query)
        if not kb_ids:
            return []
        top_k = int(query.top_k) if query.top_k and query.top_k > 0 else self._top_k
        retrieved = self._backend.search(query.text, kb_ids=kb_ids, top_k=top_k, filters=None)
        return [
            KnowledgeChunk(content=item.content, source=item.source, score=item.score)
            for item in retrieved
        ]

    def search(
        self,
        query: str,
        *,
        kb_ids: list[str],
        top_k: int = DEFAULT_KNOWLEDGE_TOP_K,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """能力包 Rich 入口：按显式 ``kb_ids`` 检索（引用可回溯）。"""
        return self._backend.search(query, kb_ids=list(kb_ids), top_k=top_k, filters=filters)

    def resolve_kb_ids(self, query: KnowledgeQuery) -> list[str]:
        """解析查询命中的 KB 标识集合（B7 / §12-d）。

        1. ``agent_version_id`` 非空且已注入绑定仓储 → ``agent_knowledge`` 绑定（``enabled``）；
        2. 否则 ``workspace_id`` 非空 → 该工作区**启用** KB（``status != DISABLED``）；
        3. 均不可得 → 空（保守：不跨工作区召回）。
        """
        if query.agent_version_id and self._binding_repository is not None:
            bindings = self._binding_repository.list_by_agent_version(query.agent_version_id)
            return _dedupe([item.knowledge_base_id for item in bindings if item.enabled])
        if query.workspace_id and self._kb_repository is not None:
            bases = self._kb_repository.list_by_workspace(query.workspace_id)
            return _dedupe([kb.id for kb in bases if kb.status in RETRIEVABLE_KB_STATUSES])
        return []


def _dedupe(values: list[str]) -> list[str]:
    """按出现顺序去重（保留稳定序）。"""
    return list(dict.fromkeys(value for value in values if value))
