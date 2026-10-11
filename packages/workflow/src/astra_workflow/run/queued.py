"""``QUEUED`` 运行形态（异步 ``TaskQueue``；W4 / T2-24；设计 §2.9 / §2.15.2 / §2.16）。

异步路径：``WorkflowService.run(mode=QUEUED)`` → 预建 ``WorkflowRun(task_id)`` +
``task(PENDING, type=workflow.run)`` → ``TaskQueue.enqueue`` → **Worker**
``handle_workflow_run`` → Application ``WorkflowService.execute``
（同 ``agent.run`` 的 ``execute_agent`` 接线范式，F17）。

**执行体与队列正交**（R-23 / F6）：本模块**只**负责「入队 + 出队后执行」，
队列实现（``InProcessTaskQueue`` / ``RedisTaskQueue``）由 ``build_providers``
**唯一分流点**装配，**本模块不 import 任何具体队列实现**，也不 import
``astra_task`` 实体（以 :class:`TaskLike` Protocol 面向抽象）。

🔴 ``task.type`` 为 ``String(100)``，取值 ``workflow.run`` **免迁移**（F18）；
   Workflow **复用** ``task`` 表，**不新增任务表**（设计 §2.15.2）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode

from ..domain import WORKFLOW_RUN_STATUS_CANCELLED, WorkflowRunRepository

__all__ = [
    "EXECUTION_MODE_QUEUED",
    "WORKFLOW_TASK_TYPE",
    "TaskLike",
    "TaskRepositoryLike",
    "TaskQueueLike",
    "QueuedRunner",
]


#: 运行形态字面值：异步队列。
EXECUTION_MODE_QUEUED = "QUEUED"

#: Workflow 复用 ``task`` 表的类型取值（**免迁移**，F18）。
WORKFLOW_TASK_TYPE = "workflow.run"


@runtime_checkable
class TaskLike(Protocol):
    """``task`` 行的最小契约（避免本包 import ``astra_task`` 实体）。

    🔴 主键字段沿用 ``astra_task.Task`` 的 ``task_id``（``task`` ORM 行的 ``id``
       为同一主键的持久化别名，:func:`_task_id` 两者皆可解析）。

    Attributes:
        task_id: 任务标识（UUIDv7）。
        type: 任务类型（``workflow.run``）。
        status: 任务状态（``TaskStatus`` 字面值）。
        payload: 任务载荷。
    """

    task_id: str
    type: str
    status: str
    payload: dict[str, Any]


@runtime_checkable
class TaskRepositoryLike(Protocol):
    """``task`` 仓储的最小契约（由组合根注入）。"""

    def add(self, task: Any) -> Any:
        """新增任务并返回。"""
        ...

    def update(self, task: Any) -> Any:
        """更新任务并返回。"""
        ...


@runtime_checkable
class TaskQueueLike(Protocol):
    """``TaskQueue`` 的最小契约（``enqueue``；由组合根注入具体实现）。"""

    def enqueue(self, item: Any) -> None:
        """入队。"""
        ...


def _task_id(task: Any) -> str | None:
    """解析任务标识（``astra_task.Task.task_id`` 优先，回落 ``task`` 行主键 ``id``）。

    Args:
        task: 任务实体 / 行对象。

    Returns:
        任务标识；不可解析返回 ``None``（**不伪造**）。
    """
    raw = getattr(task, "task_id", None)
    if raw is None:
        raw = getattr(task, "id", None)
    return str(raw or "") or None


class QueuedRunner:
    """``QUEUED`` 运行形态：入队 + 出队后**同步执行**。

    入队与执行**分离**：

    - :meth:`enqueue`：建 ``task(PENDING, type=workflow.run)`` → 挂到
      ``WorkflowRun.task_id`` → 入队；**不执行**。
    - :meth:`execute`：真正驱动引擎（Worker 侧经 Application 落到本方法）。

    Attributes:
        runs: 运行记录仓储。
        tasks: 任务仓储。
        queue: 任务队列。
        task_factory: 任务行构造回调（``(run, payload) -> TaskLike``）。
        executor: 执行回调（``(run_id) -> WorkflowRun``）。
    """

    def __init__(
        self,
        runs: WorkflowRunRepository,
        *,
        tasks: TaskRepositoryLike | None = None,
        queue: TaskQueueLike | None = None,
        task_factory: Callable[[Any, dict[str, Any]], Any] | None = None,
        executor: Callable[[str], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """装配异步运行器（全部依赖由**组合根**注入）。

        Args:
            runs: 运行记录仓储。
            tasks: 任务仓储（``QUEUED`` 入队必需）。
        queue: 任务队列（``QUEUED`` 入队必需）。
            task_factory: 任务行构造回调；缺省经 ``astra_task.Task`` 构造。
            executor: 执行回调（通常＝Application ``WorkflowService.execute``）。
            clock: 时间源（测试可注入 fake clock）。
        """
        self.runs = runs
        self.tasks = tasks
        self.queue = queue
        self._task_factory = task_factory
        self._executor = executor
        self._clock = clock

    # -- 入队 -----------------------------------------------------------------

    def enqueue(self, run_id: str, *, payload: dict[str, Any] | None = None) -> Any:
        """把一次运行挂到 ``workflow.run`` 任务并入队（**不执行**）。

        Args:
            run_id: 目标运行标识（由 Application 预建）。
            payload: 附加队列载荷（如 ``tenant_id`` / ``workspace_id``）。

        Returns:
            已挂靠 ``task_id`` 的运行实体。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）/ 任务仓储或队列未装配
                （``CONFIGURATION_ERROR``）。
        """
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                f"WorkflowRun 不存在，无法入队：{run_id}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_run_not_found", "workflow_run_id": run_id},
            )
        if self.tasks is None:
            raise DomainError(
                "QUEUED 形态需任务仓储（tasks）以建 workflow.run 任务",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "task_repository_missing", "workflow_run_id": run_id},
            )
        if self.queue is None:
            raise DomainError(
                "QUEUED 形态需任务队列（queue）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "task_queue_missing", "workflow_run_id": run_id},
            )

        extra = dict(payload or {})
        task = self._new_task(run, extra)
        self.tasks.add(task)
        run.task_id = _task_id(task)
        self.runs.update(run)
        self.queue.enqueue(
            {
                "handler": WORKFLOW_TASK_TYPE,
                "payload": {"workflow_run_id": str(run.id or ""), **extra},
                "task_id": run.task_id,
                "tenant_id": run.tenant_id,
            }
        )
        return run

    # -- 出队后执行（Worker 侧） ----------------------------------------------

    def execute(self, run_id: str) -> Any:
        """Worker 侧执行一次已入队的运行（驱动引擎至终态 / 挂起）。

        Raises:
            DomainError: 执行回调未装配（``CONFIGURATION_ERROR``）/ 运行不存在
                （``NOT_FOUND``）。
        """
        if self._executor is None:
            raise DomainError(
                "QUEUED 形态需执行回调（executor＝Application WorkflowService.execute）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "workflow_executor_missing", "workflow_run_id": run_id},
            )
        result = self._executor(run_id)
        if result is not None:
            return result
        return self.runs.get(run_id)

    def run_status(self, run_id: str) -> str | None:
        """读运行当前状态（不存在 → ``None``）。"""
        run = self.runs.get(run_id)
        if run is None:
            return None
        return str(run.status or "")

    def cancel(self, run_id: str) -> Any:
        """取消一次入队 / 执行中的运行（``→ CANCELLED``）。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）。
        """
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                f"WorkflowRun 不存在，无法取消：{run_id}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_run_not_found", "workflow_run_id": run_id},
            )
        if run.status != WORKFLOW_RUN_STATUS_CANCELLED:
            run.cancel()
            self.runs.update(run)
        return run

    # -- 内部 -----------------------------------------------------------------

    def _new_task(self, run: Any, payload: dict[str, Any]) -> Any:
        """构造 ``workflow.run`` 任务行。

        Returns:
            任务行（``PENDING``）。

        Raises:
            DomainError: 无 ``task_factory`` 且 ``astra_task`` 不可用
                （``CONFIGURATION_ERROR``）。
        """
        if self._task_factory is not None:
            return self._task_factory(run, payload)
        try:
            from astra_task import Task, TaskStatus
        except ImportError as exc:  # pragma: no cover - 依赖缺失即显式失败
            raise DomainError(
                "构造 workflow.run 任务需 astra_task（或注入 task_factory）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"reason": "task_model_unavailable"},
            ) from exc
        return Task(
            type=WORKFLOW_TASK_TYPE,
            status=TaskStatus.PENDING,
            payload={"run_id": str(run.id or ""), **payload},
            tenant_id=run.tenant_id,
        )

    @property
    def executor(self) -> Callable[[str], Any] | None:
        """执行回调（供 Worker 组合根诊断）。"""
        return self._executor
