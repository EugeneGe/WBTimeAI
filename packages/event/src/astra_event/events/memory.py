"""Memory 写入事件（Phase 2 · W3 / T2-16；设计 §2.11；裁定 §6.1）。

1 类事件，**继承** :class:`astra_core.events.DomainEvent`（事件基类唯一，C-02）：

- ``MemoryWritten``：``memory.written`` —— 记忆写入（按 ``scope`` 归属）。

🔴 2a **先定义类型**，2c 消费触发；本模块**只定义事件类型**，``EventBus`` Protocol 不变（C-02）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = ["MemoryWritten"]


@dataclass
class MemoryWritten(DomainEvent):
    """记忆写入事件（``memory.written``）。"""

    type: ClassVar[str] = "memory.written"

    @classmethod
    def create(
        cls,
        *,
        memory_id: str,
        scope: str,
        key: str | None = None,
    ) -> MemoryWritten:
        """便捷构造。"""
        payload: dict[str, Any] = {"memory_id": memory_id, "scope": scope}
        if key is not None:
            payload["key"] = key
        return cls(payload=payload)
