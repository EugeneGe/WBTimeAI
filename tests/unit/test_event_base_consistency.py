"""事件基类唯一性断言（避免重复定义基类，§2R.0.1 硬约束）。"""

from __future__ import annotations

from pathlib import Path

from astra_core import DomainEvent as CoreDomainEvent
from astra_domain import DomainEvent as DomainLayerEvent
from astra_event import (
    DefaultTenantInitialized,
    SystemShutdown,
    SystemStarted,
    UserLoggedIn,
    UserLoggedOut,
    UserRegistered,
    WorkspaceCreated,
    WorkspaceUpdated,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENT_PKG = REPO_ROOT / "packages" / "event" / "src" / "astra_event"

_CONCRETE_EVENTS = [
    UserRegistered,
    UserLoggedIn,
    UserLoggedOut,
    WorkspaceCreated,
    WorkspaceUpdated,
    SystemStarted,
    SystemShutdown,
    DefaultTenantInitialized,
]


def test_domain_layer_reexports_same_base() -> None:
    assert DomainLayerEvent is CoreDomainEvent


def test_concrete_events_subclass_core_domain_event() -> None:
    for event_cls in _CONCRETE_EVENTS:
        assert issubclass(event_cls, CoreDomainEvent)
        assert event_cls.type != "domain.event"


def test_astra_event_defines_no_event_base_class() -> None:
    """``astra_event`` 不得定义事件基类（仅机制层）。"""
    base_text = (EVENT_PKG / "base.py").read_text(encoding="utf-8")
    assert "class DomainEvent" not in base_text
    for path in EVENT_PKG.rglob("*.py"):
        if "events" in path.parts:
            continue
        assert "class DomainEvent" not in path.read_text(encoding="utf-8")
