"""``astra_memory`` 领域子模块（实体 / 常量 / 仓储接口；W6 / T2-32）。

本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from .entities import Memory, MemoryRelation
from .kinds import (
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
    MemoryKind,
    RelationType,
    ScopeType,
    Visibility,
    assert_memory_kind,
    assert_relation_type,
    assert_scope_type,
    assert_visibility,
)
from .repository import MemoryRelationRepository, MemoryRepository

__all__ = [
    # 实体
    "Memory",
    "MemoryRelation",
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
    # 枚举
    "MemoryKind",
    "ScopeType",
    "Visibility",
    "RelationType",
    # 校验
    "assert_memory_kind",
    "assert_scope_type",
    "assert_visibility",
    "assert_relation_type",
    # 仓储接口
    "MemoryRepository",
    "MemoryRelationRepository",
]
