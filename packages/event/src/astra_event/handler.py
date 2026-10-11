"""事件处理器（``EventHandler`` Protocol + ``FunctionHandler`` + ``handler_for`` 装饰器）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from astra_core import DomainEvent

from .base import HandlerFn

__all__ = ["EventHandler", "FunctionHandler", "handler_for", "get_event_type"]

#: ``handler_for`` 在函数上标注的事件类型属性名。
EVENT_TYPE_ATTR = "__astra_event_type__"


@runtime_checkable
class EventHandler(Protocol):
    """事件处理器接口。"""

    def __call__(self, event: DomainEvent) -> object:
        """处理事件（可返回 None 或可等待对象）。"""
        ...


class FunctionHandler:
    """把普通函数包装为可自描述的事件处理器。

    Attributes:
        event_type: 该处理器关注的事件类型（可为 ``None``，由订阅时显式指定）。
        func: 被包装的函数。
    """

    def __init__(self, func: HandlerFn, event_type: str | None = None) -> None:
        self.func = func
        self.event_type = event_type or get_event_type(func)

    @classmethod
    def from_callable(cls, func: HandlerFn) -> FunctionHandler:
        """由函数构造处理器（自动读取 ``handler_for`` 标注的事件类型）。"""
        return cls(func)

    @property
    def __name__(self) -> str:  # noqa: D105
        return getattr(self.func, "__name__", "handler")

    def __call__(self, event: DomainEvent) -> object:
        """调用底层函数。"""
        return self.func(event)


def handler_for(event_type: str) -> Callable[[HandlerFn], HandlerFn]:
    """处理器装饰器：声明该函数关注的事件类型。

    Args:
        event_type: 事件类型标识（如 ``user.registered``）。

    Returns:
        装饰器函数。
    """

    def decorator(func: HandlerFn) -> HandlerFn:
        setattr(func, EVENT_TYPE_ATTR, event_type)
        return func

    return decorator


def get_event_type(func: object) -> str | None:
    """读取函数上 ``handler_for`` 标注的事件类型（无则 ``None``）。"""
    return getattr(func, EVENT_TYPE_ATTR, None)
