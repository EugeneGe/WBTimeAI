"""事件总线抽象（``EventBus`` Protocol + 处理器类型别名）。

🔴 本模块**只**定义接口与类型别名，**不定义事件基类**——
   事件基类唯一为 :class:`astra_core.events.DomainEvent`（对齐 §2R.0.1 硬约束）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from astra_core import DomainEvent

__all__ = [
    "SyncHandler",
    "AsyncHandler",
    "HandlerFn",
    "EventBus",
]

#: 同步处理器：接收事件、无返回。
SyncHandler = Callable[[DomainEvent], None]

#: 异步处理器：接收事件、返回可等待对象。
AsyncHandler = Callable[[DomainEvent], Awaitable[None]]

#: 处理器函数（同步或异步）。
HandlerFn = SyncHandler | AsyncHandler


@runtime_checkable
class EventBus(Protocol):
    """事件总线接口。

    演进路径（**接口不变**）：``LocalEventBus（进程内）→ Redis Stream → Kafka``。
    """

    def publish(self, event: DomainEvent) -> None:
        """发布事件（同步分发至已订阅处理器）。"""
        ...

    def subscribe(self, event_type: str, handler: HandlerFn) -> None:
        """订阅指定事件类型。"""
        ...

    def unsubscribe(self, event_type: str, handler: HandlerFn) -> None:
        """取消订阅指定事件类型。"""
        ...
