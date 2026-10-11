"""``MemoryService``——Memory 用例编排器（W6 / T2-35；设计 §2.7 / 裁定 §2.4 F-d / F-h）。

**应用/用例层（第三类）**：编排「按 scope 浏览记忆 / 删除记忆」，**零** Web / ORM
（``test_application_import_boundary`` 强制）。

- :meth:`list_memories`：按 ``scope_type`` / ``scope_id`` / ``kind`` 浏览（**F-d** 读契约）；
- :meth:`delete_memory`：按 id 删除（**F-h** ``DELETE /memory/{id}``；不存在 → ``NOT_FOUND``）。

🔴 **并行对齐备注（重要）**：W6 后端流（``T2-32``→``T2-34``）**拥有** ``packages/memory/**``
   （`MemoryStore` Protocol / SQL 实现 / 组合工厂）。本服务**不 hard-import** ``astra_memory``，
   而是面向**应用层自持的结构化端口** :class:`MemoryStorePort` 取用——由后端流在**组合根**
   以适配器注入其 ``build_memory_store`` 产物（或直接实现同名方法）。
   在后端流落库前，:func:`resolve_memory_store` 回退 :class:`NullMemoryStore`，
   使 ``/memory`` 端点**保持可响应**（统一响应壳；空列表 / 删除 404），
   待后端流落库后自动接管真实存储（**加性**、零改本服务）。

🔴 多租户隔离：``tenant_id`` **强制**（任何浏览 / 删除先按租户过滤，I-2/I-3）。
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode

from ..dto.memory import MemoryViewDTO
from .base import ApplicationService

__all__ = [
    "DEFAULT_MEMORY_LIMIT",
    "MemoryStorePort",
    "NullMemoryStore",
    "MemoryService",
    "build_memory_service",
    "resolve_memory_store",
]

#: 浏览默认条数（F-d ``limit``）。
DEFAULT_MEMORY_LIMIT = 50


@runtime_checkable
class MemoryStorePort(Protocol):
    """Memory 浏览 / 删除端口（应用层自持；后端流 ``MemoryStore`` 经适配器注入）。

    🔴 结构化契约：后端流 ``build_memory_store(...)`` 产物只需实现下列方法即满足本端口
       （或由组合根薄适配器转调 ``search`` / ``delete``）。
    """

    def list_by_scope(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        kind: str | None = None,
        limit: int = DEFAULT_MEMORY_LIMIT,
    ) -> list[Any]:
        """按隔离维度列出记忆（无匹配返回空列表）。"""
        ...

    def delete(self, memory_id: str, *, tenant_id: str) -> bool:
        """删除一条记忆（返回是否命中；跨租户视为未命中）。"""
        ...


class NullMemoryStore:
    """占位存储（后端流落库前的**确定性**回退；**非** 运行时 try/except 推断）。"""

    def list_by_scope(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        kind: str | None = None,
        limit: int = DEFAULT_MEMORY_LIMIT,
    ) -> list[Any]:  # noqa: ARG002 - 端口签名一致
        """恒空（后端流未装配真实存储时）。"""
        return []

    def delete(self, memory_id: str, *, tenant_id: str) -> bool:  # noqa: ARG002 - 端口签名一致
        """恒未命中（后端流未装配真实存储时）。"""
        return False


class MemoryService(ApplicationService):
    """Memory 用例编排器（DI 注入 :class:`MemoryStorePort`；零 ORM）。"""

    store: MemoryStorePort

    def __init__(self, *, store: MemoryStorePort) -> None:
        """装配用例编排器（存储由**组合根**注入）。

        Args:
            store: 记忆存储端口（后端流 ``MemoryStore`` 或其适配器）。
        """
        super().__init__(store=store)

    def list_memories(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        kind: str | None = None,
        limit: int = DEFAULT_MEMORY_LIMIT,
    ) -> list[MemoryViewDTO]:
        """按 scope 浏览记忆（**F-d** 读契约）。

        Args:
            tenant_id: 租户标识（隔离不变量，强制）。
            scope_type: 作用域类型（`user|agent|project|workspace|conversation`；可空）。
            scope_id: 作用域标识（可空）。
            kind: 记忆类别（`SHORT_TERM|LONG_TERM|PROJECT|AGENT|USER`；可空）。
            limit: 条数上限（``<=0`` 取默认）。

        Returns:
            :class:`~astra_application.dto.memory.MemoryViewDTO` 列表。
        """
        effective_limit = int(limit) if int(limit) > 0 else DEFAULT_MEMORY_LIMIT
        records = self.store.list_by_scope(
            tenant_id=tenant_id,
            scope_type=scope_type,
            scope_id=scope_id,
            kind=kind,
            limit=effective_limit,
        )
        return [MemoryViewDTO.from_entity(record) for record in records]

    def delete_memory(self, memory_id: str, *, tenant_id: str) -> None:
        """删除一条记忆（**F-h**；不存在 / 跨租户 → ``NOT_FOUND``）。

        Raises:
            DomainError: 未命中（``NOT_FOUND``）。
        """
        deleted = self.store.delete(memory_id, tenant_id=tenant_id)
        if not deleted:
            raise DomainError(
                "记忆不存在",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "memory_not_found", "memory_id": memory_id},
            )


class _SearchStoreAdapter:
    """薄适配器：把后端流 ``MemoryStore``（``search`` / ``delete`` 面）适配为端口。

    🔴 组合根薄委托、零业务逻辑：把「按 scope 浏览」转调后端 ``search(**kwargs)``，
    「删除」转调后端 ``delete(id, *, tenant_id)``；参数名与后端流冻结面
    （``astra_memory.store.MemoryStore``，裁定 §5.4 / F-g）一致。
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def list_by_scope(
        self,
        *,
        tenant_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        kind: str | None = None,
        limit: int = DEFAULT_MEMORY_LIMIT,
    ) -> list[Any]:
        """转调后端 ``search``（按隔离维度；异常 → 空，不抛）。"""
        try:
            return list(
                self._store.search(
                    tenant_id=tenant_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    kinds=[kind] if kind else None,
                    limit=limit,
                )
            )
        except Exception:  # noqa: BLE001 - 后端签名演进期保守降级（组合根可换显式适配）
            return []

    def delete(self, memory_id: str, *, tenant_id: str) -> bool:
        """删除一条记忆（命中 → ``True``；缺失 / 跨租户 → ``False``）。

        后端 ``MemoryStore.delete`` 冻结签名为 ``-> None``（幂等、跨租户不可删），
        故优先经 ``store.repository.get`` 做**存在性 + 租户**预检，以支撑 F-h
        ``不存在 → 404`` 语义；无 ``get`` 时以 ``delete`` 返回值兜底判定。
        """
        store_delete = getattr(self._store, "delete", None)
        if not callable(store_delete):
            return False
        repository = getattr(self._store, "repository", None)
        getter = getattr(repository, "get", None)
        try:
            if callable(getter):
                existing = getter(memory_id)
                if existing is None or str(getattr(existing, "tenant_id", "") or "") != tenant_id:
                    return False
                store_delete(memory_id, tenant_id=tenant_id)
                return True
            result = store_delete(memory_id, tenant_id=tenant_id)
        except Exception:  # noqa: BLE001 - 后端签名演进期：视为未命中（不误报成功）
            return False
        if isinstance(result, bool):
            return result
        if isinstance(result, int):
            return result > 0
        return True


