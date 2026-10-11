"""系统相关 Phase 0 事件（继承 ``astra_core.events.DomainEvent``）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = ["SystemStarted", "SystemShutdown", "DefaultTenantInitialized"]


@dataclass
class SystemStarted(DomainEvent):
    """系统启动事件（``system.started``）。"""

    type: ClassVar[str] = "system.started"

    @classmethod
    def create(cls, *, mode: str | None = None, version: str | None = None) -> SystemStarted:
        """便捷构造。"""
        payload: dict[str, Any] = {}
        if mode is not None:
            payload["mode"] = mode
        if version is not None:
            payload["version"] = version
        return cls(payload=payload)


@dataclass
class SystemShutdown(DomainEvent):
    """系统关闭事件（``system.shutdown``）。"""

    type: ClassVar[str] = "system.shutdown"

    @classmethod
    def create(cls, *, reason: str | None = None) -> SystemShutdown:
        """便捷构造。"""
        payload: dict[str, Any] = {}
        if reason is not None:
            payload["reason"] = reason
        return cls(payload=payload)


@dataclass
class DefaultTenantInitialized(DomainEvent):
    """默认租户初始化事件（``system.default_tenant_initialized``）。"""

    type: ClassVar[str] = "system.default_tenant_initialized"

    @classmethod
    def create(cls, *, tenant_id: str, slug: str | None = None) -> DefaultTenantInitialized:
        """便捷构造。"""
        payload: dict[str, Any] = {"tenant_id": tenant_id}
        if slug is not None:
            payload["slug"] = slug
        return cls(payload=payload)
