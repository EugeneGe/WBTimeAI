"""``astra_memory`` 领域实体（设计 §2.7；W6 裁定 §5.2）。

- :class:`Memory`：**可变聚合根**（承载 ``kind`` / 作用域 / 可见性 / 内容 / 权重 /
  向量 / TTL）；隔离三元组 ``scope_type`` + ``scope_id`` + ``visibility`` 与 **强制**
  ``tenant_id`` 共同定义隔离语义（R-19 / I-2 / I-3）。
- :class:`MemoryRelation`：轻量记忆关系行（``from → to`` + ``relation``）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from astra_common.time import utcnow
from astra_domain import AggregateRoot

from .kinds import (
    MEMORY_KIND_SHORT_TERM,
    RELATION_TYPE_RELATED,
    SCOPE_TYPE_USER,
    VISIBILITY_PRIVATE,
    RelationType,
    ScopeType,
    Visibility,
    assert_relation_type,
    assert_scope_type,
    assert_visibility,
)

__all__ = ["Memory", "MemoryRelation"]


@dataclass
class Memory(AggregateRoot):
    """一条记忆（**可变聚合根**；设计 §2.7 / W6 裁定 §5.2）。

    Attributes:
        tenant_id: 所属租户标识（**强制**，隔离不变量 I-2；基类字段）。
        workspace_id: 归属工作区标识（可空）。
        kind: 记忆类别（``MemoryKind`` 字面值）。
        scope_type: 隔离作用域维度（``ScopeType`` 字面值）。
        scope_id: 作用域标识（如 ``user_id`` / ``agent_id``；异质字符串）。
        visibility: 可见性（``Visibility`` 字面值，R-19）。
        content: 记忆文本。
        memory_type: 记忆内容类型（抽取器产出，如 ``fact`` / ``preference``）。
        importance: 重要度（召回权重项）。
        confidence: 置信度（抽取置信）。
        source_run_id: 来源 Run 标识（可空）。
        vector: 记忆向量（可空；SQLite / ``vector_search=false`` 恒 ``None``）。
        expires_at: 到期时间（可空；``SHORT_TERM`` 用）。
    """

    workspace_id: str | None = None
    kind: str = MEMORY_KIND_SHORT_TERM
    scope_type: str = SCOPE_TYPE_USER
    scope_id: str = ""
    visibility: str = VISIBILITY_PRIVATE
    content: str = ""
    memory_type: str = ""
    importance: float = 0.0
    confidence: float = 0.0
    source_run_id: str | None = None
    vector: list[float] | None = None
    expires_at: datetime | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        """是否已到期（无 ``expires_at`` → 永不过期）。

        Args:
            now: 参照时间（缺省 ＝ 当前 UTC）。

        Returns:
            ``True`` 表示 ``expires_at`` 已到 / 已过。
        """
        if self.expires_at is None:
            return False
        reference = now or utcnow()
        return self.expires_at <= reference

    def assert_valid(self) -> None:
        """断言隔离必需字段齐备（``scope_type`` / ``scope_id`` / ``visibility`` 合法）。

        Raises:
            DomainError: 非法值（``VALIDATION_ERROR``）。
        """
        assert_scope_type(self.scope_type)
        assert_visibility(self.visibility)


@dataclass
class MemoryRelation(AggregateRoot):
    """记忆关系（``from_memory_id → to_memory_id`` 间的一条命名关系）。

    Attributes:
        from_memory_id: 源记忆标识。
        to_memory_id: 目标记忆标识。
        relation: 关系类型（``RelationType`` 字面值）。
    """

    from_memory_id: str = ""
    to_memory_id: str = ""
    relation: str = RELATION_TYPE_RELATED

    def assert_valid(self) -> None:
        """断言关系类型合法。

        Raises:
            DomainError: 非法关系类型（``VALIDATION_ERROR``）。
        """
        assert_relation_type(self.relation)


# 显式 re-export 供类型注解 / 上层引用（保持 ``Domain`` 门面单一来源）。
_DEFAULT_SCOPE: str = ScopeType.USER.value
_DEFAULT_VISIBILITY: str = Visibility.PRIVATE.value
_DEFAULT_RELATION: str = RelationType.RELATED.value
