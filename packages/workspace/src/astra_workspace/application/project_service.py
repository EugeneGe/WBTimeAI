"""Project / Clone 编排用例（W7 / T2-38；``application/``＝跨层编排）。

- **项目** CRUD：经 :class:`~astra_workspace.repositories.SqlProjectRepository`（注入的
  领域 ``ProjectRepository``）；
- **克隆编排**（``clone``）：加载项目（租户校验）→ 若注入了任务派发器则派发 ``project.clone``
  任务（返回 ``task_id``，异步路径）；否则**同步**经 :class:`~astra_workspace.git.GitService`
  在沙箱内克隆（Git **仅经 Sandbox**）。

🔴 依赖经**注入 Protocol**：``SandboxProvider`` / ``TaskDispatcher``（``TYPE_CHECKING`` 引类型）；
   本模块**不 import** 具体基础设施（``astra_sandbox`` / ``astra_task``）运行时对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode
from astra_database import session_scope
from sqlalchemy.orm import Session, sessionmaker

from ..domain import Project
from ..git import GitService
from ..repositories import SqlProjectRepository

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_sandbox import ExecResult, SandboxProvider, SandboxSession

__all__ = ["ProjectService", "CloneResult", "TaskDispatcher"]


@runtime_checkable
class TaskDispatcher(Protocol):
    """克隆任务派发器（由组合根注入；把 ``project.clone`` 落任务队列）。

    🔴 **只定义契约**：本波（T2-38）不耦合 ``astra_task`` 具体实现；任务创建/幂等由
       T2-39（``astra_task`` + ``astra_database.repositories``）承载，经此 Protocol 注入。
    """

    def dispatch_clone(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        project_id: str,
        repo_url: str,
        base_ref: str | None = None,
    ) -> str:
        """创建并派发 ``project.clone`` 任务，返回 ``task_id``。"""
        ...


@dataclass
class CloneResult:
    """克隆编排结果。

    Attributes:
        project_id: 项目标识。
        base_ref: 请求的基准引用（可空）。
        task_id: 异步派发的任务标识（注入了 ``TaskDispatcher`` 时非空）。
        result: 同步沙箱克隆的执行结果（未注入派发器时非空）。
        sandbox_session: 同步克隆使用的沙箱会话（可空；仅供审计）。
    """

    project_id: str
    base_ref: str | None = None
    task_id: str | None = None
    result: ExecResult | None = None
    sandbox_session: SandboxSession | None = None


class ProjectService:
    """项目 / 克隆编排用例。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        git: GitService | None = None,
        *,
        sandbox: SandboxProvider | None = None,
        task_dispatcher: TaskDispatcher | None = None,
    ) -> None:
        """构造。

        Args:
            session_factory: SQLAlchemy 会话工厂。
            git: Git 用例（仅经 Sandbox；同步克隆路径需要，可空）。
            sandbox: 注入的 ``SandboxProvider``（同步克隆路径需要）。
            task_dispatcher: 注入的任务派发器（异步克隆路径；可空）。
        """
        self._session_factory = session_factory
        self._git = git
        self._sandbox = sandbox
        self._task_dispatcher = task_dispatcher

    # -- 项目 CRUD ----------------------------------------------------------

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        name: str,
        description: str | None = None,
        repo_url: str | None = None,
        default_branch: str | None = None,
        settings: dict[str, Any] | None = None,
        created_by: str | None = None,
        organization_id: str | None = None,
    ) -> Project:
        """创建项目（校验名称 / 工作区归属后持久化）。

        Raises:
            DomainError: 名称或工作区为空（``VALIDATION_ERROR``）。
        """
        project = Project(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            organization_id=organization_id,
            name=(name or "").strip(),
            description=description,
            repo_url=repo_url,
            default_branch=default_branch,
            settings=dict(settings) if settings else {},
            created_by=created_by,
        )
        project.assert_valid()
        with session_scope(self._session_factory) as session:
            return SqlProjectRepository(session).add(project)

    def get(self, project_id: str, *, tenant_id: str) -> Project:
        """按 id 获取项目（**校验租户归属**）。

        Raises:
            DomainError: 不存在或跨租户（``NOT_FOUND``）。
        """
        with session_scope(self._session_factory) as session:
            project = SqlProjectRepository(session).get(project_id)
        if project is None or project.tenant_id != tenant_id:
            raise DomainError(
                "项目不存在", code=ErrorCode.NOT_FOUND, data={"project_id": project_id}
            )
        return project

    def list_by_workspace(self, workspace_id: str, *, tenant_id: str) -> list[Project]:
        """列出某工作区下的项目（**仅返回同租户**）。"""
        with session_scope(self._session_factory) as session:
            projects = SqlProjectRepository(session).list_by_workspace(workspace_id)
        return [project for project in projects if project.tenant_id == tenant_id]

    # -- 克隆编排 -----------------------------------------------------------

    def clone(self, *, tenant_id: str, project_id: str, base_ref: str | None = None) -> CloneResult:
        """克隆项目仓库。

        路径（二选一）：

        - 注入 ``TaskDispatcher`` → **异步**：派发 ``project.clone`` 任务，返回 ``task_id``；
        - 未注入 → **同步**：在沙箱内 ``git clone``（经 ``GitService``），返回执行结果。

        Raises:
            DomainError: 项目不存在 / 跨租户（``NOT_FOUND``）、无仓库地址（``VALIDATION_ERROR``）、
                同步路径未注入 ``SandboxProvider``（``CONFIGURATION_ERROR``）。
        """
        project = self.get(project_id, tenant_id=tenant_id)
        repo_url = (project.repo_url or "").strip()
        if not repo_url:
            raise DomainError(
                "项目未配置仓库地址，无法克隆",
                code=ErrorCode.VALIDATION_ERROR,
                data={"project_id": project_id, "field": "repo_url"},
            )
        if self._task_dispatcher is not None:
            task_id = self._task_dispatcher.dispatch_clone(
                tenant_id=tenant_id,
                workspace_id=project.workspace_id,
                project_id=project.id,
                repo_url=repo_url,
                base_ref=base_ref,
            )
            return CloneResult(project_id=project.id, base_ref=base_ref, task_id=task_id)

        if self._sandbox is None or self._git is None:
            raise DomainError(
                "同步克隆需要注入 SandboxProvider 与 GitService",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"project_id": project_id},
            )
        session = self._sandbox.create_session(
            workspace_id=project.workspace_id, tenant_id=tenant_id
        )
        try:
            result = self._git.clone(session, repo_url, base_ref=base_ref)
        finally:
            self._sandbox.destroy(session)
        return CloneResult(
            project_id=project.id, base_ref=base_ref, result=result, sandbox_session=session
        )
