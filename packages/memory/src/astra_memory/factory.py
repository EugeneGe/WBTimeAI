"""``astra_memory`` 组合工厂（供**组合根**装配；W6 / T2-34；仿 ``astra_knowledge.factory``）。

- :func:`build_memory_repositories`：装配 SQL 仓储（能力包显式 ORM 落点）；
- :func:`resolve_memory_vector_capability`：解析 ``capability.vector_search`` 三态
  （``None`` ＝ 按 dialect + ``pg_extension`` **确定性探测**，**非 try/except 推断**）；
- :func:`build_memory_store`：装配 :class:`MemoryStore`（``vector_search=true`` →
  ``VectorMemoryStore``；否则 ``SqlMemoryStore``）；
- :func:`build_memory_manager`：装配 :class:`~astra_memory.manager.MemoryManager`
  （RP-03 真实实现，**不落 runtime**；由组合根注入 ``AgentRuntime.build``，B8）。

🔴 本模块为**组合工厂**（``factory.py`` 是能力包显式允许的 ORM 落点）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from astra_database import session_scope
from astra_model import ModelProvider
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .extractor import DEFAULT_EXTRACTION_TOKEN_LIMIT, MemoryExtractor
from .manager import MemoryManager
from .recall import (
    DEFAULT_IMPORTANCE_WEIGHT,
    DEFAULT_RECALL_TOP_K,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
    MemoryRecall,
)
from .repositories import SqlMemoryRelationRepository, SqlMemoryRepository
from .store import MemoryStore
from .store_sql import SqlMemoryStore
from .store_vector import DEFAULT_VECTOR_DIMENSIONS, VectorMemoryStore

__all__ = [
    "MemoryRepositories",
    "build_memory_repositories",
    "resolve_memory_vector_capability",
    "build_memory_store",
    "build_memory_manager",
]


@dataclass
class MemoryRepositories:
    """Memory 双仓储集合（组合根装配产物）。

    Attributes:
        memories: ``memory`` 仓储。
        relations: ``memory_relation`` 关系仓储。
    """

    memories: SqlMemoryRepository
    relations: SqlMemoryRelationRepository


def build_memory_repositories(
    session_factory: sessionmaker[Session],
) -> MemoryRepositories:
    """装配 Memory 双 SQL 仓储（共享同一 ``session_factory``；单例安全）。"""
    return MemoryRepositories(
        memories=SqlMemoryRepository(session_factory),
        relations=SqlMemoryRelationRepository(session_factory),
    )


def resolve_memory_vector_capability(
    *,
    explicit: bool | None,
    session_factory: sessionmaker[Session],
) -> bool:
    """解析 ``capability.vector_search`` 三态（与 Knowledge 同口径）。

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


def build_memory_store(
    *,
    session_factory: sessionmaker[Session],
    vector_search: bool,
    embedding_dimensions: int = DEFAULT_VECTOR_DIMENSIONS,
    repositories: MemoryRepositories | None = None,
    embedder: Callable[[str], list[float]] | None = None,
) -> MemoryStore:
    """装配 :class:`MemoryStore`（能力选路）。

    Args:
        session_factory: 数据库会话工厂。
        vector_search: ``capability.vector_search`` 产物。
        embedding_dimensions: 部署级固定维度（＝ ``capability.embedding_dimensions``）。
        repositories: 复用的仓储集合（``None`` ＝ 现场装配）。
        embedder: 文本 → 向量函数（仅 ``vector_search=true`` 时用于写入 / 重排）。

    Returns:
        ``vector_search=true`` → :class:`VectorMemoryStore`；否则 :class:`SqlMemoryStore`。
    """
    repos = repositories or build_memory_repositories(session_factory)
    sql_store = SqlMemoryStore(repository=repos.memories)
    if vector_search:
        return VectorMemoryStore(
            store=sql_store, embedder=embedder, dimensions=int(embedding_dimensions)
        )
    return sql_store


def build_memory_manager(
    *,
    session_factory: sessionmaker[Session],
    settings: Any,
    model_router: Any = None,
    extraction_model_config: dict[str, Any] | None = None,
    vector_search: bool = False,
    embedding_dimensions: int = DEFAULT_VECTOR_DIMENSIONS,
    store: MemoryStore | None = None,
    repositories: MemoryRepositories | None = None,
) -> MemoryManager:
    """装配 RP-03 真实实现 :class:`~astra_memory.manager.MemoryManager`（供组合根注入 runtime）。

    Args:
        session_factory: 数据库会话工厂。
        settings: ``MemorySettings``（duck-typing 读取抽取 / 召回配置）。
        model_router: 显式 Model Router（用于装配抽取 Provider；可空）。
        extraction_model_config: 抽取模型配置 ``{provider, model}``（可空）。
        vector_search: ``capability.vector_search`` 产物。
        embedding_dimensions: 部署级固定维度（＝ ``capability.embedding_dimensions``）。
        store: 复用的存储（``None`` ＝ 现场装配）。
        repositories: 复用的仓储集合（``None`` ＝ 现场装配）。

    Returns:
        结构化契合 RP-03 ``MemoryManager`` Protocol 的记忆管理器。
    """
    repos = repositories or build_memory_repositories(session_factory)
    memory_store = store or build_memory_store(
        session_factory=session_factory,
        vector_search=vector_search,
        embedding_dimensions=embedding_dimensions,
        repositories=repos,
    )
    provider = _resolve_extraction_provider(model_router, extraction_model_config)
    extractor = MemoryExtractor(
        model_provider=provider,
        model=_extraction_model_name(settings, extraction_model_config),
        token_limit=int(
            getattr(settings, "extraction_token_limit", DEFAULT_EXTRACTION_TOKEN_LIMIT)
        ),
    )
    recall = MemoryRecall(
        store=memory_store,
        top_k=int(getattr(settings, "recall_top_k", DEFAULT_RECALL_TOP_K)),
        importance_weight=float(getattr(settings, "importance_weight", DEFAULT_IMPORTANCE_WEIGHT)),
        recency_half_life_days=float(
            getattr(settings, "recency_half_life_days", DEFAULT_RECENCY_HALF_LIFE_DAYS)
        ),
    )
    return MemoryManager(
        store=memory_store,
        extractor=extractor,
        recall=recall,
        relation_repository=repos.relations,
        settings=settings,
    )


def _resolve_extraction_provider(
    model_router: Any, extraction_model_config: dict[str, Any] | None
) -> ModelProvider | None:
    """从 ``model_router`` + 抽取模型配置解析抽取 Provider。

    不可得 → ``None``（**非静默 fallback**：未配置 / 未注册即不抽取）。
    """
    if model_router is None or not extraction_model_config:
        return None
    provider_name = str(extraction_model_config.get("provider", "") or "")
    model_name = str(extraction_model_config.get("model", "") or "")
    if not provider_name or not model_name:
        return None
    try:
        resolved = model_router.resolve({"provider": provider_name, "model": model_name})
    except Exception:  # noqa: BLE001 - 未配置 / 未注册 → 不抽取（返回 None，非静默）
        return None
    return resolved.provider


def _extraction_model_name(
    settings: Any, extraction_model_config: dict[str, Any] | None
) -> str | None:
    """解析抽取模型名（``MemorySettings.extraction_model`` 优先）。"""
    configured = getattr(settings, "extraction_model", None)
    if configured:
        return str(configured)
    if extraction_model_config:
        model = str(extraction_model_config.get("model", "") or "")
        if model:
            return model
    return None
