"""Project / Clone 编排用例（W7 / T2-38；R2 / T2-58 增 Attempt 供给）。

- **项目** CRUD：经 :class:`~astra_workspace.repositories.SqlProjectRepository`（注入的
  领域 ``ProjectRepository``）；
- **克隆编排**（``clone``）：加载项目（租户校验）→ 若注入了任务派发器则派发 ``project.clone``
  任务（返回 ``task_id``，异步路径）；否则**同步**经 :class:`~astra_workspace.git.GitService`
  在沙箱内克隆（Git **仅经 Sandbox**）；
- **Attempt 供给**（``prepare_attempt``，T2-58）：为每次 Execution Attempt 创建**独立**工作
  副本（``ProjectStorage``）并在**短时 Git Provision Sandbox** 内克隆（各 Attempt 独立
  ``.git`` / refs / index），记录不透明 ``checkout_ref`` 与 ``base_commit``。**返回结果不含
  宿主绝对路径**。

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
from ..project_storage import ProjectStorage
from ..repositories import SqlProjectRepository

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_sandbox import ExecResult, SandboxProvider, SandboxSession

__all__ = ["ProjectService", "CloneResult", "AttemptCheckoutResult", "TaskDispatcher"]


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


@dataclass
class AttemptCheckoutResult:
    """Attempt 独立工作副本的供给结果（T2-58；**不含宿主绝对路径**）。

    Attributes:
        project_id: 项目标识。
        execution_id: 执行标识（``task_execution.id``）。
        attempt: 尝试序号（从 1 起）。
        checkout_ref: 不透明 checkout 句柄（可服务端还原，**不含宿主路径**）。
        base_commit: Attempt 起始提交（Git OID；可空）。
    """

    project_id: str
    execution_id: str
    attempt: int
    checkout_ref: str
    base_commit: str | None = None


class ProjectService:
    """项目 / 克隆编排用例。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        git: GitService | None = None,
        *,
        storage: ProjectStorage | None = None,
        sandbox: SandboxProvider | None = None,
        task_dispatcher: TaskDispatcher | None = None,
    ) -> None:
        """构造。

        Args:
            session_factory: SQLAlchemy 会话工厂。
            git: Git 用例（仅经 Sandbox；同步克隆 / Attempt 供给路径需要，可空）。
            storage: 受管目录生命周期（Attempt 独立副本；可空）。
            sandbox: 注入的 ``SandboxProvider``（同步克隆 / Attempt 供给路径需要）。
            task_dispatcher: 注入的任务派发器（异步克隆路径；可空）。
        """
        self._session_factory = session_factory
        self._git = git
        self._storage = storage
        self._sandbox = sandbox
        self._task_dispatcher = task_dispatcher

    @property
    def storage(self) -> ProjectStorage | None:
        """返回注入的受管目录管理器（供组合根 / 测试检视）。"""
        return self._storage

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

    # -- Attempt 独立副本供给（T2-58） --------------------------------------

    def prepare_attempt(
        self,
        *,
        tenant_id: str,
        project_id: str,
        execution_id: str,
        attempt: int,
        base_ref: str | None = None,
    ) -> AttemptCheckoutResult:
        """为一次 Attempt 准备**独立**工作副本并供给 Git checkout（T2-58）。

        步骤：

        1. 加载项目（**租户校验**）并取 ``repo_url``；
        2. 经 ``ProjectStorage`` **新建**独立 Attempt 目录（**已存在即拒绝**，防复用）并生成
           不透明 ``checkout_ref``；
        3. 在**短时 Git Provision Sandbox** 内 ``git clone``（各 Attempt 独立 ``.git`` / refs /
           index）并解析 ``base_commit``；克隆**仅经 Sandbox**。

        Raises:
            DomainError: 项目不存在 / 跨租户（``NOT_FOUND``）、无仓库地址（``VALIDATION_ERROR``）、
                未注入 ``ProjectStorage`` / ``GitService`` / ``SandboxProvider``
                （``CONFIGURATION_ERROR``）、Attempt 目录已存在（``CONFLICT``）、克隆失败
                （``INTERNAL_ERROR``）。
        """
        project = self.get(project_id, tenant_id=tenant_id)
        repo_url = (project.repo_url or "").strip()
        if not repo_url:
            raise DomainError(
                "项目未配置仓库地址，无法供给 Attempt 副本",
                code=ErrorCode.VALIDATION_ERROR,
                data={"project_id": project_id, "field": "repo_url"},
            )
        if self._storage is None or self._git is None or self._sandbox is None:
            raise DomainError(
                "供给 Attempt 副本需要注入 ProjectStorage / GitService / SandboxProvider",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"project_id": project_id},
            )

        # ① 独立 Attempt 目录（已存在 → CONFLICT；唯一、不复用）+ 不透明 checkout_ref。
        self._storage.create_attempt_dir(execution_id, attempt)
        checkout_ref = self._storage.checkout_ref(execution_id, attempt)

        # ② 短时 Git Provision Sandbox 内克隆（独立 .git / refs / index；仅经 Sandbox）。
        session = self._sandbox.create_session(
            workspace_id=project.workspace_id, tenant_id=tenant_id
        )
        try:
            checkout = self._git.provision_attempt_checkout(
                session, repo_url=repo_url, base_ref=base_ref
            )
        finally:
            self._sandbox.destroy(session)

        return AttemptCheckoutResult(
            project_id=project.id,
            execution_id=execution_id,
            attempt=attempt,
            checkout_ref=checkout_ref,
            base_commit=checkout.base_commit,
        )
