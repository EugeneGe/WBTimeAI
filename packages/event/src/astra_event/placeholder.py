"""``UnsupportedEventBus``（server 模式占位，抛 ``NotImplementedYetError``）。

非静默降级：接口齐备、应用可启动，但**首次调用**即显式抛错（错误码
``NOT_IMPLEMENTED`` / HTTP 501）。
"""

from __future__ import annotations

from astra_core import DomainEvent, NotImplementedYetError

from .base import HandlerFn

__all__ = ["UnsupportedEventBus"]


class UnsupportedEventBus:
    """server 模式事件总线占位（Redis Stream 目标，Team 阶段）。"""

    def __init__(self, *, feature: str, available_in: str) -> None:
        self.feature = feature
        self.available_in = available_in

    def _raise(self, operation: str) -> None:
        raise NotImplementedYetError(
            f"事件总线能力「{self.feature}」尚未实现（目标阶段：{self.available_in}）；"
            f"当前调用：{operation}。请使用 ASTRA_MODE=local 以获得进程内实现。",
            data={"feature": self.feature, "available_in": self.available_in},
        )

    def publish(self, event: DomainEvent) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("publish")

    def subscribe(self, event_type: str, handler: HandlerFn) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("subscribe")

    def unsubscribe(self, event_type: str, handler: HandlerFn) -> None:  # noqa: ARG002
        """占位：抛 ``NotImplementedYetError``。"""
        self._raise("unsubscribe")
