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

from .application import AttemptCheckoutResult, CloneResult, ProjectService, TaskDispatcher
from .application.change_review_service import (
    ApplyResult,
    ChangeReviewService,
    DiffView,
    GitCredentialProvider,
    GitWriteCredential,
    PushResult,
)
from .application.remote_task_service import (
    ArtifactView,
    ExecutionTaskEventSource,
    RemoteAccessDecision,
    RemoteAttemptView,
    RemoteDiffView,
    RemoteEventPage,
    RemotePrincipal,
    RemoteProjectStatus,
    RemoteTaskAuthorizer,
    RemoteTaskService,
    RemoteTaskSpec,
    RemoteTaskView,
    TaskEvent,
    TaskLogView,
)
from .domain import (
    Project,
    ProjectRepository,
    WorkspaceEnvironment,
    WorkspaceEnvironmentRepository,
)
from .environment import EnvironmentService
from .environment_snapshot import (
    compute_environment_digest,
    environment_digest_for,
)
from .factory import WorkspaceServices, build_workspace_services
from .files import FileService
from .git import AttemptCheckout, GitService
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
    # R2 / T2-58：Attempt 独立副本供给 + 环境快照摘要
    "AttemptCheckout",
    "AttemptCheckoutResult",
    "compute_environment_digest",
    "environment_digest_for",
    # R3 / T2-60：远程 Task / Project 用例 + 事件游标服务
    "RemoteTaskService",
    "RemotePrincipal",
    "RemoteAccessDecision",
    "RemoteTaskSpec",
    "RemoteTaskView",
    "RemoteAttemptView",
    "RemoteProjectStatus",
    "RemoteDiffView",
    "ArtifactView",
    "TaskEvent",
    "TaskLogView",
    "RemoteEventPage",
    "RemoteTaskAuthorizer",
    "ExecutionTaskEventSource",
    # R3 / T2-61：变更审阅（受限 Diff / 显式 Apply / 显式 Push）
    "ChangeReviewService",
    "DiffView",
    "ApplyResult",
    "PushResult",
    "GitWriteCredential",
    "GitCredentialProvider",
]
