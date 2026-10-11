"""Workspace 相关 Phase 0 事件（继承 ``astra_core.events.DomainEvent``）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = ["WorkspaceCreated", "WorkspaceUpdated"]


@dataclass
class WorkspaceCreated(DomainEvent):
    """Workspace 创建事件（``workspace.created``）。"""

    type: ClassVar[str] = "workspace.created"

    @classmethod
    def create(
        cls, *, workspace_id: str, tenant_id: str | None = None, owner_id: str | None = None
    ) -> WorkspaceCreated:
        """便捷构造。"""
        payload: dict[str, Any] = {"workspace_id": workspace_id}
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id
        if owner_id is not None:
            payload["owner_id"] = owner_id
        return cls(payload=payload)


@dataclass
class WorkspaceUpdated(DomainEvent):
    """Workspace 更新事件（``workspace.updated``）。"""

    type: ClassVar[str] = "workspace.updated"

    @classmethod
    def create(cls, *, workspace_id: str, changed: list[str] | None = None) -> WorkspaceUpdated:
        """便捷构造。"""
        payload: dict[str, Any] = {"workspace_id": workspace_id}
        if changed is not None:
            payload["changed"] = changed
        return cls(payload=payload)
