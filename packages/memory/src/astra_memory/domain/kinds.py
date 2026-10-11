"""``astra_memory`` 领域常量 / 枚举（设计 §2.7 / §2.15；W6 裁定 §5.2 / §9-1 / E7）。

值域（DB 为**普通字符串列**，免枚举迁移，W6 裁定 §5.1）：

- :class:`MemoryKind`：``SHORT_TERM | LONG_TERM | PROJECT | AGENT | USER``（五类记忆）；
- :class:`ScopeType`：``user | agent | project | workspace | conversation``（隔离作用域维度）；
- :class:`Visibility`：``private | workspace | tenant``（**显式**可见性，R-19）；
- :class:`RelationType`：``supersedes | derived_from | related``（记忆关系）。

配套校验函数（非法值抛 ``DomainError(VALIDATION_ERROR)``，仿 ``astra_knowledge.status``）。

🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_core``）。
"""

from __future__ import annotations

from enum import StrEnum

from astra_core import DomainError, ErrorCode

__all__ = [
    # 常量 · MemoryKind
    "MEMORY_KIND_SHORT_TERM",
    "MEMORY_KIND_LONG_TERM",
    "MEMORY_KIND_PROJECT",
    "MEMORY_KIND_AGENT",
    "MEMORY_KIND_USER",
    # 常量 · ScopeType
    "SCOPE_TYPE_USER",
    "SCOPE_TYPE_AGENT",
    "SCOPE_TYPE_PROJECT",
    "SCOPE_TYPE_WORKSPACE",
    "SCOPE_TYPE_CONVERSATION",
    # 常量 · Visibility
    "VISIBILITY_PRIVATE",
    "VISIBILITY_WORKSPACE",
    "VISIBILITY_TENANT",
    # 常量 · RelationType
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
]

# -- MemoryKind（五类记忆） --------------------------------------------------

MEMORY_KIND_SHORT_TERM = "SHORT_TERM"
MEMORY_KIND_LONG_TERM = "LONG_TERM"
MEMORY_KIND_PROJECT = "PROJECT"
MEMORY_KIND_AGENT = "AGENT"
MEMORY_KIND_USER = "USER"

# -- ScopeType（隔离作用域维度） ---------------------------------------------

SCOPE_TYPE_USER = "user"
SCOPE_TYPE_AGENT = "agent"
SCOPE_TYPE_PROJECT = "project"
SCOPE_TYPE_WORKSPACE = "workspace"
SCOPE_TYPE_CONVERSATION = "conversation"

# -- Visibility（显式可见性，R-19） ------------------------------------------

VISIBILITY_PRIVATE = "private"
VISIBILITY_WORKSPACE = "workspace"
VISIBILITY_TENANT = "tenant"

# -- RelationType（记忆关系） ------------------------------------------------

RELATION_TYPE_SUPERSEDES = "supersedes"
RELATION_TYPE_DERIVED_FROM = "derived_from"
RELATION_TYPE_RELATED = "related"


class MemoryKind(StrEnum):
    """记忆类别（设计 §2.7；W6 裁定 §9-1，**冻结**）。"""

    SHORT_TERM = MEMORY_KIND_SHORT_TERM
    LONG_TERM = MEMORY_KIND_LONG_TERM
    PROJECT = MEMORY_KIND_PROJECT
    AGENT = MEMORY_KIND_AGENT
    USER = MEMORY_KIND_USER

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class ScopeType(StrEnum):
    """隔离作用域维度（设计 §2.7；W6 裁定 §9-3）。"""

    USER = SCOPE_TYPE_USER
    AGENT = SCOPE_TYPE_AGENT
    PROJECT = SCOPE_TYPE_PROJECT
    WORKSPACE = SCOPE_TYPE_WORKSPACE
    CONVERSATION = SCOPE_TYPE_CONVERSATION

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class Visibility(StrEnum):
    """可见性（**显式**，替代隐含语义，R-19）。"""

    PRIVATE = VISIBILITY_PRIVATE
    WORKSPACE = VISIBILITY_WORKSPACE
    TENANT = VISIBILITY_TENANT

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class RelationType(StrEnum):
    """记忆关系类型（设计 §2.7）。"""

    SUPERSEDES = RELATION_TYPE_SUPERSEDES
    DERIVED_FROM = RELATION_TYPE_DERIVED_FROM
    RELATED = RELATION_TYPE_RELATED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


def _normalize(value: str | StrEnum) -> str:
    """将枚举 / 字符串统一为字面值。"""
    return value.value if isinstance(value, StrEnum) else str(value)


def _assert_membership(*, value: str | StrEnum, allowed: tuple[str, ...], field: str) -> str:
    """断言 ``value`` 属于 ``allowed``，否则抛 ``DomainError(VALIDATION_ERROR)``。

    Args:
        value: 待校验值（枚举 / 字符串）。
        allowed: 合法字面值集合。
        field: 字段名（用于错误 ``data``）。

    Returns:
        归一化后的合法字面值。

    Raises:
        DomainError: 值非法（``VALIDATION_ERROR``）。
    """
    normalized = _normalize(value)
    if normalized not in allowed:
        raise DomainError(
            f"非法 {field}：{normalized!r}（合法值：{list(allowed)}）",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "invalid_memory_value", "field": field, "value": normalized},
        )
    return normalized


def assert_memory_kind(value: str | MemoryKind) -> str:
    """断言 ``kind`` 合法，返回归一化字面值。"""
    return _assert_membership(value=value, allowed=MemoryKind.values(), field="kind")


def assert_scope_type(value: str | ScopeType) -> str:
    """断言 ``scope_type`` 合法，返回归一化字面值。"""
    return _assert_membership(value=value, allowed=ScopeType.values(), field="scope_type")


def assert_visibility(value: str | Visibility) -> str:
    """断言 ``visibility`` 合法，返回归一化字面值。"""
    return _assert_membership(value=value, allowed=Visibility.values(), field="visibility")


def assert_relation_type(value: str | RelationType) -> str:
    """断言 ``relation`` 合法，返回归一化字面值。"""
    return _assert_membership(value=value, allowed=RelationType.values(), field="relation")
