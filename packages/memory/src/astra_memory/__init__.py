"""Astra AI Memory 能力包（``astra_memory``；设计 §2.7 / W6 裁定 R1）。

- 领域实体 / 常量 / 仓储接口：``astra_memory.domain``（``Memory`` / ``MemoryRelation`` /
  ``MemoryKind`` / ``ScopeType`` / ``Visibility`` / ``RelationType``）；
- SQL 仓储：``astra_memory.repositories``（能力包 ORM 落点）；
- 抽取：``astra_memory.extractor``；召回：``astra_memory.recall``；
- 存储抽象：``astra_memory.store`` / ``store_sql`` / ``store_vector``；
- 管理器：``astra_memory.manager``（RP-03 面 + Rich 面）；
- 组合工厂：``astra_memory.factory``（供组合根装配）。

包性质：能力包（仅禁 Web；SQL 仓储留本包 ``repositories/``；**不 import ``astra_runtime``**）
——W6 裁定 §3 / §9-14。
"""

from __future__ import annotations

from .domain import (
    MEMORY_KIND_AGENT,
    MEMORY_KIND_LONG_TERM,
    MEMORY_KIND_PROJECT,
    MEMORY_KIND_SHORT_TERM,
    MEMORY_KIND_USER,
    RELATION_TYPE_DERIVED_FROM,
    RELATION_TYPE_RELATED,
    RELATION_TYPE_SUPERSEDES,
    SCOPE_TYPE_AGENT,
    SCOPE_TYPE_CONVERSATION,
    SCOPE_TYPE_PROJECT,
    SCOPE_TYPE_USER,
    SCOPE_TYPE_WORKSPACE,
    VISIBILITY_PRIVATE,
    VISIBILITY_TENANT,
    VISIBILITY_WORKSPACE,
    Memory,
    MemoryKind,
    MemoryRelation,
    MemoryRelationRepository,
    MemoryRepository,
    RelationType,
    ScopeType,
    Visibility,
    assert_memory_kind,
    assert_relation_type,
    assert_scope_type,
    assert_visibility,
)
from .extractor import (
    DEFAULT_EXTRACTION_TOKEN_LIMIT,
    NON_USER_TRIGGERS,
    MemoryDraft,
    MemoryExtractor,
)
from .factory import (
    MemoryRepositories,
    build_memory_manager,
    build_memory_repositories,
    build_memory_store,
    resolve_memory_vector_capability,
)
from .manager import DEFAULT_SHORT_TERM_TTL_SECONDS, MemoryManager
from .recall import (
    DEFAULT_IMPORTANCE_WEIGHT,
    DEFAULT_RECALL_TOP_K,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
    MemoryRecall,
)
from .repositories import (
    SqlMemoryRelationRepository,
    SqlMemoryRepository,
)
from .store import MemoryStore
from .store_sql import SqlMemoryStore
from .store_vector import DEFAULT_VECTOR_DIMENSIONS, VectorMemoryStore

__all__ = [
    # 实体
    "Memory",
    "MemoryRelation",
    # 枚举
    "MemoryKind",
    "ScopeType",
    "Visibility",
    "RelationType",
    # 常量 · kind
    "MEMORY_KIND_SHORT_TERM",
    "MEMORY_KIND_LONG_TERM",
    "MEMORY_KIND_PROJECT",
    "MEMORY_KIND_AGENT",
    "MEMORY_KIND_USER",
    # 常量 · scope
    "SCOPE_TYPE_USER",
    "SCOPE_TYPE_AGENT",
    "SCOPE_TYPE_PROJECT",
    "SCOPE_TYPE_WORKSPACE",
    "SCOPE_TYPE_CONVERSATION",
    # 常量 · visibility
    "VISIBILITY_PRIVATE",
    "VISIBILITY_WORKSPACE",
    "VISIBILITY_TENANT",
    # 常量 · relation
    "RELATION_TYPE_SUPERSEDES",
    "RELATION_TYPE_DERIVED_FROM",
    "RELATION_TYPE_RELATED",
    # 校验
    "assert_memory_kind",
    "assert_scope_type",
    "assert_visibility",
    "assert_relation_type",
    # 仓储接口
    "MemoryRepository",
    "MemoryRelationRepository",
    # SQL 仓储
    "SqlMemoryRepository",
    "SqlMemoryRelationRepository",
    # 抽取
    "MemoryDraft",
    "MemoryExtractor",
    "DEFAULT_EXTRACTION_TOKEN_LIMIT",
    "NON_USER_TRIGGERS",
    # 召回
    "MemoryRecall",
    "DEFAULT_RECALL_TOP_K",
    "DEFAULT_IMPORTANCE_WEIGHT",
    "DEFAULT_RECENCY_HALF_LIFE_DAYS",
    # 存储
    "MemoryStore",
    "SqlMemoryStore",
    "VectorMemoryStore",
    "DEFAULT_VECTOR_DIMENSIONS",
    # 管理器
    "MemoryManager",
    "DEFAULT_SHORT_TERM_TTL_SECONDS",
    # 组合工厂
    "MemoryRepositories",
    "build_memory_repositories",
    "resolve_memory_vector_capability",
    "build_memory_store",
    "build_memory_manager",
]
