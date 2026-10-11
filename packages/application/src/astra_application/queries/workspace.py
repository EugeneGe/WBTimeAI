"""Workspace 查询（Query / QueryHandler）。"""

from __future__ import annotations

from dataclasses import dataclass

from astra_workspace import WorkspaceService

from ..dto.workspace import WorkspaceDTO
from .base import Query

__all__ = [
    "ListWorkspacesQuery",
    "ListWorkspacesHandler",
    "GetWorkspaceQuery",
    "GetWorkspaceHandler",
]


@dataclass
class ListWorkspacesQuery(Query):
    """列出某租户下的工作区。"""

    tenant_id: str = ""


class ListWorkspacesHandler:
    """列出工作区查询处理器。"""

    def __init__(self, workspaces: WorkspaceService) -> None:
        self._workspaces = workspaces

    def handle(self, query: ListWorkspacesQuery) -> list[WorkspaceDTO]:
        """返回工作区 DTO 列表。"""
        return [
            WorkspaceDTO.from_entity(workspace)
            for workspace in self._workspaces.list_for_tenant(query.tenant_id)
        ]


@dataclass
class GetWorkspaceQuery(Query):
    """获取单个工作区详情（租户校验）。"""

    workspace_id: str = ""
    tenant_id: str = ""


class GetWorkspaceHandler:
    """获取工作区详情查询处理器。"""

    def __init__(self, workspaces: WorkspaceService) -> None:
        self._workspaces = workspaces

    def handle(self, query: GetWorkspaceQuery) -> WorkspaceDTO:
        """返回工作区 DTO（跨租户 → ``WORKSPACE_NOT_FOUND``）。"""
        workspace = self._workspaces.get(query.workspace_id, tenant_id=query.tenant_id)
        return WorkspaceDTO.from_entity(workspace)
