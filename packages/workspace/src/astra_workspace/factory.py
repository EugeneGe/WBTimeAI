"""workspace 组合工厂（供组合根调用；W7 / T2-38 增装配位）。

既有 ``workspaces``（``WorkspaceService``）**不变**；W7 新增 ``projects`` / ``files`` /
``environment`` / ``git`` 装配位，依赖经**注入 Protocol**（``Storage`` / ``SandboxProvider`` /
``CredentialResolver`` / ``SecretResolver`` / ``TaskDispatcher``）。

🔴 **向后兼容**：新参数**全部可选**（缺省 ``None``）——既有调用 ``build_workspace_services(
session_factory)`` **不受影响**；缺依赖的装配位为 ``None``（待组合根注入）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from .application import ProjectService, TaskDispatcher
from .environment import CredentialResolver, EnvironmentService, SecretResolver
from .files import FileService
from .git import GitService
from .project_storage import ProjectStorage
from .services import WorkspaceService

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_sandbox import SandboxProvider
    from astra_storage import Storage

__all__ = ["WorkspaceServices", "build_workspace_services"]


@dataclass
class WorkspaceServices:
    """工作区子域服务集合（组合根产物）。

    Attributes:
        workspaces: 既有工作区领域服务。
        projects: 项目 / 克隆编排用例（W7）。
        files: 工作区文件用例（W7；缺 ``Storage`` 时为 ``None``）。
        environment: 工作区环境用例（W7）。
        git: Git 用例（W7；缺 ``SandboxProvider`` 时为 ``None``）。
    """

    workspaces: WorkspaceService
    projects: ProjectService
    files: FileService | None
    environment: EnvironmentService
    git: GitService | None


def build_workspace_services(
    session_factory: sessionmaker[Session],
    *,
    storage: Storage | None = None,
    sandbox: SandboxProvider | None = None,
    credential_resolver: CredentialResolver | None = None,
    secret_provider: SecretResolver | None = None,
    task_dispatcher: TaskDispatcher | None = None,
    project_storage: ProjectStorage | None = None,
) -> WorkspaceServices:
    """依会话工厂（+ 可选注入）构建工作区子域服务集合。

    Args:
        session_factory: SQLAlchemy 会话工厂。
        storage: 注入的文件存储（Protocol；可空）。
        sandbox: 注入的 ``SandboxProvider``（可空）。
        credential_resolver: 注入的凭证解密器（可空）。
        secret_provider: 注入的机密读取器（可空）。
        task_dispatcher: 注入的克隆任务派发器（可空）。
        project_storage: 注入的受管工作区目录管理器（Attempt 独立副本；可空；T2-58 加性）。

    Returns:
        :class:`WorkspaceServices`。
    """
    git = GitService(sandbox) if sandbox is not None else None
    return WorkspaceServices(
        workspaces=WorkspaceService(session_factory),
        projects=ProjectService(
            session_factory,
            git,
            storage=project_storage,
            sandbox=sandbox,
            task_dispatcher=task_dispatcher,
        ),
        files=FileService(storage) if storage is not None else None,
        environment=EnvironmentService(
            session_factory,
            credential_resolver=credential_resolver,
            secret_provider=secret_provider,
        ),
        git=git,
    )
