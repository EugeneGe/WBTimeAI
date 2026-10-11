"""``LocalEventBus``（进程内发布 / 订阅）。"""

from __future__ import annotations

from astra_core import DomainEvent

from .base import HandlerFn
from .dispatcher import EventDispatcher

__all__ = ["LocalEventBus"]


class LocalEventBus:
    """进程内事件总线（local 模式默认实现）。

    实现 :class:`~astra_event.base.EventBus` Protocol；内部委托
    :class:`~astra_event.dispatcher.EventDispatcher` 完成匹配与分发。
    """

    def __init__(self, dispatcher: EventDispatcher | None = None) -> None:
        self._dispatcher = dispatcher or EventDispatcher()

    def publish(self, event: DomainEvent) -> None:
        """发布事件（同步分发）。"""
        self._dispatcher.dispatch(event)

    async def publish_async(self, event: DomainEvent) -> None:
        """异步发布事件。"""
        await self._dispatcher.dispatch_async(event)

    def subscribe(self, event_type: str, handler: HandlerFn) -> None:
        """订阅指定事件类型。"""
        self._dispatcher.register(event_type, handler)

    def unsubscribe(self, event_type: str, handler: HandlerFn) -> None:
        """取消订阅。"""
        self._dispatcher.unregister(event_type, handler)

    @property
    def dispatcher(self) -> EventDispatcher:
        """底层分发器（便于测试）。"""
        return self._dispatcher
