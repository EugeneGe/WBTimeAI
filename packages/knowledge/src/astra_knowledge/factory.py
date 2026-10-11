"""``astra_knowledge`` 组合工厂（供**组合根**装配；W5 / T2-30 + T2-31）。

- :func:`build_knowledge_repositories`：装配五个 SQL 仓储（能力包显式 ORM 落点）；
- :func:`resolve_vector_search_capability`：解析 ``capability.vector_search`` 三态
  （``None`` ＝ 按 dialect + ``pg_extension`` **确定性探测**，B5；**非 try/except 推断**）；
- :func:`build_knowledge_retriever`：装配 RP-02 真实实现 :class:`KnowledgeRetriever`
  （能力包，**不落 runtime**；由组合根注入 ``AgentRuntime.build``，F8）；
- :func:`build_knowledge_index_task`：装配索引任务 :class:`KnowledgeIndexTask`（T2-31）。

🔴 本模块为**组合工厂**（``factory.py`` 是能力包显式允许的 ORM 落点，F15）。
"""

from __future__ import annotations

from dataclasses import dataclass

from astra_database import session_scope
from astra_model import ModelRouter
from astra_storage import Storage
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .embedder import DEFAULT_EMBEDDING_DIMENSIONS, Embedder
from .index_task import KnowledgeIndexTask
from .parser import ParserRegistry
from .repositories import (
    SqlAgentKnowledgeRepository,
    SqlDocumentChunkRepository,
    SqlDocumentRepository,
    SqlEmbeddingRepository,
    SqlKnowledgeBaseRepository,
)
from .retriever import DEFAULT_KNOWLEDGE_TOP_K, KnowledgeRetriever
from .retriever_fts import FtsRetriever
from .retriever_semantic import SemanticRetriever

__all__ = [
    "KnowledgeRepositories",
    "build_knowledge_repositories",
    "resolve_vector_search_capability",
    "build_knowledge_retriever",
    "build_knowledge_index_task",
]


@dataclass
class KnowledgeRepositories:
    """Knowledge 五仓储集合（组合根装配产物）。

    Attributes:
        knowledge_bases: ``knowledge_base`` 仓储。
        documents: ``document`` 仓储。
        chunks: ``document_chunk`` 仓储。
        embeddings: ``embedding`` 仓储。
        agent_knowledge: ``agent_knowledge`` 绑定仓储。
    """

    knowledge_bases: SqlKnowledgeBaseRepository
    documents: SqlDocumentRepository
    chunks: SqlDocumentChunkRepository
    embeddings: SqlEmbeddingRepository
    agent_knowledge: SqlAgentKnowledgeRepository


def build_knowledge_repositories(
    session_factory: sessionmaker[Session],
) -> KnowledgeRepositories:
    """装配五个 SQL 仓储（共享同一 ``session_factory``；单例安全，仿 F3）。"""
    return KnowledgeRepositories(
        knowledge_bases=SqlKnowledgeBaseRepository(session_factory),
        documents=SqlDocumentRepository(session_factory),
        chunks=SqlDocumentChunkRepository(session_factory),
        embeddings=SqlEmbeddingRepository(session_factory),
        agent_knowledge=SqlAgentKnowledgeRepository(session_factory),
    )


def resolve_vector_search_capability(
    *,
    explicit: bool | None,
    session_factory: sessionmaker[Session],
) -> bool:
    """解析 ``capability.vector_search`` 三态（W5 裁定 B5 / §8-1）。

    - 显式 ``True`` / ``False`` → **覆盖优先**；
    - ``None``（自动）→ 按 **dialect 确定性探测**：非 ``postgresql`` → ``False``；
      ``postgresql`` → 查 ``pg_extension``（``extname='vector'``）是否存在。

    🔴 **确定性查询**（``SELECT`` / dialect 判定），**非** try/except 推断。

    Args:
        explicit: 显式配置值（``None`` ＝ 自动）。
        session_factory: 数据库会话工厂（探测用）。

    Returns:
        生效的 ``vector_search`` 布尔值。
    """
    if explicit is not None:
        return bool(explicit)
    with session_scope(session_factory) as session:
        dialect = session.get_bind().dialect.name
        if dialect != "postgresql":
            return False
        row = session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()
    return row is not None


def build_knowledge_retriever(
    *,
    session_factory: sessionmaker[Session],
    model_router: ModelRouter,
    vector_search: bool,
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    top_k: int = DEFAULT_KNOWLEDGE_TOP_K,
) -> KnowledgeRetriever:
    """装配 RP-02 真实实现 :class:`KnowledgeRetriever`（供组合根注入 runtime）。

    Args:
        session_factory: 数据库会话工厂。
        model_router: 显式 Model Router（query 向量嵌入路由）。
        vector_search: 能力包汇入的布尔值（``resolve_vector_search_capability`` 产物）。
        embedding_dimensions: 部署级固定维度（＝ ``capability.embedding_dimensions``）。
        top_k: 默认召回条数。

    Returns:
        结构化契合 RP-02 ``KnowledgeRetriever`` Protocol 的检索器。
    """
    repositories = build_knowledge_repositories(session_factory)
    embedder = Embedder(model_router=model_router, embedding_dimensions=embedding_dimensions)
    semantic = SemanticRetriever(
        embedding_repository=repositories.embeddings,
        knowledge_base_repository=repositories.knowledge_bases,
        embedder=embedder,
    )
    fts = FtsRetriever(chunk_repository=repositories.chunks)
    return KnowledgeRetriever(
        vector_search=vector_search,
        semantic=semantic,
        fts=fts,
        knowledge_base_repository=repositories.knowledge_bases,
        binding_repository=repositories.agent_knowledge,
        top_k=top_k,
    )


def build_knowledge_index_task(
    *,
    session_factory: sessionmaker[Session],
    storage: Storage | None = None,
    model_router: ModelRouter | None = None,
    vector_search: bool = False,
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    parser_registry: ParserRegistry | None = None,
) -> KnowledgeIndexTask:
    """装配索引任务 :class:`KnowledgeIndexTask`（供组合根注入 worker，W5 / T2-31）。

    Args:
        session_factory: 数据库会话工厂。
        storage: ``Storage`` 实现（读取原文；未注入时 ``file`` / ``url`` 文档不可索引）。
        model_router: 显式 Model Router（嵌入路由；``vector_search=False`` 时可为 ``None``）。
        vector_search: 是否启用嵌入（能力包汇入）。
        embedding_dimensions: 部署级固定维度（＝ ``capability.embedding_dimensions``）。
        parser_registry: 解析器注册表（缺省 ＝ 内置注册表）。

    Returns:
        已装配的索引任务（``run(document_id) -> str``）。
    """
    repositories = build_knowledge_repositories(session_factory)
    embedder = (
        Embedder(model_router=model_router, embedding_dimensions=embedding_dimensions)
        if model_router is not None
        else None
    )
    return KnowledgeIndexTask(
        knowledge_base_repository=repositories.knowledge_bases,
        document_repository=repositories.documents,
        chunk_repository=repositories.chunks,
        embedding_repository=repositories.embeddings,
        storage=storage,
        embedder=embedder,
        vector_search=vector_search,
        parser_registry=parser_registry or ParserRegistry.default(),
    )
