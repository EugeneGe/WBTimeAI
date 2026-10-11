"""Astra AI 工作区能力包（``astra_workspace``）。

**叶能力包**：仅依赖 ``common`` / ``core`` / ``domain`` / ``database``
（**不依赖** ``application`` / ``api``）。ORM 持久化实现落于
:mod:`astra_workspace.repositories`（Workspace 聚合的归属能力包）。

W7（T2-37）新增（能力包自含布局，R1）：``Project`` / ``WorkspaceEnvironment`` 实体与
``ProjectRepository`` / ``WorkspaceEnvironmentRepository`` Protocol 落
``astra_workspace.domain``，SQL 实现落 ``astra_workspace.repositories.project_repository``。
既有 ``Workspace`` 实体 / ``WorkspaceRepository`` Protocol **原地不动**（仍在 ``astra_domain``）。
"""

from __future__ import annotations

from .application import CloneResult, ProjectService, TaskDispatcher
from .domain import (
    Project,
    ProjectRepository,
    WorkspaceEnvironment,
    WorkspaceEnvironmentRepository,
)
from .environment import EnvironmentService
from .factory import WorkspaceServices, build_workspace_services
from .files import FileService
from .git import GitService
from .mappers import workspace_to_domain, workspace_to_orm
from .paths import ManagedWorkspacePaths, is_safe_path_segment, resolve_workspace_root
from .project_storage import ProjectStorage
from .repositories import (
    SqlProjectRepository,
    SqlWorkspaceEnvironmentRepository,
    SqlWorkspaceRepository,
)
from .services import WorkspaceService

__all__ = [
    # 既有服务 / 工厂
    "WorkspaceService",
    "WorkspaceServices",
    "build_workspace_services",
    "SqlWorkspaceRepository",
    "workspace_to_domain",
    "workspace_to_orm",
    # W7 / T2-37：Project / Environment 实体与仓储
    "Project",
    "WorkspaceEnvironment",
    "ProjectRepository",
    "WorkspaceEnvironmentRepository",
    "SqlProjectRepository",
    "SqlWorkspaceEnvironmentRepository",
    # W7 / T2-38：Files / Environment / Git / 项目克隆编排用例
    "FileService",
    "EnvironmentService",
    "GitService",
    "ProjectService",
    "CloneResult",
    "TaskDispatcher",
    # R1 / T2-55：受管工作区路径（UUID 派生 + containment）与生命周期
    "ManagedWorkspacePaths",
    "ProjectStorage",
    "resolve_workspace_root",
    "is_safe_path_segment",
]
