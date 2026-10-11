"""Workspace 用例（Command / Query）。

命令：创建 / 更新设置；查询：列表 / 详情。处理器委托
:class:`~astra_workspace.WorkspaceService`，返回应用层 DTO。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_workspace import WorkspaceService

from ..dto.workspace import WorkspaceDTO
from .base import Command

__all__ = [
    "CreateWorkspaceCommand",
    "CreateWorkspaceHandler",
    "UpdateWorkspaceSettingsCommand",
    "UpdateWorkspaceSettingsHandler",
]


@dataclass
class CreateWorkspaceCommand(Command):
    """创建工作区命令。"""

    tenant_id: str = ""
    owner_id: str = ""
    name: str = ""
    workspace_type: str = "personal"
    settings: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


class CreateWorkspaceHandler:
    """创建工作区命令处理器。"""

    def __init__(self, workspaces: WorkspaceService) -> None:
        self._workspaces = workspaces

    def handle(self, command: CreateWorkspaceCommand) -> WorkspaceDTO:
        """执行创建工作区并返回 DTO。"""
        workspace = self._workspaces.create(
            tenant_id=command.tenant_id,
            owner_id=command.owner_id,
            name=command.name,
            workspace_type=command.workspace_type,
            settings=command.settings,
            config=command.config,
        )
        return WorkspaceDTO.from_entity(workspace)


@dataclass
class UpdateWorkspaceSettingsCommand(Command):
    """更新工作区设置命令。"""

    workspace_id: str = ""
    tenant_id: str = ""
    settings: dict[str, Any] = field(default_factory=dict)


class UpdateWorkspaceSettingsHandler:
    """更新工作区设置命令处理器。"""

    def __init__(self, workspaces: WorkspaceService) -> None:
        self._workspaces = workspaces

    def handle(self, command: UpdateWorkspaceSettingsCommand) -> WorkspaceDTO:
        """执行更新工作区设置并返回 DTO。"""
        workspace = self._workspaces.update_settings(
            command.workspace_id,
            tenant_id=command.tenant_id,
            settings=command.settings,
        )
        return WorkspaceDTO.from_entity(workspace)
