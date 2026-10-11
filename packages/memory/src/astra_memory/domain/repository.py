"""``astra_memory`` 仓储接口（**仅 Protocol**，零 ORM；设计 §2.7 / W6 裁定 §5.3）。

- :class:`MemoryRepository`：``memory`` 聚合仓储（隔离过滤召回 + TTL 清理）；
- :class:`MemoryRelationRepository`：``memory_relation`` 关系仓储。

🔴 **独立 Protocol（不继承 ``Repository[T]``）**：设计 §5.3 冻结的租户作用域删除签名
   ``delete(memory_id, *, tenant_id)`` 与 ``astra_domain.Repository.delete(entity)`` **互斥**
   （同名不同形），故本接口自包含声明 ``get`` / ``add`` / ``list`` / ``update`` /
   ``delete``（对齐设计签名，**零改签名**）。
SQLAlchemy 实现落本包 ``repositories/``（能力包显式允许的 ORM 落点）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .entities import Memory, MemoryRelation

__all__ = ["MemoryRepository", "MemoryRelationRepository"]


@runtime_checkable
class MemoryRepository(Protocol):
    """``memory`` 聚合仓储接口（**强制 ``tenant_id`` 过滤**，隔离不变量 I-2/I-3）。"""

    def get(self, memory_id: str) -> Memory | None:
        """按主键获取记忆，不存在返回 ``None``。"""
        ...

    def add(self, entity: Memory) -> Memory:
        """新增记忆并返回。"""
        ...

    def list(self, **filters: Any) -> builtins.list[Memory]:
        """按等值条件列出记忆。"""
        ...

    def update(self, entity: Memory) -> Memory:
        """更新记忆并返回。"""
        ...

    def delete(self, memory_id: str, *, tenant_id: str) -> None:
        """按 ``(memory_id, tenant_id)`` 删除记忆（**跨租户不可删**）。"""
        ...

    def search(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        visibility: builtins.list[str] | None = None,
        kinds: builtins.list[str] | None = None,
        text: str | None = None,
        limit: int = 10,
        now: datetime | None = None,
    ) -> builtins.list[Memory]:
        """按隔离维度召回记忆（**先**按 ``tenant_id`` / 作用域 / 可见性过滤，再排序）。

        过滤语义（W6 裁定 §3.3 / §9-3）：

        - ``tenant_id`` **强制**（必填）；
        - ``visibility`` 非空 → 仅取集合内可见性；
        - ``kinds`` 非空 → 仅取集合内类别（非用户触发时用以排除 ``USER``，B5）；
        - ``text`` 非空 → ``content`` 关键字子串匹配（SQLite 退化路）；
        - ``now`` 非空 → 排除 ``expires_at`` 已过期的行（TTL）。
        """
        ...

    def list_by_scope(
        self,
        *,
        tenant_id: str,
        scope_type: str,
        scope_id: str,
        limit: int | None = None,
    ) -> builtins.list[Memory]:
        """列出某租户内某作用域下的记忆（按创建时间倒序）。"""
        ...

    def get_by_source_run(self, run_id: str) -> builtins.list[Memory]:
        """列出某 Run 产出的全部记忆（溯源 / 去重）。"""
        ...

    def prune(self, *, now: datetime) -> int:
        """清理已到期记忆（``expires_at IS NOT NULL AND expires_at <= now``），返回条数。"""
        ...


@runtime_checkable
class MemoryRelationRepository(Protocol):
    """``memory_relation`` 关系仓储接口。"""

    def get(self, relation_id: str) -> MemoryRelation | None:
        """按主键获取关系，不存在返回 ``None``。"""
        ...

    def add(self, entity: MemoryRelation) -> MemoryRelation:
        """新增关系并返回。"""
        ...

    def list(self, **filters: Any) -> builtins.list[MemoryRelation]:
        """按等值条件列出关系。"""
        ...

    def list_by_from(self, from_memory_id: str) -> builtins.list[MemoryRelation]:
        """列出某源记忆的全部出边关系。"""
        ...

    def list_by_to(self, to_memory_id: str) -> builtins.list[MemoryRelation]:
        """列出某目标记忆的全部入边关系。"""
        ...

    def delete_by_memory(self, memory_id: str) -> int:
        """删除与某记忆相关的**全部**关系（出边 + 入边；``forget`` 显式级联，§13-e）。"""
        ...
