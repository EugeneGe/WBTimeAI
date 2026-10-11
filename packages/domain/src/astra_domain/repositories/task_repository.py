"""Task 仓储接口（**仅 Protocol**，零 ORM；W5 / T1-26）。

对应 ORM 表：``task``。领域模型 :class:`astra_task.models.Task`（状态机驱动）。

🔴 设计 §2.15.1：``task`` 的 SQL 仓储落 ``astra_database/repositories``（ORM 允许位置，
   A19 先例）；``packages/task`` 保持零 ORM（禁 ``astra_database`` 导入，F3）。

为使 ``astra_domain`` 保持**零框架 / 零任务实现依赖**，此处仅以 ``TYPE_CHECKING``
引入 :class:`astra_task.Task` 作为实体类型（运行期不形成 ``domain → task`` 依赖）。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .base import Repository

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_task import ScheduleSpec, Task, TaskExecutionRecord

__all__ = ["TaskRepository", "TaskExecutionRepository", "ScheduleRepository"]


@runtime_checkable
class TaskRepository(Repository["Task"], Protocol):
    """Task 仓储接口（多租户 / 类型 / 状态查询）。"""

    def list_by_type(self, task_type: str) -> list[Task]:
        """列出某类型的全部任务（如 ``agent.run``）。"""
        ...

    def list_by_status(self, status: str) -> list[Task]:
        """列出某状态的全部任务。"""
        ...


@runtime_checkable
class TaskExecutionRepository(Repository["TaskExecutionRecord"], Protocol):
    """``task_execution`` 仓储接口（**零 ORM**；W7 / T2-39）。

    对应 ORM 表：``task_execution``（唯一键 ``(task_id, attempt)``）。领域模型
    :class:`astra_task.TaskExecutionRecord`（零 ORM，经注入 Protocol 使用）。
    """

    def list_by_task(self, task_id: str) -> list[TaskExecutionRecord]:
        """列出某任务的全部执行记录（按 ``attempt`` 升序）。"""
        ...

    def get_by_attempt(self, task_id: str, attempt: int) -> TaskExecutionRecord | None:
        """按 ``(task_id, attempt)`` 获取执行记录，不存在返回 ``None``。"""
        ...


@runtime_checkable
class ScheduleRepository(Repository["ScheduleSpec"], Protocol):
    """``schedule`` 仓储接口（**零 ORM**；W7 / T2-39）。

    对应 ORM 表：``schedule``（唯一键 ``(tenant_id, target_type, target_id, name)``）。领域模型
    :class:`astra_task.ScheduleSpec`。

    🔴 **`create` 以原语入参**（而非实体）——使 API 层（Router 不 import ``astra_task``）
       亦能经本 Protocol 落调度（分层纪律）。
    🔴 **`get_or_create_task` 封装冻结的幂等契约**（R6）：同一 ``idempotency_key`` 二次触发
       **只产生 1 个 task**，命中唯一索引 → 返回**既有** ``task_id``（``created=False``）。
    """

    def create(
        self,
        *,
        tenant_id: str,
        name: str,
        target_type: str,
        target_id: str,
        trigger: str,
        workspace_id: str | None = None,
        organization_id: str | None = None,
        cron: str | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> ScheduleSpec:
        """创建调度（以原语入参，内部构造领域实体 + 校验）。"""
        ...

    def list_due(
        self, *, now: datetime, tenant_id: str | None = None, limit: int | None = None
    ) -> list[ScheduleSpec]:
        """列出 ``enabled`` 且 ``next_run_at <= now`` 的到期调度（按 ``next_run_at`` 升序）。"""
        ...

    def list_by_tenant(self, tenant_id: str) -> list[ScheduleSpec]:
        """列出某租户的全部调度。"""
        ...

    def mark_fired(
        self, schedule_id: str, *, fired_at: datetime, next_run_at: datetime | None
    ) -> ScheduleSpec | None:
        """标记调度已触发（写 ``last_run_at`` / ``next_run_at``），返回更新后的调度。"""
        ...

    def get_or_create_task(
        self,
        *,
        tenant_id: str,
        workspace_id: str | None,
        task_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[str, bool]:
        """幂等创建 ``task``：命中 ``idempotency_key`` 返回既有 id；否则新建。

        Returns:
            ``(task_id, created)``——``created=False`` 表示命中既有 task（幂等）。
        """
        ...
