"""远程 Task / Project 用例、scope 校验与事件游标服务（R3 / T2-60）。

本模块承载**远程工作台**在服务端的用例编排（设计 §2.8.1 / §2.9.1；I-P2-39）：

- **远程 Project**：状态查询、显式 Clone（异步派发 ``project.clone`` 任务）、Git ref 查询；
- **远程 Task**：远程提交（``remote.agent_run``）、状态快照、取消、Attempt / Event / Log /
  Diff / Artifact 读取；
- **权限（A-14）**：创建 / 取消 / Diff / Download 一律以 ``EXECUTE`` + capability 细分校验
  （``task.submit`` / ``task.cancel`` / ``git.diff`` / ``artifact.download`` …），**不新增
  action 枚举**、**不新增 DB 枚举迁移**；新增 ``TASK`` 资源类型仅为**字符串**（A-14）；
  逐次校验、限定资源范围并记审计。
- **隔离**：跨租户 / 跨范围资源按**统一隔离规则返回 404**（不泄漏存在性）；列表 / 创建等
  集合或变更操作在**已鉴权但缺 capability** 时返回 403。
- **事件**：采用**不透明 cursor** / ``Last-Event-ID``；``seq`` 单调；过期 cursor 返回稳定
  错误码 ``EVENT_CURSOR_EXPIRED``。
- **宿主路径不出网**：API 只返回**不透明** ``checkout_ref``（可服务端还原），**不含**宿主
  绝对路径（对齐 ``astra_workspace.paths``）。

🔴 **分层（R-R1R5-15 · 仅收紧零放宽）**：本模块位于 ``astra_workspace/application/``——
   **零** Web（禁 ``fastapi`` / ``starlette``）、**零** ``astra_runtime``、**零** ORM
   （仓储经**注入 Protocol** 使用；不 import ``sqlalchemy`` / ``astra_database``）。
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode
from astra_domain import (
    AUDIT_OUTCOME_DENIED,
    AUDIT_OUTCOME_SUCCESS,
    CAPABILITY_GIT_PUSH,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_domain.repositories import (
        ProjectRepository,
        TaskExecutionRepository,
        TaskRepository,
    )

__all__ = [
    # 常量
    "TASK_RESOURCE_TYPE",
    "PROJECT_RESOURCE_TYPE",
    "ACTION_EXECUTE",
    "CAPABILITY_TASK_SUBMIT",
    "CAPABILITY_TASK_READ",
    "CAPABILITY_TASK_CANCEL",
    "CAPABILITY_GIT_DIFF",
    "CAPABILITY_GIT_APPLY",
    "CAPABILITY_GIT_PUSH",
    "CAPABILITY_ARTIFACT_DOWNLOAD",
    "CAPABILITY_PROJECT_READ",
    "CAPABILITY_PROJECT_CLONE",
    "TASK_EVENT_CURSOR_PREFIX",
    "REMOTE_TASK_TYPE",
    "PROJECT_CLONE_TASK_TYPE",
    "TASK_ACTION_SUBMIT",
    "TASK_ACTION_CANCEL",
    "TASK_ACTION_DIFF",
    "TASK_ACTION_DOWNLOAD",
    "TASK_ACTION_EVENT",
    # 值对象 / DTO
    "RemotePrincipal",
    "RemoteAccessDecision",
    "TaskEvent",
    "RemoteAttemptView",
    "RemoteTaskView",
    "TaskLogView",
    "DiffFile",
    "RemoteDiffView",
    "ArtifactView",
    "ArtifactDownload",
    "RemoteEventPage",
    "RemoteTaskSpec",
    "RemoteProjectStatus",
    "GitRefView",
    # Protocol
    "RemoteTaskAuthorizer",
    "RemoteAuditSink",
    "RemoteTaskSubmitter",
    "TaskEventSource",
    "DiffProvider",
    "ArtifactReader",
    "GitRefsProvider",
    # 实现
    "ExecutionTaskEventSource",
    "RemoteTaskService",
]

# -- A-14：资源类型 / 动作 / capability --------------------------------------

#: 新增 ``TASK`` 资源类型（**字符串列**，无枚举迁移；A-14）。
TASK_RESOURCE_TYPE = "TASK"

#: 既有 ``PROJECT`` 资源类型（Project 远程端点）。
PROJECT_RESOURCE_TYPE = "PROJECT"

#: 远程动作统一复用既有粗粒度动作 ``EXECUTE``（**不新增** action 枚举；A-14）。
ACTION_EXECUTE = "EXECUTE"

# -- capability 细分（细粒度；字符串，落 ``resource_permission.scope.capabilities``） --
CAPABILITY_TASK_SUBMIT = "task.submit"
CAPABILITY_TASK_READ = "task.read"
CAPABILITY_TASK_CANCEL = "task.cancel"
CAPABILITY_GIT_DIFF = "git.diff"
CAPABILITY_GIT_APPLY = "git.apply"
# ``git.push`` 复用领域受控词汇表（``astra_domain.CAPABILITY_GIT_PUSH``，避免拼写漂移）。
CAPABILITY_ARTIFACT_DOWNLOAD = "artifact.download"
CAPABILITY_PROJECT_READ = "project.read"
CAPABILITY_PROJECT_CLONE = "project.clone"

#: 审计 ``action`` 字面值（区分四类远程动作；A-14「限定作用范围 + 审计」）。
TASK_ACTION_SUBMIT = "task.remote.submit"
TASK_ACTION_CANCEL = "task.remote.cancel"
TASK_ACTION_DIFF = "task.remote.diff"
TASK_ACTION_DOWNLOAD = "task.remote.artifact.download"
TASK_ACTION_EVENT = "task.remote.event.read"

#: 远程任务类型（``task.type`` 为 ``String(100)`` → 免迁移；对齐 worker handler）。
REMOTE_TASK_TYPE = "remote.agent_run"

#: Project Clone 任务类型（对齐 T2-58 worker handler）。
PROJECT_CLONE_TASK_TYPE = "project.clone"

#: 不透明事件游标前缀（不含宿主路径；服务端可还原）。
TASK_EVENT_CURSOR_PREFIX = "tev_"

#: 事件保留窗口：默认保留全部 Attempt（``None`` = 不裁剪，无 cursor 过期）。
DEFAULT_EVENT_RETENTION_ATTEMPTS: int | None = None


# -- 值对象 ------------------------------------------------------------------


@dataclass(frozen=True)
class RemotePrincipal:
    """远程调用主体（HTTP 层由 ``CurrentUser`` 派生；本模块**不依赖** Web DTO）。

    Attributes:
        tenant_id: 租户标识（硬隔离，I-1）。
        user_id: 用户标识（capability / scope 判定主体）。
    """

    tenant_id: str
    user_id: str = ""


@dataclass(frozen=True)
class RemoteAccessDecision:
    """一次远程访问判定（A-14：``can()`` + scope 结果）。

    Attributes:
        allowed: capability 是否在**该资源范围**内被授予。
        in_scope: 资源是否处于调用者**可访问范围**内（否则统一 404，不泄漏存在性）。
        reason: 判定来源（``role`` / ``rbac`` / ``scoped`` / ``no_grant`` / ``denied``）。
    """

    allowed: bool
    in_scope: bool
    reason: str = ""


@dataclass(frozen=True)
class TaskEvent:
    """任务级事件（聚合通道；``seq`` 单调，可续读）。

    Attributes:
        seq: 事件序号（**单调递增**；服务端分配，跨保留窗口稳定）。
        type: 事件类型（如 ``attempt.started`` / ``attempt.finished``）。
        payload: 事件载荷（**不含**宿主路径 / Secret）。
        created_at: 事件时刻（可空）。
    """

    seq: int
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class RemoteAttemptView:
    """一次 Attempt 的对外视图（**不含宿主路径**）。"""

    attempt: int
    status: str
    checkout_ref: str | None = None
    base_commit: str | None = None
    result_commit: str | None = None
    environment_digest: str | None = None
    worker_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None
    artifact_refs: dict[str, Any] | None = None


@dataclass(frozen=True)
class RemoteTaskView:
    """远程任务状态快照（**不含宿主路径**）。"""

    task_id: str
    type: str
    status: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    attempt_count: int = 0
    checkout_ref: str | None = None
    base_commit: str | None = None
    result_commit: str | None = None
    environment_digest: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class TaskLogView:
    """任务日志行（由执行记录派生；**不含** Secret 明文）。"""

    seq: int
    attempt: int
    level: str
    message: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class DiffFile:
    """受限 Diff 的单个文件变更（摘要级）。"""

    path: str
    change_type: str
    additions: int = 0
    deletions: int = 0


@dataclass(frozen=True)
class RemoteDiffView:
    """某 Attempt 的**受限** Diff 视图。

    🔴 本波（T2-60）只返回**元数据 + 受限文件摘要**；真实补丁计算与 Apply / Push 归
       **T2-61**（``change_review_service``）。``available`` 表示该 Attempt 是否具备可比
       对结果（``base_commit`` / ``result_commit`` 齐备）。
    """

    attempt: int
    checkout_ref: str | None = None
    base_commit: str | None = None
    result_commit: str | None = None
    available: bool = False
    files: tuple[DiffFile, ...] = ()
    truncated: bool = False


@dataclass(frozen=True)
class ArtifactView:
    """Artifact 元数据（下载**逐项重新鉴权**；此处仅元数据）。"""

    name: str
    ref: str
    size: int | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class ArtifactDownload:
    """Artifact 下载结果（内容经注入 ``ArtifactReader`` 取回）。"""

    view: ArtifactView
    content: bytes
    content_type: str


@dataclass(frozen=True)
class RemoteEventPage:
    """事件分页结果（含下一页**不透明** cursor）。"""

    events: tuple[TaskEvent, ...]
    next_cursor: str


@dataclass(frozen=True)
class RemoteTaskSpec:
    """远程任务提交规格（F-R2）。

    Attributes:
        workspace_id: 归属 Workspace（必填）。
        project_id: 归属 Project（必填）。
        agent_version_id: 固定 Agent 版本（与 ``workflow_version_id`` 二选一）。
        workflow_version_id: 固定 Workflow 版本（与 ``agent_version_id`` 二选一）。
        requirement: 需求文本（用户输入）。
        base_ref: 基准引用（可空）。
        environment_id: 环境标识（可空）。
        idempotency_key: 幂等键（可空；同键同体 → 复用既有 task）。
        limits: 资源限额（可空；具体字段由 T2-59 校验）。
        created_by: 创建者（组合根注入；缺省取 principal.user_id）。
    """

    workspace_id: str
    project_id: str
    agent_version_id: str | None = None
    workflow_version_id: str | None = None
    requirement: str = ""
    base_ref: str | None = None
    environment_id: str | None = None
    idempotency_key: str | None = None
    limits: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None


@dataclass(frozen=True)
class RemoteProjectStatus:
    """远程 Project 状态视图（**不含宿主路径**）。"""

    project_id: str
    name: str
    workspace_id: str
    tenant_id: str | None = None
    default_branch: str | None = None
    repo_configured: bool = False
    clone_task_id: str | None = None
    refs_available: bool = False


@dataclass(frozen=True)
class GitRefView:
    """Git 引用视图（分支 / 标签；**不含宿主路径**）。"""

    name: str
    commit: str | None = None
    kind: str = "branch"


# -- 注入 Protocol（组合根实现；能力包不耦合具体基础设施） -------------------


@runtime_checkable
class RemoteTaskAuthorizer(Protocol):
    """远程访问授权（A-14：``can()`` + scope；由组合根适配 RBAC + ``resource_permission``）。"""

    def authorize(
        self,
        principal: RemotePrincipal,
        *,
        capability: str,
        resource_type: str = TASK_RESOURCE_TYPE,
        resource_id: str | None = None,
    ) -> RemoteAccessDecision:
        """判定 ``principal`` 对 ``resource_id`` 是否具备 ``capability``。"""
        ...


@runtime_checkable
class RemoteAuditSink(Protocol):
    """远程动作审计出口（A-14「记审计」；组合根适配 ``AuditService``）。"""

    def record(
        self,
        *,
        tenant_id: str,
        user_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
        metadata: dict[str, Any],
    ) -> None:
        """写一条审计记录（**不得**含宿主路径 / Secret 明文）。"""
        ...


@runtime_checkable
class RemoteTaskSubmitter(Protocol):
    """远程任务提交器（组合根构造 ``Task`` 实体 + 入队；能力包不 import ``astra_task``）。"""

    def submit(self, spec: RemoteTaskSpec, *, tenant_id: str, user_id: str) -> str:
        """创建并派发远程任务，返回 ``task_id``（同 ``idempotency_key`` 同体 → 复用）。"""
        ...


@runtime_checkable
class TaskEventSource(Protocol):
    """任务级事件源（``seq`` 单调；提供保留窗口低水位以支持「过期 cursor」）。"""

    def list_events(self, task_id: str, *, after_seq: int | None = None) -> list[TaskEvent]:
        """返回 ``seq > after_seq`` 的事件（``seq`` 升序；无 → 空列表）。"""
        ...

    def window_start_seq(self, task_id: str) -> int:
        """返回**保留窗口**内最小可用 ``seq``（无事件 → ``1``）。"""
        ...

    def latest_seq(self, task_id: str) -> int:
        """返回最近一次事件的 ``seq``（无事件 → ``0``）。"""
        ...


@runtime_checkable
class DiffProvider(Protocol):
    """受限 Diff 文件摘要提供者（组合根适配；缺省 → 仅元数据）。"""

    def files(self, record: Any) -> Sequence[DiffFile]:
        """返回某 Attempt 的文件变更摘要列表。"""
        ...


@runtime_checkable
class ArtifactReader(Protocol):
    """Artifact 内容读取器（经 ``Storage``；缺省 → 结构化 503）。"""

    def read(self, ref: str) -> tuple[bytes, str]:
        """读取 Artifact 内容，返回 ``(bytes, content_type)``。"""
        ...


@runtime_checkable
class GitRefsProvider(Protocol):
    """Git 引用查询器（仅经 Sandbox；缺省 → 结构化 503）。"""

    def refs(self, project_id: str, *, tenant_id: str) -> Sequence[GitRefView]:
        """返回某 Project 的 Git 引用列表。"""
        ...


# -- 默认事件源：执行记录派生投影 --------------------------------------------


class ExecutionTaskEventSource:
    """由 ``task_execution`` 记录派生的任务事件源（**持久、单调、可续读**）。

    投影规则（确定性；跨保留窗口 ``seq`` 稳定）：

    - 每个 Attempt 产出至多两条事件：
      ``attempt.started`` → ``seq = 2 * attempt - 1``；
      ``attempt.finished`` → ``seq = 2 * attempt``（仅当 ``finished_at`` 非空）。
    - **保留窗口**（``retention_attempts``）：仅保留最近 N 个 Attempt；裁剪后
      ``window_start_seq`` 上移，早于窗口的 cursor → 过期（``EVENT_CURSOR_EXPIRED``）。
    - **不含宿主路径 / Secret**：载荷仅含 Attempt 序号 / 状态 / 摘要引用。

    🔴 生产可替换为 ``agent_event`` 聚合源（T2-61/63 经组合根装配）；本默认实现保证本波
       本地 SQLite / fake 面可施工、可测（R-R1R5-18）。
    """

    def __init__(
        self,
        executions: TaskExecutionRepository,
        *,
        retention_attempts: int | None = DEFAULT_EVENT_RETENTION_ATTEMPTS,
    ) -> None:
        """构造。

        Args:
            executions: 执行记录仓储（注入 Protocol）。
            retention_attempts: 保留窗口（最近 N 个 Attempt；``None`` = 全保留）。
        """
        self._executions = executions
        self._retention = retention_attempts

    @property
    def retention_attempts(self) -> int | None:
        """返回保留窗口（供组合根 / 测试检视）。"""
        return self._retention

    def _retained(self, task_id: str) -> list[Any]:
        """返回按 ``attempt`` 升序、经保留窗口裁剪后的执行记录。"""
        records = sorted(self._executions.list_by_task(task_id), key=lambda item: int(item.attempt))
        if self._retention is not None and len(records) > self._retention:
            records = records[-self._retention :]
        return records

    def list_events(self, task_id: str, *, after_seq: int | None = None) -> list[TaskEvent]:
        """返回 ``seq > after_seq`` 的派生事件（``seq`` 升序）。"""
        events: list[TaskEvent] = []
        for record in self._retained(task_id):
            attempt = int(record.attempt)
            events.append(
                TaskEvent(
                    seq=2 * attempt - 1,
                    type="attempt.started",
                    payload={
                        "attempt": attempt,
                        "worker_id": getattr(record, "worker_id", None),
                        "checkout_ref": getattr(record, "checkout_ref", None),
                    },
                    created_at=getattr(record, "started_at", None),
                )
            )
            if getattr(record, "finished_at", None) is not None:
                events.append(
                    TaskEvent(
                        seq=2 * attempt,
                        type="attempt.finished",
                        payload={
                            "attempt": attempt,
                            "status": str(getattr(record, "status", "") or ""),
                            "duration_ms": getattr(record, "duration_ms", None),
                            "result_commit": getattr(record, "result_commit", None),
                        },
                        created_at=getattr(record, "finished_at", None),
                    )
                )
        if after_seq is not None:
            events = [event for event in events if event.seq > after_seq]
        return events

    def window_start_seq(self, task_id: str) -> int:
        """返回保留窗口内最小可用 ``seq``（无事件 → ``1``）。"""
        retained = self._retained(task_id)
        if not retained:
            return 1
        return 2 * int(retained[0].attempt) - 1

    def latest_seq(self, task_id: str) -> int:
        """返回最近一次事件的 ``seq``（无事件 → ``0``）。"""
        retained = self._retained(task_id)
        if not retained:
            return 0
        last = retained[-1]
        return (
            2 * int(last.attempt)
            if getattr(last, "finished_at", None) is not None
            else (2 * int(last.attempt) - 1)
        )


# -- 服务 --------------------------------------------------------------------


class RemoteTaskService:
    """远程 Task / Project 用例编排（scope 校验 + 事件游标服务；R3 / T2-60）。"""

    def __init__(
        self,
        *,
        tasks: TaskRepository,
        task_executions: TaskExecutionRepository,
        projects: ProjectRepository,
        authorizer: RemoteTaskAuthorizer | None = None,
        audit: RemoteAuditSink | None = None,
        events: TaskEventSource | None = None,
        submitter: RemoteTaskSubmitter | None = None,
        clone_dispatcher: Any | None = None,
        diff_provider: DiffProvider | None = None,
        artifact_reader: ArtifactReader | None = None,
        git_refs_provider: GitRefsProvider | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """构造（依赖全部经**注入**；能力包零 ORM / 零 Web / 零 Runtime）。

        Args:
            tasks: 任务仓储（注入 Protocol）。
            task_executions: 执行记录仓储（注入 Protocol）。
            projects: 项目仓储（注入 Protocol）。
            authorizer: 远程访问授权（A-14）；缺省 → **拒绝一切远程访问**（deny-by-default）。
            audit: 审计出口；缺省 → 不记审计。
            events: 任务事件源；缺省 → 由执行记录派生（:class:`ExecutionTaskEventSource`）。
            submitter: 远程任务提交器；缺省 → 提交返回结构化 503。
            clone_dispatcher: Project Clone 派发器（``ProjectService.TaskDispatcher`` 同形）。
            diff_provider: 受限 Diff 提供者（缺省 → 仅元数据）。
            artifact_reader: Artifact 内容读取器（缺省 → 结构化 503）。
            git_refs_provider: Git 引用查询器（缺省 → 结构化 503）。
            clock: 时钟（可空；保留位，供扩展）。
        """
        self._tasks = tasks
        self._executions = task_executions
        self._projects = projects
        self._authorizer = authorizer
        self._audit = audit
        self._events = events if events is not None else ExecutionTaskEventSource(task_executions)
        self._submitter = submitter
        self._clone_dispatcher = clone_dispatcher
        self._diff_provider = diff_provider
        self._artifact_reader = artifact_reader
        self._git_refs_provider = git_refs_provider

    # -- 公共属性（供组合根 / 测试检视） -----------------------------------

    @property
    def events(self) -> TaskEventSource:
        """返回注入 / 派生的任务事件源。"""
        return self._events

    # -- 远程 Project -------------------------------------------------------

    def project_status(self, principal: RemotePrincipal, project_id: str) -> RemoteProjectStatus:
        """远程 Project 状态（跨租户 / 越界 → 404）。"""
        project = self._require_project(principal, project_id)
        self._authorize(principal, capability=CAPABILITY_PROJECT_READ, resource_id=project_id)
        clone_task_id = self._latest_clone_task_id(principal, project_id)
        return RemoteProjectStatus(
            project_id=str(project.id),
            name=str(project.name or ""),
            workspace_id=str(project.workspace_id or ""),
            tenant_id=project.tenant_id,
            default_branch=project.default_branch,
            repo_configured=bool((project.repo_url or "").strip()),
            clone_task_id=clone_task_id,
            refs_available=self._git_refs_provider is not None,
        )

    def clone_project(
        self,
        principal: RemotePrincipal,
        project_id: str,
        *,
        base_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """显式 Clone 项目（异步派发 ``project.clone``；返回 ``task_id``；F-R1）。

        Raises:
            DomainError: 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）、
                无仓库地址（``VALIDATION_ERROR``）、未装配派发器（``DEPENDENCY_MISSING``）。
        """
        project = self._require_project(principal, project_id)
        self._authorize(principal, capability=CAPABILITY_PROJECT_CLONE, resource_id=project_id)
        repo_url = (project.repo_url or "").strip()
        if not repo_url:
            raise DomainError(
                "项目未配置仓库地址，无法克隆",
                code=ErrorCode.VALIDATION_ERROR,
                data={"project_id": project_id, "field": "repo_url"},
            )
        if self._clone_dispatcher is None:
            raise self._dependency_missing("project.clone")
        task_id = self._clone_dispatcher.dispatch_clone(
            tenant_id=principal.tenant_id,
            workspace_id=str(project.workspace_id or ""),
            project_id=project_id,
            repo_url=repo_url,
            base_ref=base_ref,
        )
        self._record(
            principal,
            action="project.remote.clone",
            resource_type=PROJECT_RESOURCE_TYPE,
            resource_id=project_id,
            outcome=AUDIT_OUTCOME_SUCCESS,
            metadata={"task_id": task_id, "idempotency_key": idempotency_key},
        )
        return str(task_id)

    def list_git_refs(self, principal: RemotePrincipal, project_id: str) -> list[GitRefView]:
        """查询项目 Git 引用（分支 / 标签；**不含宿主路径**）。

        Raises:
            DomainError: 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）、
                未装配 Git 引用查询器（``DEPENDENCY_MISSING`` → 503）。
        """
        self._require_project(principal, project_id)
        self._authorize(principal, capability=CAPABILITY_PROJECT_READ, resource_id=project_id)
        if self._git_refs_provider is None:
            raise self._dependency_missing("project.git_refs")
        return list(self._git_refs_provider.refs(project_id, tenant_id=principal.tenant_id))

    # -- 远程 Task：提交 / 列表 / 状态 / 取消 -------------------------------

    def submit(self, principal: RemotePrincipal, spec: RemoteTaskSpec) -> str:
        """远程提交一个 Task（F-R2；返回 ``task_id``）。

        Raises:
            DomainError: 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED`` → 403）、
                参数非法（``VALIDATION_ERROR``）、未装配提交器（``DEPENDENCY_MISSING``）。
        """
        self._validate_spec(spec)
        project = self._require_project(principal, spec.project_id)
        if str(project.workspace_id or "") != spec.workspace_id:
            # 工作区与项目不匹配 → 统一隔离 404（不泄漏存在性）。
            raise self._not_found("project", spec.project_id)
        # 创建为**变更**操作：缺 capability → 403（不静默）。
        self._authorize(
            principal,
            capability=CAPABILITY_TASK_SUBMIT,
            resource_id=spec.project_id,
            mutation=True,
        )
        if self._submitter is None:
            raise self._dependency_missing("task.submit")
        task_id = self._submitter.submit(
            spec, tenant_id=principal.tenant_id, user_id=principal.user_id
        )
        self._record(
            principal,
            action=TASK_ACTION_SUBMIT,
            resource_type=TASK_RESOURCE_TYPE,
            resource_id=str(task_id),
            outcome=AUDIT_OUTCOME_SUCCESS,
            metadata={
                "project_id": spec.project_id,
                "workspace_id": spec.workspace_id,
                "idempotency_key": spec.idempotency_key,
            },
        )
        return str(task_id)

    def list_tasks(
        self,
        principal: RemotePrincipal,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RemoteTaskView]:
        """列出远程任务（**列表重新鉴权**；缺 capability → 403，不枚举）。"""
        self._authorize(
            principal,
            capability=CAPABILITY_TASK_READ,
            resource_id=project_id,
            mutation=True,
        )
        filters: dict[str, Any] = {"tenant_id": principal.tenant_id}
        if status:
            filters["status"] = status
        tasks = self._tasks.list(**filters)
        views = [self._to_task_view(task) for task in tasks]
        views = [view for view in views if view.project_id is not None]
        if workspace_id:
            views = [view for view in views if view.workspace_id == workspace_id]
        if project_id:
            views = [view for view in views if view.project_id == project_id]
        return views[offset : offset + limit]

    def get_task(self, principal: RemotePrincipal, task_id: str) -> RemoteTaskView:
        """任务状态快照（跨租户 / 越界 → 404）。"""
        task = self._require_task(principal, task_id, capability=CAPABILITY_TASK_READ)
        return self._to_task_view(task)

    def cancel(self, principal: RemotePrincipal, task_id: str) -> Any:
        """取消任务（``EXECUTE + task.cancel``；终态**幂等**返回既有状态）。

        Returns:
            更新后（或既有终态）的**任务实体**（供 Router 复用 ``_to_task_response`` 映射）。

        Raises:
            DomainError: 跨租户 / 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）。
        """
        task = self._require_task(principal, task_id, capability=CAPABILITY_TASK_CANCEL)
        if task.is_terminal:
            self._record(
                principal,
                action=TASK_ACTION_CANCEL,
                resource_type=TASK_RESOURCE_TYPE,
                resource_id=task_id,
                outcome=AUDIT_OUTCOME_SUCCESS,
                metadata={"idempotent": True, "status": str(task.status)},
            )
            return task
        task.cancel()
        updated = self._tasks.update(task)
        self._record(
            principal,
            action=TASK_ACTION_CANCEL,
            resource_type=TASK_RESOURCE_TYPE,
            resource_id=task_id,
            outcome=AUDIT_OUTCOME_SUCCESS,
            metadata={"status": str(updated.status)},
        )
        return updated

    # -- 远程 Task：Attempt / Event / Log / Diff / Artifact -----------------

    def list_attempts(self, principal: RemotePrincipal, task_id: str) -> list[RemoteAttemptView]:
        """列出任务的执行 Attempt（跨租户 / 越界 → 404）。"""
        self._require_task(principal, task_id, capability=CAPABILITY_TASK_READ)
        return [self._to_attempt_view(record) for record in self._sorted_executions(task_id)]

    def list_events(
        self,
        principal: RemotePrincipal,
        task_id: str,
        *,
        cursor: str | None = None,
        last_event_id: str | None = None,
    ) -> RemoteEventPage:
        """事件回放 / 续读（不透明 cursor / ``Last-Event-ID``；过期 → ``EVENT_CURSOR_EXPIRED``）。

        Raises:
            DomainError: 跨租户 / 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）、
                非法 cursor（``VALIDATION_ERROR``）、过期 cursor（``EVENT_CURSOR_EXPIRED`` → 410）。
        """
        self._require_task(principal, task_id, capability=CAPABILITY_TASK_READ)
        after_seq = self._resolve_cursor(task_id, cursor=cursor, last_event_id=last_event_id)
        events = self._events.list_events(task_id, after_seq=after_seq)
        tail = events[-1].seq if events else (after_seq if after_seq is not None else 0)
        return RemoteEventPage(events=tuple(events), next_cursor=self._encode_cursor(task_id, tail))

    def list_logs(self, principal: RemotePrincipal, task_id: str) -> list[TaskLogView]:
        """列出任务日志行（由执行记录派生；跨租户 / 越界 → 404）。"""
        self._require_task(principal, task_id, capability=CAPABILITY_TASK_READ)
        logs: list[TaskLogView] = []
        for record in self._sorted_executions(task_id):
            attempt = int(record.attempt)
            status = str(getattr(record, "status", "") or "")
            logs.append(
                TaskLogView(
                    seq=2 * attempt - 1,
                    attempt=attempt,
                    level="info",
                    message=f"attempt {attempt} started ({status})",
                    created_at=getattr(record, "started_at", None),
                )
            )
            error = getattr(record, "error", None)
            if error:
                logs.append(
                    TaskLogView(
                        seq=2 * attempt,
                        attempt=attempt,
                        level="error",
                        message=str(error),
                        created_at=getattr(record, "finished_at", None),
                    )
                )
        return logs

    def get_diff(
        self, principal: RemotePrincipal, task_id: str, *, attempt: int | None = None
    ) -> RemoteDiffView:
        """返回某 Attempt 的**受限** Diff（``EXECUTE + git.diff``；不 Apply / 不 Push）。

        Raises:
            DomainError: 跨租户 / 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）、
                Attempt 不存在（``NOT_FOUND``）。
        """
        self._require_task(
            principal, task_id, capability=CAPABILITY_GIT_DIFF, action=TASK_ACTION_DIFF
        )
        record = self._require_attempt(task_id, attempt)
        files: tuple[DiffFile, ...] = ()
        if self._diff_provider is not None:
            files = tuple(self._diff_provider.files(record))
        base_commit = getattr(record, "base_commit", None)
        result_commit = getattr(record, "result_commit", None)
        return RemoteDiffView(
            attempt=int(record.attempt),
            checkout_ref=getattr(record, "checkout_ref", None),
            base_commit=base_commit,
            result_commit=result_commit,
            available=bool(base_commit and result_commit),
            files=files,
        )

    def list_artifacts(
        self, principal: RemotePrincipal, task_id: str, *, attempt: int | None = None
    ) -> list[ArtifactView]:
        """列出某 Attempt 的 Artifact 元数据（跨租户 / 越界 → 404）。"""
        self._require_task(principal, task_id, capability=CAPABILITY_TASK_READ)
        record = self._require_attempt(task_id, attempt)
        return self._artifact_views(getattr(record, "artifact_refs", None))

    def download_artifact(
        self,
        principal: RemotePrincipal,
        task_id: str,
        *,
        name: str,
        attempt: int | None = None,
    ) -> ArtifactDownload:
        """下载 Artifact（**逐项重新鉴权**；``EXECUTE + artifact.download``）。

        Raises:
            DomainError: 跨租户 / 越界（``NOT_FOUND``）、缺 capability（``PERMISSION_DENIED``）、
                Artifact 不存在（``NOT_FOUND``）、未装配读取器（``DEPENDENCY_MISSING`` → 503）。
        """
        self._require_task(
            principal,
            task_id,
            capability=CAPABILITY_ARTIFACT_DOWNLOAD,
            action=TASK_ACTION_DOWNLOAD,
        )
        record = self._require_attempt(task_id, attempt)
        refs = getattr(record, "artifact_refs", None)
        views = {view.name: view for view in self._artifact_views(refs)}
        view = views.get(name)
        if view is None:
            raise self._not_found("artifact", name)
        if self._artifact_reader is None:
            raise self._dependency_missing("task.artifact.download")
        content, content_type = self._artifact_reader.read(view.ref)
        self._record(
            principal,
            action=TASK_ACTION_DOWNLOAD,
            resource_type=TASK_RESOURCE_TYPE,
            resource_id=task_id,
            outcome=AUDIT_OUTCOME_SUCCESS,
            metadata={"artifact": name, "attempt": int(record.attempt)},
        )
        return ArtifactDownload(
            view=view,
            content=content,
            content_type=content_type or view.content_type or "application/octet-stream",
        )

    # -- 内部：resolver -----------------------------------------------------

    def _require_project(self, principal: RemotePrincipal, project_id: str) -> Any:
        """取项目（不存在 / 跨租户 → 404；不泄漏存在性）。"""
        project = self._projects.get(project_id)
        if project is None or str(getattr(project, "tenant_id", "") or "") != principal.tenant_id:
            raise self._not_found("project", project_id)
        return project

    def _require_task(
        self,
        principal: RemotePrincipal,
        task_id: str,
        *,
        capability: str,
        action: str | None = None,
    ) -> Any:
        """取任务（不存在 / 跨租户 → 404）+ 逐次授权（缺 capability → 403 / 越界 → 404）。"""
        task = self._tasks.get(task_id)
        if task is None or str(getattr(task, "tenant_id", "") or "") != principal.tenant_id:
            raise self._not_found("task", task_id)
        if not self._is_remote_task(task):
            raise self._not_found("task", task_id)
        self._authorize(
            principal,
            capability=capability,
            resource_id=self._task_project_id(task),
            action=action,
        )
        return task

    def _require_attempt(self, task_id: str, attempt: int | None) -> Any:
        """取指定（缺省取最近）Attempt；不存在 → 404。"""
        records = self._sorted_executions(task_id)
        if not records:
            raise self._not_found("attempt", f"{task_id}:{attempt or 1}")
        if attempt is None:
            return records[-1]
        match = next((record for record in records if int(record.attempt) == int(attempt)), None)
        if match is None:
            raise self._not_found("attempt", f"{task_id}:{attempt}")
        return match

    # -- 内部：authorization -------------------------------------------------

    def _authorize(
        self,
        principal: RemotePrincipal,
        *,
        capability: str,
        resource_id: str | None,
        action: str | None = None,
        mutation: bool = False,
    ) -> None:
        """逐次校验（A-14）。策略：

        - 缺 capability 且**变更 / 集合**操作（``mutation=True``）→ **403**（不静默 / 不枚举）；
        - 缺 capability 且**单资源读取**：``in_scope`` 为真 → **403**；否则 → **404**
          （统一隔离，不泄漏存在性）；
        - 授权通过 → 放行；失败另记**拒绝审计**（``outcome=DENIED``）。
        """
        decision = self._decide(principal, capability=capability, resource_id=resource_id)
        if decision.allowed:
            return
        self._record(
            principal,
            action=action or capability,
            resource_type=TASK_RESOURCE_TYPE,
            resource_id=resource_id,
            outcome=AUDIT_OUTCOME_DENIED,
            metadata={"capability": capability, "reason": decision.reason},
        )
        if mutation or decision.in_scope:
            raise DomainError(
                "缺少远程访问权限",
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

    # -- 内部：cursor --------------------------------------------------------

    def encode_event_cursor(self, task_id: str, seq: int) -> str:
        """生成**不透明**事件游标（``tev_<base64url(task_id:seq)>``；不含宿主路径）。"""
        raw = f"{task_id}:{int(seq)}".encode()
        token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return f"{TASK_EVENT_CURSOR_PREFIX}{token}"

    #: 兼容别名（供 Router / 测试以「cursor」语义调用）。
    _encode_cursor = encode_event_cursor

    def decode_event_cursor(self, cursor: str, *, task_id: str) -> int:
        """还原不透明游标为 ``seq``（校验所属 ``task_id`；格式非法 → 422）。

        Raises:
            DomainError: 游标格式非法 / 不属于该任务（``VALIDATION_ERROR``）。
        """
        text = str(cursor or "")
        if not text.startswith(TASK_EVENT_CURSOR_PREFIX):
            raise DomainError(
                "非法事件游标",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "cursor"},
            )
        token = text[len(TASK_EVENT_CURSOR_PREFIX) :]
        padding = "=" * (-len(token) % 4)
        try:
            decoded = base64.urlsafe_b64decode(f"{token}{padding}").decode("utf-8")
            owner, _, seq_text = decoded.rpartition(":")
            seq = int(seq_text)
        except (ValueError, UnicodeDecodeError) as exc:
            raise DomainError(
                "非法事件游标",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "cursor"},
            ) from exc
        if owner != task_id or seq < 0:
            raise DomainError(
                "非法事件游标",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "cursor"},
            )
        return seq

    def _resolve_cursor(
        self, task_id: str, *, cursor: str | None, last_event_id: str | None
    ) -> int | None:
        """解析续读起点：``?cursor=`` 优先（不透明句柄），``Last-Event-ID`` 回退（序号）。

        Raises:
            DomainError: 游标非法（``VALIDATION_ERROR``）或**已过期**
                （``EVENT_CURSOR_EXPIRED`` → 410）。
        """
        raw = cursor if cursor else last_event_id
        if not raw:
            return None
        if str(raw).startswith(TASK_EVENT_CURSOR_PREFIX):
            seq = self.decode_event_cursor(str(raw), task_id=task_id)
        else:
            try:
                seq = int(str(raw))
            except ValueError as exc:
                raise DomainError(
                    "非法事件游标",
                    code=ErrorCode.VALIDATION_ERROR,
                    data={"field": "cursor"},
                ) from exc
        window_start = self._events.window_start_seq(task_id)
        if seq < window_start - 1:
            raise DomainError(
                "事件游标已过期",
                code=ErrorCode.EVENT_CURSOR_EXPIRED,
                status_code=410,
                data={"cursor": str(raw), "window_start_seq": window_start},
            )
        return seq

    # -- 内部：映射 / 工具 ---------------------------------------------------

    def _sorted_executions(self, task_id: str) -> list[Any]:
        """按 ``attempt`` 升序返回执行记录。"""
        return sorted(self._executions.list_by_task(task_id), key=lambda item: int(item.attempt))

    @staticmethod
    def _is_remote_task(task: Any) -> bool:
        """是否为远程任务（未携带 ``project_id`` 的既有任务不属远程面）。"""
        payload = dict(getattr(task, "payload", None) or {})
        return bool(payload.get("project_id"))

    @staticmethod
    def _task_project_id(task: Any) -> str | None:
        """取任务归属 Project（来自 ``task.payload['project_id']``）。"""
        payload = dict(getattr(task, "payload", None) or {})
        value = payload.get("project_id")
        return str(value) if value else None

    def _to_task_view(self, task: Any) -> RemoteTaskView:
        """任务实体 → 远程视图（取最近 Attempt 的不透明引用 / 提交哈希）。"""
        records = self._sorted_executions(str(task.task_id))
        latest = records[-1] if records else None
        return RemoteTaskView(
            task_id=str(task.task_id),
            type=str(task.type),
            status=str(task.status),
            tenant_id=getattr(task, "tenant_id", None),
            workspace_id=getattr(task, "workspace_id", None),
            project_id=self._task_project_id(task),
            attempt_count=len(records),
            checkout_ref=getattr(latest, "checkout_ref", None) if latest else None,
            base_commit=getattr(latest, "base_commit", None) if latest else None,
            result_commit=getattr(latest, "result_commit", None) if latest else None,
            environment_digest=getattr(latest, "environment_digest", None) if latest else None,
            created_at=getattr(task, "created_at", None),
            updated_at=getattr(task, "updated_at", None),
        )

    @staticmethod
    def _to_attempt_view(record: Any) -> RemoteAttemptView:
        """执行记录 → Attempt 视图。"""
        return RemoteAttemptView(
            attempt=int(record.attempt),
            status=str(getattr(record, "status", "") or ""),
            checkout_ref=getattr(record, "checkout_ref", None),
            base_commit=getattr(record, "base_commit", None),
            result_commit=getattr(record, "result_commit", None),
            environment_digest=getattr(record, "environment_digest", None),
            worker_id=getattr(record, "worker_id", None),
            started_at=getattr(record, "started_at", None),
            finished_at=getattr(record, "finished_at", None),
            duration_ms=getattr(record, "duration_ms", None),
            error=getattr(record, "error", None),
            artifact_refs=dict(getattr(record, "artifact_refs", None) or {}) or None,
        )

    @staticmethod
    def _artifact_views(refs: Any) -> list[ArtifactView]:
        """``artifact_refs`` JSON → Artifact 元数据视图（兼容 ``str`` / ``dict``）。"""
        if not isinstance(refs, dict):
            return []
        views: list[ArtifactView] = []
        for name, value in refs.items():
            if isinstance(value, dict):
                ref = str(value.get("ref") or "")
                if not ref:
                    continue
                views.append(
                    ArtifactView(
                        name=str(name),
                        ref=ref,
                        size=value.get("size"),
                        content_type=value.get("content_type"),
                    )
                )
            elif value:
                views.append(ArtifactView(name=str(name), ref=str(value)))
        return views

    def _latest_clone_task_id(self, principal: RemotePrincipal, project_id: str) -> str | None:
        """取该 Project 最近一次 ``project.clone`` 任务 id（无 → ``None``）。"""
        tasks = self._tasks.list(tenant_id=principal.tenant_id, type=PROJECT_CLONE_TASK_TYPE)
        matches = [
            task
            for task in tasks
            if str((dict(getattr(task, "payload", None) or {})).get("project_id") or "")
            == project_id
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: str(getattr(item, "created_at", "") or ""))
        return str(matches[-1].task_id)

    @staticmethod
    def _validate_spec(spec: RemoteTaskSpec) -> None:
        """校验提交规格（必填 + 版本二选一）。

        Raises:
            DomainError: 缺必填字段或版本二选一未满足（``VALIDATION_ERROR``）。
        """
        if not spec.workspace_id:
            raise DomainError(
                "远程提交缺少 workspace_id",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "workspace_id"},
            )
        if not spec.project_id:
            raise DomainError(
                "远程提交缺少 project_id",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "project_id"},
            )
        if bool(spec.agent_version_id) == bool(spec.workflow_version_id):
            raise DomainError(
                "远程提交须且仅须提供 agent_version_id 或 workflow_version_id 之一",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "agent_version_id|workflow_version_id"},
            )

    def _record(
        self,
        principal: RemotePrincipal,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
        metadata: dict[str, Any],
    ) -> None:
        """写审计（缺审计出口 → 静默跳过；**不因审计失败中断业务**）。"""
        if self._audit is None:
            return
        try:
            self._audit.record(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                metadata=dict(metadata),
            )
        except Exception:  # noqa: BLE001 - 审计失败不得阻断业务（对齐 AuditService 语义）
            pass

    @staticmethod
    def _not_found(kind: str, identifier: str) -> DomainError:
        """统一隔离 404（不泄漏存在性）。"""
        return DomainError(
            "资源不存在",
            code=ErrorCode.NOT_FOUND,
            status_code=404,
            data={"kind": kind, "id": identifier},
        )

    @staticmethod
    def _dependency_missing(capability: str) -> DomainError:
        """结构化 503（能力未装配；**不 500、不静默空**）。"""
        return DomainError(
            "远程能力未装配",
            code=ErrorCode.DEPENDENCY_MISSING,
            status_code=503,
            data={"capability": capability},
        )
