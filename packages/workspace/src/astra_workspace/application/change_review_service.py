"""变更审阅用例：受限 Diff / 显式 Apply / 显式 Push（R3 / T2-61）。

本模块承载**变更审阅闭环**在服务端的用例编排（设计 §2.8.1；F-R6 / F-R7；I-P2-40）：

- **受限 Diff**：由固定 ``base_commit`` 与 Attempt ``result_commit`` 生成**受限**文件摘要
  （仅经 Sandbox ``git diff --name-status``；**不含**宿主路径）；
- **显式 Apply**（**不 Push**）：把 Attempt 结果**仅**应用到**服务器 Project 目标分支**。Apply
  前逐项校验调用者权限（``EXECUTE + git.apply``）、目标 Ref、当前 HEAD（**目标分支前进 → 409**）、
  工作树干净（**脏工作树 → 409**）与冲突（**冲突 → 409**）——**任一失败保留原 Project / Attempt**
  （冲突后 ``merge --abort`` 回滚，**不**改目标分支）；
- **显式 Push**（**独立权限**）：``EXECUTE + git.push``；**必须**配置 Project 写凭证（缺 → 422）；
  **拒绝**任意 URL / force-push / 远端删除分支 / 绕过 EgressPolicy；凭证**仅服务端短时读取**、
  **仅**在**独立 Push Sandbox** 会话内使用（**不**进 Agent Sandbox / 客户端 / 日志 / 响应）。

🔴 **授权（A-14）**：Apply / Push 为**变更**操作 → 缺 capability **一律 403**（不静默）；跨租户 /
   越界 → **404**（统一隔离，不泄漏存在性）；**不新增** action 枚举、**不新增** DB 枚举迁移。

🔴 **前向硬约束（承 T2-60 OBS 前向声明，升格为硬约束）**：Apply / Push **若**接受 ``checkout_ref``
   输入，**必须**先经 ``astra_workspace.paths.ManagedWorkspacePaths.path_for_checkout_ref`` 做
   **canonical containment** 还原为受管目录；**禁止**从 API 直接接受宿主路径。本模块**只**从
   Attempt 记录读取不透明 ``checkout_ref`` 并经 ``ProjectStorage.resolve_checkout_ref`` 还原。

🔴 **分层（R-R1R5-15 · 仅收紧零放宽）**：本模块位于 ``astra_workspace/application/``——**零** Web
   （禁 ``fastapi`` / ``starlette``）、**零** ``astra_runtime``、**零** ORM（仓储经**注入 Protocol**
   使用；不 import ``sqlalchemy`` / ``astra_database``）。Git **仅经 Sandbox**
   （经 ``GitService``）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode
from astra_domain import AUDIT_OUTCOME_DENIED, AUDIT_OUTCOME_SUCCESS

from ..git import parse_name_status
from .remote_task_service import (
    CAPABILITY_GIT_APPLY,
    CAPABILITY_GIT_DIFF,
    CAPABILITY_GIT_PUSH,
    TASK_RESOURCE_TYPE,
    DiffFile,
    RemoteAccessDecision,
    RemoteAuditSink,
    RemotePrincipal,
    RemoteTaskAuthorizer,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_domain.repositories import TaskExecutionRepository, TaskRepository
    from astra_sandbox import SandboxProvider, SandboxSession

    from astra_workspace.domain import ProjectRepository

    from ..git import GitService
    from ..project_storage import ProjectStorage

__all__ = [
    # 常量
    "TASK_ACTION_APPLY",
    "TASK_ACTION_PUSH",
    "DEFAULT_REMOTE_NAME",
    "DEFAULT_DIFF_TRUNCATE_LIMIT",
    "GIT_CREDENTIAL_ENV_USERNAME",
    "GIT_CREDENTIAL_ENV_PASSWORD",
    # 值对象 / DTO
    "DiffView",
    "ApplyResult",
    "PushResult",
    "GitWriteCredential",
    # Protocol
    "GitCredentialProvider",
    # 实现
    "ChangeReviewService",
]

#: Apply 审计动作字面值（A-14「限定作用范围 + 审计」）。
TASK_ACTION_APPLY = "task.remote.apply"

#: Push 审计动作字面值（A-14；**独立**于 Apply）。
TASK_ACTION_PUSH = "task.remote.push"

#: 默认远端名（**仅**接受该名或与 Project ``repo_url`` 完全一致者；禁任意 URL）。
DEFAULT_REMOTE_NAME = "origin"

#: Diff 文件数上限（超出 → ``truncated=True``，防止超大变更集压垮响应）。
DEFAULT_DIFF_TRUNCATE_LIMIT = 500

#: 推送凭证注入沙箱的环境变量键（**仅**在独立 Push Sandbox 会话内设置）。
GIT_CREDENTIAL_ENV_USERNAME = "ASTRA_GIT_USERNAME"
GIT_CREDENTIAL_ENV_PASSWORD = "ASTRA_GIT_PASSWORD"


# -- 值对象 ------------------------------------------------------------------


@dataclass(frozen=True)
class GitWriteCredential:
    """Project **写凭证**（短时；``token`` 在 ``repr`` 中隐藏，**不**落日志 / 响应）。

    Attributes:
        username: 用户名（可空；如 ``x-access-token``）。
        token: 令牌 / 密码（**Secret**；``repr`` 隐藏）。
    """

    username: str = ""
    token: str = field(default="", repr=False)

    def as_env(self) -> dict[str, str]:
        """构造**仅**用于 Push Sandbox 命令的环境变量映射。"""
        env: dict[str, str] = {}
        if self.username:
            env[GIT_CREDENTIAL_ENV_USERNAME] = self.username
        if self.token:
            env[GIT_CREDENTIAL_ENV_PASSWORD] = self.token
        return env


@dataclass(frozen=True)
class DiffView:
    """某 Attempt 的**受限** Diff 视图（**不含**宿主路径）。

    Attributes:
        task_id: 任务标识。
        attempt: 尝试序号。
        checkout_ref: 不透明 checkout 句柄（不含宿主路径）。
        base_commit: 起始提交（Git OID；可空）。
        result_commit: 结果提交（Git OID；可空）。
        available: 是否具备可比对结果（``base_commit`` / ``result_commit`` 齐备且 diff 成功）。
        files: 变更文件摘要（元数据级）。
        truncated: 是否因超出上限被截断。
    """

    task_id: str
    attempt: int
    checkout_ref: str | None = None
    base_commit: str | None = None
    result_commit: str | None = None
    available: bool = False
    files: tuple[DiffFile, ...] = ()
    truncated: bool = False
    created_at: datetime | None = None


@dataclass(frozen=True)
class ApplyResult:
    """Apply 结果（**只**更新服务器 Project 目标分支；**不** Push）。

    Attributes:
        task_id: 任务标识。
        target_ref: 目标分支。
        base_commit: Attempt 起始提交。
        result_commit: Attempt 结果提交（被**应用**的提交）。
        applied_commit: 应用后目标分支的提交（可空）。
        already_applied: 目标分支**已**包含结果提交（幂等：无需再次应用）。
    """

    task_id: str
    target_ref: str
    base_commit: str | None = None
    result_commit: str | None = None
    applied_commit: str | None = None
    already_applied: bool = False


@dataclass(frozen=True)
class PushResult:
    """Push 结果（**独立**请求与权限；**不含**任何凭证）。

    Attributes:
        task_id: 任务标识。
        target_ref: 目标分支。
        remote: 远端名（**仅** ``origin`` 或 Project ``repo_url``）。
        ref: 推送的引用（``refs/heads/<branch>``）。
        pushed: 是否成功推送。
        already_up_to_date: 远端**已**是最新（幂等 / 无变更）。
    """

    task_id: str
    target_ref: str
    remote: str = DEFAULT_REMOTE_NAME
    ref: str = ""
    pushed: bool = False
    already_up_to_date: bool = False


# -- 注入 Protocol（组合根实现；能力包不耦合具体基础设施） -------------------


@runtime_checkable
class GitCredentialProvider(Protocol):
    """Project **写凭证**提供者（A-14 / L-11；组合根适配凭证服务，**短时**读取）。"""

    def write_credentials(self, *, tenant_id: str, project_id: str) -> GitWriteCredential | None:
        """返回 Project 的**写凭证**（**短时**；未配置 → ``None``）。"""
        ...


# -- 实现 --------------------------------------------------------------------


class ChangeReviewService:
    """变更审阅用例编排（受限 Diff / 显式 Apply / 显式 Push；R3 / T2-61）。

    🔴 依赖全部经**注入**；Git **仅经 Sandbox**（经注入 ``GitService``）；
       **零** ORM / Web / Runtime。
    """

    def __init__(
        self,
        *,
        tasks: TaskRepository,
        executions: TaskExecutionRepository,
        projects: ProjectRepository,
        git: GitService | None = None,
        sandbox: SandboxProvider | None = None,
        storage: ProjectStorage | None = None,
        authorizer: RemoteTaskAuthorizer | None = None,
        audit: RemoteAuditSink | None = None,
        credentials: GitCredentialProvider | None = None,
        diff_truncate_limit: int = DEFAULT_DIFF_TRUNCATE_LIMIT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """构造（依赖全部经**注入**；能力包零 ORM / 零 Web / 零 Runtime）。

        Args:
            tasks: 任务仓储（注入 Protocol）。
            executions: 执行记录仓储（注入 Protocol）。
            projects: 项目仓储（注入 Protocol）。
            git: Git 用例（**仅经 Sandbox**；缺省 → Apply / Push / Diff 返回结构化 503）。
            sandbox: 注入的 ``SandboxProvider``（缺省 → 结构化 503）。
            storage: 受管工作区目录管理器（``checkout_ref`` → 受管目录 containment 还原）。
            authorizer: 远程访问授权（A-14）；缺省 → **拒绝一切**（deny-by-default）。
            audit: 审计出口；缺省 → 不记审计。
            credentials: Project 写凭证提供者（Push 必需；缺省 → Push 拒绝）。
            diff_truncate_limit: Diff 文件数上限（超出截断）。
            clock: 时钟（可空；保留位，供扩展）。
        """
        self._tasks = tasks
        self._executions = executions
        self._projects = projects
        self._git = git
        self._sandbox = sandbox
        self._storage = storage
        self._authorizer = authorizer
        self._audit = audit
        self._credentials = credentials
        self._diff_truncate_limit = int(diff_truncate_limit)
        self._clock = clock

    # -- 公共属性（供组合根 / 测试检视） -----------------------------------

    @property
    def git(self) -> GitService | None:
        """返回注入的 Git 用例（可空）。"""
        return self._git

    @property
    def storage(self) -> ProjectStorage | None:
        """返回注入的受管目录管理器（可空）。"""
        return self._storage

    # -- 受限 Diff -----------------------------------------------------------

    def diff(
        self, principal: RemotePrincipal, task_id: str, *, attempt: int | None = None
    ) -> DiffView:
        """由固定 ``base_commit`` 与 Attempt ``result_commit`` 生成**受限** Diff。

        Raises:
            DomainError: 跨租户 / 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）、
                Attempt 不存在（``NOT_FOUND``）、未装配 Git / Sandbox / 存储
                （``DEPENDENCY_MISSING``）。
        """
        self._require_task(
            principal, task_id, capability=CAPABILITY_GIT_DIFF, action="task.remote.diff"
        )
        record = self._select_latest_attempt(task_id, attempt)
        base_commit = getattr(record, "base_commit", None)
        result_commit = getattr(record, "result_commit", None)
        checkout_ref = getattr(record, "checkout_ref", None)
        view = DiffView(
            task_id=str(task_id),
            attempt=int(getattr(record, "attempt", attempt or 1)),
            checkout_ref=checkout_ref,
            base_commit=base_commit,
            result_commit=result_commit,
            available=bool(base_commit and result_commit),
            created_at=getattr(record, "finished_at", None),
        )
        if not view.available:
            return view
        git, sandbox = self._require_git()
        attempt_dir = self._resolve_attempt_dir(record)
        session = self._open_session(principal, task_id)

        def _run() -> list[tuple[str, str]]:
            result = git.diff_name_status(
                session, str(base_commit), str(result_commit), cwd=str(attempt_dir)
            )
            if not result.ok:
                return []
            return parse_name_status(result.stdout)

        try:
            changes = _run()
        finally:
            sandbox.destroy(session)
        truncated = len(changes) > self._diff_truncate_limit
        files = tuple(DiffFile(path=path, change_type=kind) for kind, path in changes)
        return DiffView(
            task_id=view.task_id,
            attempt=view.attempt,
            checkout_ref=view.checkout_ref,
            base_commit=base_commit,
            result_commit=result_commit,
            available=True,
            files=files[: self._diff_truncate_limit],
            truncated=truncated,
            created_at=view.created_at,
        )

    # -- 显式 Apply（不 Push） ----------------------------------------------

    def apply(
        self,
        principal: RemotePrincipal,
        task_id: str,
        *,
        target_ref: str | None = None,
    ) -> ApplyResult:
        """把 Attempt 结果**仅**应用到**服务器 Project 目标分支**（**不** Push）。

        校验（任一失败 **保留原 Project / Attempt**）：

        1. 逐次授权（``EXECUTE + git.apply``；缺 → 403）；
        2. 目标分支当前 HEAD **必须**等于 Attempt ``base_commit``（**前进 → 409**）；
        3. Attempt 工作树**必须**干净（**脏 → 409**）；
        4. 合并**不得**冲突（**冲突 → 409**，``merge --abort`` 回滚）。

        Raises:
            DomainError: 跨租户 / 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）、
                缺 ``base_commit`` / ``result_commit``（``VALIDATION_ERROR``）、目标前进 /
                脏工作树 / 冲突（``CONFLICT`` → 409）、未装配 Git / Sandbox / 存储
                （``DEPENDENCY_MISSING``）。
        """
        task = self._require_task(
            principal,
            task_id,
            capability=CAPABILITY_GIT_APPLY,
            action=TASK_ACTION_APPLY,
            mutation=True,
        )
        project = self._require_project(principal, task)
        target = self._resolve_target_ref(target_ref, project)
        record = self._require_attempt(task_id, None)
        base_commit = getattr(record, "base_commit", None)
        result_commit = getattr(record, "result_commit", None)
        if not base_commit or not result_commit:
            raise DomainError(
                "Attempt 缺少 base_commit / result_commit，无法 Apply",
                code=ErrorCode.VALIDATION_ERROR,
                data={"task_id": task_id, "attempt": int(getattr(record, "attempt", 0))},
            )
        git, sandbox = self._require_git()
        repo_dir = self._project_repo_dir(project)
        attempt_dir = self._resolve_attempt_dir(record)
        session = self._open_session(principal, task_id)
        try:
            outcome = self._verify_base_and_clean(
                session=session,
                repo_dir=str(repo_dir),
                attempt_dir=str(attempt_dir),
                target_ref=target,
                base_commit=str(base_commit),
            )
            applied_commit: str | None = None
            already_applied = False
            if outcome.get("target_head") == str(result_commit):
                # 幂等：目标分支已含结果提交 → 无需再次应用。
                already_applied = True
                applied_commit = str(result_commit)
            else:
                git.fetch_from(session, str(attempt_dir), str(result_commit), cwd=str(repo_dir))
                merged = git.merge(
                    session,
                    str(result_commit),
                    message=f"astra apply {task_id} attempt {int(getattr(record, 'attempt', 0))}",
                    cwd=str(repo_dir),
                )
                if not merged.ok:
                    git.merge_abort(session, cwd=str(repo_dir))
                    raise DomainError(
                        "应用发生冲突（保留原 Project / Attempt）",
                        code=ErrorCode.CONFLICT,
                        status_code=409,
                        data={"task_id": task_id, "target_ref": target},
                    )
                applied_commit = git.resolve_commit(session, target, cwd=str(repo_dir)) or str(
                    result_commit
                )
        finally:
            sandbox.destroy(session)
        self._record(
            principal,
            action=TASK_ACTION_APPLY,
            resource_id=str(task_id),
            outcome=AUDIT_OUTCOME_SUCCESS,
            metadata={
                "target_ref": target,
                "attempt": int(getattr(record, "attempt", 0)),
                "base_commit": str(base_commit),
                "result_commit": str(result_commit),
                "already_applied": already_applied,
            },
        )
        return ApplyResult(
            task_id=str(task_id),
            target_ref=target,
            base_commit=str(base_commit),
            result_commit=str(result_commit),
            applied_commit=applied_commit,
            already_applied=already_applied,
        )

    # -- 显式 Push（独立权限） ---------------------------------------------

    def push(
        self,
        principal: RemotePrincipal,
        task_id: str,
        *,
        target_ref: str | None = None,
        remote: str = DEFAULT_REMOTE_NAME,
    ) -> PushResult:
        """把**服务器 Project 目标分支**推送到远端（**独立**请求与权限；A-14）。

        - 逐次授权（``EXECUTE + git.push``；缺 → 403）；
        - 远端**仅**接受 ``origin`` 或与 Project ``repo_url`` **完全一致**者（**禁**任意 URL）；
        - **必须**配置 Project 写凭证（缺 → 422）；
        - **禁** force-push / 远端删除分支（refspec 恒为 ``refs/heads/<b>:refs/heads/<b>``）；
        - 凭证**仅服务端短时读取**、**仅**在**独立 Push Sandbox** 会话内使用。

        Raises:
            DomainError: 跨租户 / 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）、
                任意 URL / 强推 / 删分支（``PERMISSION_DENIED``）、未配置写凭证
                （``CONFIGURATION_ERROR`` → 422）、推送被拒（``CONFLICT`` → 409）、
                未装配 Git / Sandbox / 存储（``DEPENDENCY_MISSING``）。
        """
        task = self._require_task(
            principal,
            task_id,
            capability=CAPABILITY_GIT_PUSH,
            action=TASK_ACTION_PUSH,
            mutation=True,
        )
        project = self._require_project(principal, task)
        target = self._resolve_target_ref(target_ref, project)
        remote_name = self._validate_remote(remote, project)
        # 先做**纯逻辑**安全校验（任意 URL / 强推 / 删分支）——失败即拒（**不**触碰凭证）。
        self._validate_push_target(remote_name, target)
        git, sandbox = self._require_git()
        credential = self._require_write_credential(principal, project)
        repo_dir = self._project_repo_dir(project)
        session = self._open_session(principal, task_id)
        refspec = f"refs/heads/{target}:refs/heads/{target}"
        try:
            pushed = git.push_ref(
                session,
                remote=DEFAULT_REMOTE_NAME,
                refspec=refspec,
                cwd=str(repo_dir),
                env=credential.as_env(),
            )
        finally:
            sandbox.destroy(session)
        result = PushResult(
            task_id=str(task_id),
            target_ref=target,
            remote=remote_name,
            ref=f"refs/heads/{target}",
            pushed=bool(pushed.ok),
            already_up_to_date=bool(pushed.ok and "up-to-date" in (pushed.stdout or "").lower()),
        )
        if not pushed.ok:
            self._record(
                principal,
                action=TASK_ACTION_PUSH,
                resource_id=str(task_id),
                outcome=AUDIT_OUTCOME_DENIED,
                metadata={"target_ref": target, "remote": remote_name, "reason": "push_rejected"},
            )
            raise DomainError(
                "推送被拒绝（保留原状）",
                code=ErrorCode.CONFLICT,
                status_code=409,
                data={"task_id": task_id, "target_ref": target, "remote": remote_name},
            )
        self._record(
            principal,
            action=TASK_ACTION_PUSH,
            resource_id=str(task_id),
            outcome=AUDIT_OUTCOME_SUCCESS,
            metadata={"target_ref": target, "remote": remote_name, "ref": result.ref},
        )
        return result

    # -- 内部：基线 / 干净校验（Apply 核心） --------------------------------

    def _verify_base_and_clean(
        self,
        *,
        session: SandboxSession,
        repo_dir: str,
        attempt_dir: str,
        target_ref: str,
        base_commit: str,
    ) -> dict[str, Any]:
        """校验目标分支基线 + Attempt 工作树干净（**只读**；失败不产生副作用）。

        Raises:
            DomainError: 目标分支不存在（``VALIDATION_ERROR``）、目标前进（``CONFLICT``）、
                脏工作树（``CONFLICT``）。
        """
        assert self._git is not None  # 由 _require_git 保证
        git = self._git
        target_head = git.resolve_commit(session, target_ref, cwd=repo_dir)
        if target_head is None:
            raise DomainError(
                "目标分支不存在",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "target_ref", "target_ref": target_ref},
            )
        if target_head != base_commit:
            # 目标分支已前进（HEAD ≠ Attempt 基线）→ 409，**保留原 Project / Attempt**。
            raise DomainError(
                "目标分支已前进（基线不一致，保留原 Project / Attempt）",
                code=ErrorCode.CONFLICT,
                status_code=409,
                data={"target_ref": target_ref, "expected": base_commit, "actual": target_head},
            )
        status = git.status(session, cwd=attempt_dir)
        if (status.stdout or "").strip():
            raise DomainError(
                "Attempt 工作树不干净（存在未提交改动，保留原 Project / Attempt）",
                code=ErrorCode.CONFLICT,
                status_code=409,
                data={"task_id": "", "dirty": True},
            )
        return {"target_head": target_head}

    # -- 内部：授权 / 解析 ---------------------------------------------------

    def _require_task(
        self,
        principal: RemotePrincipal,
        task_id: str,
        *,
        capability: str,
        action: str,
        mutation: bool = False,
    ) -> Any:
        """取任务（不存在 / 跨租户 / 非远程 → 404）+ 逐次授权。

        读取类（``mutation=False``）：跨范围 → 404 隔离（I-1）；变更类（``mutation=True``）：
        缺 capability 一律 403（见 :meth:`_authorize`）。
        """
        task = self._tasks.get(task_id)
        if task is None or str(getattr(task, "tenant_id", "") or "") != principal.tenant_id:
            raise self._not_found("task", task_id)
        project_id = self._task_project_id(task)
        if not project_id:
            raise self._not_found("task", task_id)
        self._authorize(
            principal,
            capability=capability,
            resource_id=project_id,
            action=action,
            mutation=mutation,
        )
        return task

    def _require_project(self, principal: RemotePrincipal, task: Any) -> Any:
        """取任务归属 Project（不存在 / 跨租户 → 404）。"""
        project_id = self._task_project_id(task) or ""
        project = self._projects.get(project_id) if project_id else None
        if project is None or str(getattr(project, "tenant_id", "") or "") != principal.tenant_id:
            raise self._not_found("project", project_id)
        return project

    def _require_attempt(self, task_id: str, attempt: int | None) -> Any:
        """取指定（缺省取**最近完成**）Attempt；不存在 → 404。"""
        records = self._sorted_executions(task_id)
        if attempt is None:
            usable = [rec for rec in records if getattr(rec, "result_commit", None)]
            if not usable:
                raise self._not_found("attempt", task_id)
            return usable[-1]
        match = next(
            (rec for rec in records if int(getattr(rec, "attempt", 0)) == int(attempt)), None
        )
        if match is None:
            raise self._not_found("attempt", f"{task_id}:{attempt}")
        return match

    def _select_latest_attempt(self, task_id: str, attempt: int | None) -> Any:
        """取指定（缺省取**最近**）Attempt —— **含**缺 ``result_commit`` 的在跑 Attempt。

        R5 补全轮（F4 / R5A-02）：Diff 读取需在结果提交**尚缺**时**降级**（``available=False`` →
        200），故 ``attempt is None`` 时取**最近一条**（**不**要求 ``result_commit``）；仅**无任何
        Attempt** 才 404。与 :meth:`_require_attempt`（Apply 用，要求**可比对**）区分，
        **不**改其语义。

        Raises:
            DomainError: 无任何 Attempt（``NOT_FOUND``）。
        """
        records = self._sorted_executions(task_id)
        if not records:
            raise self._not_found("attempt", f"{task_id}:{attempt or 1}")
        if attempt is None:
            return records[-1]
        match = next(
            (rec for rec in records if int(getattr(rec, "attempt", 0)) == int(attempt)), None
        )
        if match is None:
            raise self._not_found("attempt", f"{task_id}:{attempt}")
        return match

    def _require_git(self) -> tuple[GitService, SandboxProvider]:
        """取 Git 用例 + Sandbox（缺装配 → 结构化 503，不静默）。

        Raises:
            DomainError: 缺 ``GitService`` / ``SandboxProvider`` / ``ProjectStorage``
                （``DEPENDENCY_MISSING`` → 503）。
        """
        if self._git is None or self._sandbox is None or self._storage is None:
            raise DomainError(
                "变更审阅能力未装配（缺 GitService / SandboxProvider / ProjectStorage）",
                code=ErrorCode.DEPENDENCY_MISSING,
                status_code=503,
                data={"capability": "change_review"},
            )
        return self._git, self._sandbox

    def _require_write_credential(
        self, principal: RemotePrincipal, project: Any
    ) -> GitWriteCredential:
        """取 Project **写凭证**（缺提供者 / 未配置 → 422，**不**静默）。

        Raises:
            DomainError: 未装配凭证提供者或 Project 未配置写凭证（``CONFIGURATION_ERROR`` → 422）。
        """
        project_id = str(getattr(project, "id", "") or "")
        credential = (
            self._credentials.write_credentials(
                tenant_id=principal.tenant_id, project_id=project_id
            )
            if self._credentials is not None
            else None
        )
        if credential is None or not credential.token:
            raise DomainError(
                "Project 未配置写凭证，无法 Push",
                code=ErrorCode.CONFIGURATION_ERROR,
                status_code=422,
                data={"project_id": project_id},
            )
        return credential

    def _validate_remote(self, remote: str, project: Any) -> str:
        """校验远端名：**仅**接受 ``origin``（**禁**任意 URL；防推送目标被劫持）。

        Raises:
            DomainError: 任意 URL / 非 ``origin`` 的远端（``PERMISSION_DENIED`` → 403）。
        """
        name = (remote or "").strip() or DEFAULT_REMOTE_NAME
        if name != DEFAULT_REMOTE_NAME:
            raise DomainError(
                "禁止推送至任意 URL（仅允许 origin）",
                code=ErrorCode.PERMISSION_DENIED,
                data={"field": "remote", "remote": name},
            )
        if not str(getattr(project, "repo_url", "") or "").strip():
            raise DomainError(
                "Project 未配置仓库地址，无法 Push",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "repo_url"},
            )
        return name

    @staticmethod
    def _validate_push_target(remote: str, target_ref: str) -> None:
        """纯逻辑安全校验：**禁** force-push / 远端删除分支 / 任意 URL。

        Raises:
            DomainError: 命中禁用形态（``PERMISSION_DENIED`` / ``VALIDATION_ERROR``）。
        """
        text = (target_ref or "").strip()
        lowered = text.lower()
        if not text:
            raise DomainError(
                "目标引用不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "target_ref"},
            )
        if text.startswith(":") or text.startswith("+"):
            raise DomainError(
                "禁止删除远端分支 / 强推（引用不得以 ':' 或 '+' 开头）",
                code=ErrorCode.PERMISSION_DENIED,
                data={"field": "target_ref"},
            )
        if ".." in text:
            raise DomainError(
                "非法目标引用（含 '..'）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "target_ref"},
            )
        if "--force" in lowered or lowered in {"-f", "force", "force-push"}:
            raise DomainError(
                "禁止强推（force push）",
                code=ErrorCode.PERMISSION_DENIED,
                data={"field": "target_ref"},
            )
        if "://" in text or "@" in text:
            raise DomainError(
                "目标引用不得为 URL",
                code=ErrorCode.PERMISSION_DENIED,
                data={"field": "target_ref"},
            )
        if "://" in (remote or "") or "@" in (remote or ""):
            raise DomainError(
                "禁止推送至任意 URL",
                code=ErrorCode.PERMISSION_DENIED,
                data={"field": "remote"},
            )

    @staticmethod
    def _resolve_target_ref(target_ref: str | None, project: Any) -> str:
        """解析目标分支（缺省取 Project ``default_branch``，再缺省 ``main``）。"""
        if target_ref and target_ref.strip():
            return target_ref.strip()
        default = str(getattr(project, "default_branch", "") or "").strip()
        return default or "main"

    def _project_repo_dir(self, project: Any) -> Any:
        """取服务器 Project 受管基础仓库目录（canonical containment；未装配 → 503）。"""
        if self._storage is None:
            raise DomainError(
                "变更审阅能力未装配（缺 ProjectStorage）",
                code=ErrorCode.DEPENDENCY_MISSING,
                status_code=503,
                data={"capability": "change_review"},
            )
        return self._storage.project_repo_dir(str(getattr(project, "id", "") or ""))

    def _resolve_attempt_dir(self, record: Any) -> Any:
        """由不透明 ``checkout_ref`` **经 canonical containment** 还原 Attempt 受管目录。

        🔴 前向硬约束：``checkout_ref`` **必须**经 ``ProjectStorage.resolve_checkout_ref``
           （即 ``ManagedWorkspacePaths.path_for_checkout_ref``）还原；**禁止**直接宿主路径。

        Raises:
            DomainError: 缺 ``ProjectStorage``（``DEPENDENCY_MISSING``）、``checkout_ref`` 缺失 /
                非法（``VALIDATION_ERROR``）。
        """
        if self._storage is None:
            raise DomainError(
                "变更审阅能力未装配（缺 ProjectStorage）",
                code=ErrorCode.DEPENDENCY_MISSING,
                status_code=503,
                data={"capability": "change_review"},
            )
        ref = getattr(record, "checkout_ref", None)
        if not ref:
            raise DomainError(
                "Attempt 缺少 checkout_ref，无法定位工作副本",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "checkout_ref"},
            )
        return self._storage.resolve_checkout_ref(str(ref))

    def _open_session(self, principal: RemotePrincipal, task_id: str) -> SandboxSession:
        """为**一次**变更审阅操作开启**独立** Sandbox 会话（Git **仅经 Sandbox**）。"""
        assert self._sandbox is not None  # 由 _require_git 保证
        return self._sandbox.create_session(tenant_id=principal.tenant_id)

    def _sorted_executions(self, task_id: str) -> list[Any]:
        """按 ``attempt`` 升序返回执行记录。"""
        records = self._executions.list_by_task(task_id)
        return sorted(records, key=lambda rec: int(getattr(rec, "attempt", 0)))

    # -- 内部：authorization / 审计 -----------------------------------------

    def _authorize(
        self,
        principal: RemotePrincipal,
        *,
        capability: str,
        resource_id: str | None,
        action: str,
        mutation: bool = False,
    ) -> None:
        """逐次校验（A-14）。策略（对齐 ``RemoteTaskService._authorize``）：

        - **变更**操作（``mutation=True``：Apply / Push）→ 缺 capability **一律 403**
          （不静默 / 不降级为 404）；
        - **单资源读取**（如 ``git.diff``；``mutation=False``）：``in_scope`` 为真 → **403**；
          否则 → **404**（统一隔离 I-1，不泄漏存在性）；
        - 授权通过 → 放行；失败另记**拒绝审计**（``outcome=DENIED``）。

        🔴 R5 补全轮（F4 补正）：``GET /tasks/{id}/diff`` 为**读取**出口（改道 ``diff`` 后仍须
           维持 I-1 隔离语义）——此前 ``_authorize`` 无条件 403，读取类跨范围会误报 403。
        """
        decision = self._decide(principal, capability=capability, resource_id=resource_id)
        if decision.allowed:
            return
        self._record(
            principal,
            action=action,
            resource_id=resource_id,
            outcome=AUDIT_OUTCOME_DENIED,
            metadata={"capability": capability, "reason": decision.reason},
        )
        if mutation or decision.in_scope:
            raise DomainError(
                "缺少变更审阅权限",
                code=ErrorCode.PERMISSION_DENIED,
                status_code=403,
                data={"capability": capability},
            )
        raise self._not_found("resource", resource_id or "")

    def _decide(
        self, principal: RemotePrincipal, *, capability: str, resource_id: str | None
    ) -> RemoteAccessDecision:
        """调用注入授权器；未装配授权器 → **拒绝一切**（deny-by-default）。"""
        if self._authorizer is None:
            return RemoteAccessDecision(allowed=False, in_scope=False, reason="no_authorizer")
        return self._authorizer.authorize(
            principal,
            capability=capability,
            resource_type=TASK_RESOURCE_TYPE,
            resource_id=resource_id,
        )

    def _record(
        self,
        principal: RemotePrincipal,
        *,
        action: str,
        resource_id: str | None,
        outcome: str,
        metadata: dict[str, Any],
    ) -> None:
        """写审计（缺审计出口 → 静默跳过；**不因审计失败中断业务**；**不含**凭证）。"""
        if self._audit is None:
            return
        try:
            self._audit.record(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                action=action,
                resource_type=TASK_RESOURCE_TYPE,
                resource_id=resource_id,
                outcome=outcome,
                metadata=dict(metadata),
            )
        except Exception:  # noqa: BLE001 - 审计失败不得阻断业务（对齐 AuditService 语义）
            pass

    @staticmethod
    def _task_project_id(task: Any) -> str | None:
        """取任务归属 Project（来自 ``task.payload['project_id']``）。"""
        payload = dict(getattr(task, "payload", None) or {})
        value = payload.get("project_id")
        return str(value) if value else None

    @staticmethod
    def _not_found(kind: str, identifier: str) -> DomainError:
        """统一隔离 404（不泄漏存在性）。"""
        return DomainError(
            "资源不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
            data={"kind": kind, "id": identifier},
        )
