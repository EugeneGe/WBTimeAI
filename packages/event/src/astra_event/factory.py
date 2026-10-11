"""event 组合工厂（**模式无关**）。"""

from __future__ import annotations

from .bus import LocalEventBus
from .dispatcher import EventDispatcher

__all__ = ["create_local_event_bus"]


def create_local_event_bus() -> LocalEventBus:
    """创建进程内事件总线（模式无关；mode 分流仅在 ``providers.py``）。"""
    return LocalEventBus(EventDispatcher())
