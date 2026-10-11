"""Workspace 相关 DTO（设计 §2.9；应用层，零框架依赖）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astra_domain import Workspace, WorkspaceType

from .base import DTO

__all__ = [
    "WorkspaceDTO",
    "CreateWorkspaceDTO",
    "UpdateWorkspaceSettingsDTO",
]


@dataclass
class WorkspaceDTO(DTO):
    """工作区 DTO。"""

    id: str
    tenant_id: str | None
    owner_id: str
    name: str
    workspace_type: str = WorkspaceType.PERSONAL.value
    settings: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: Workspace) -> WorkspaceDTO:
        """由领域实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            owner_id=entity.owner_id,
            name=entity.name,
            workspace_type=str(entity.workspace_type),
            settings=dict(entity.settings) if entity.settings else {},
            config=dict(entity.config) if entity.config else {},
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


@dataclass
class CreateWorkspaceDTO(DTO):
    """创建工作区入参 DTO。"""

    name: str
    workspace_type: str = WorkspaceType.PERSONAL.value
    settings: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpdateWorkspaceSettingsDTO(DTO):
    """更新工作区设置入参 DTO。"""

    settings: dict[str, Any] = field(default_factory=dict)
