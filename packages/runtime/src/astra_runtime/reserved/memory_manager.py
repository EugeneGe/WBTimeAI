"""RP-03 · ``MemoryManager``（记忆管理预留位；总纲 §12.2）。

Phase 1 仅提供**完整 Protocol 签名 + 可装配空实现**；Phase 2 填充实现时**不得改签名**。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import MemoryQuery, MemoryRecord

__all__ = ["MemoryManager", "NullMemoryManager"]


@runtime_checkable
class MemoryManager(Protocol):
    """记忆管理器（RP-03）。"""

    def remember(self, record: MemoryRecord) -> None:
        """写入一条记忆。

        Raises:
            DomainError: 写入失败（``INTERNAL_ERROR``）。
        """
        ...

    def recall(self, query: MemoryQuery) -> list[MemoryRecord]:
        """按查询召回记忆（无匹配返回空列表）。"""
        ...


class NullMemoryManager:
    """空实现（Phase 1）：写入为无操作，召回恒返回空列表。"""

    def remember(self, record: MemoryRecord) -> None:
        """无操作。"""
        return None

    def recall(self, query: MemoryQuery) -> list[MemoryRecord]:
        """恒返回空列表。"""
        return []