def build_memory_service(*, store: MemoryStorePort) -> MemoryService:
    """装配 :class:`MemoryService`（显式注入存储端口；供组合根 / 测试）。"""
    return MemoryService(store=store)


def _adapt_store(store: Any) -> MemoryStorePort:
    """把后端流存储（``MemoryStore``）适配为 :class:`MemoryStorePort`。"""
    if isinstance(store, MemoryStorePort):
        return store
    if hasattr(store, "search") and hasattr(store, "delete"):
        return _SearchStoreAdapter(store)
    return NullMemoryStore()


def resolve_memory_store(
    session_factory: Any,
    *,
    store: Any | None = None,
    vector_search: bool = False,
    embedding_dimensions: int = 1536,
) -> MemoryStorePort:
    """解析记忆存储端口（**组合根**接线）。

    - **优先**直接采用组合根已装配的 ``store``（＝ ``providers.memory_store``，T2-34
      Provider 层按同一 capability 装配的 ``MemoryStore``）；
    - 否则尽力经 ``astra_memory.build_memory_store`` 就地装配（传必需 ``vector_search`` /
      ``embedding_dimensions``）；
    - **任何装配期异常**（含后端流并行 WIP 的 import 期错误）均确定性回退占位存储，
      使端点保持可响应（**非** 运行时 try/except 能力推断）。

    Args:
        session_factory: 数据库会话工厂（就地装配时透传给后端流工厂）。
        store: 组合根已装配的 ``MemoryStore``（可空；非空则优先采用）。
        vector_search: 向量检索能力（就地装配时透传）。
        embedding_dimensions: 嵌入维度（就地装配时透传）。

    Returns:
        已装配的 :class:`MemoryStorePort`（真实 or 占位）。
    """
    if store is not None:
        return _adapt_store(store)
    try:
        module = importlib.import_module("astra_memory")
    except Exception:  # noqa: BLE001 - 后端流并行 WIP：import 期异常亦回退占位
        return NullMemoryStore()
    factory = getattr(module, "build_memory_store", None)  # 后端流 T2-34 产出
    if not callable(factory):
        return NullMemoryStore()
    try:
        built = factory(
            session_factory=session_factory,
            vector_search=vector_search,
            embedding_dimensions=embedding_dimensions,
        )
    except Exception:  # noqa: BLE001 - 后端流签名演进期：装配失败即回退占位
        return NullMemoryStore()
    return _adapt_store(built)
