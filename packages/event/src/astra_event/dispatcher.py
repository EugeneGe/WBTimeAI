"""事件分发器（按 ``event.type`` 匹配、同步/异步 handler、异常隔离）。"""

from __future__ import annotations

import asyncio
import inspect
import logging

from astra_core import DomainEvent

from .base import HandlerFn

__all__ = ["EventDispatcher"]

_logger = logging.getLogger("astra_event.dispatcher")


class EventDispatcher:
    """事件分发器。

    维护 ``事件类型 → 处理器列表`` 订阅表，并在分发时**隔离异常**：
    单个处理器失败不影响其余处理器，也不向发布方抛出（记录结构化日志）。
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerFn]] = {}

    def register(self, event_type: str, handler: HandlerFn) -> None:
        """注册处理器（同一处理器重复注册只保留一次）。"""
        handlers = self._handlers.setdefault(event_type, [])
        if handler not in handlers:
            handlers.append(handler)

    def unregister(self, event_type: str, handler: HandlerFn) -> None:
        """注销处理器。"""
        handlers = self._handlers.get(event_type)
        if not handlers:
            return
        if handler in handlers:
            handlers.remove(handler)
        if not handlers:
            self._handlers.pop(event_type, None)

    def clear(self) -> None:
        """清空全部订阅。"""
        self._handlers.clear()

    def handlers_for(self, event_type: str) -> list[HandlerFn]:
        """返回某事件类型的处理器列表（副本）。"""
        return list(self._handlers.get(event_type, []))

    def dispatch(self, event: DomainEvent) -> None:
        """同步分发事件至匹配处理器。"""
        for handler in self.handlers_for(event.type):
            self._invoke_sync(handler, event)

    async def dispatch_async(self, event: DomainEvent) -> None:
        """异步分发事件至匹配处理器。"""
        for handler in self.handlers_for(event.type):
            await self._invoke_async(handler, event)

    def _invoke_sync(self, handler: HandlerFn, event: DomainEvent) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                self._run_awaitable(result)
        except Exception:  # noqa: BLE001 - 异常隔离是分发器职责
            _logger.exception(
                "event.handler.failed",
                extra={"event": "event.handler.failed", "event_type": event.type},
            )

    async def _invoke_async(self, handler: HandlerFn, event: DomainEvent) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - 异常隔离是分发器职责
            _logger.exception(
                "event.handler.failed",
                extra={"event": "event.handler.failed", "event_type": event.type},
            )

    @staticmethod
    def _run_awaitable(awaitable: object) -> None:
        """在同步上下文中执行可等待对象。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(awaitable)  # type: ignore[arg-type]
        else:
            loop.create_task(awaitable)  # type: ignore[arg-type]
