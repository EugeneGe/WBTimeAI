"""``RunService``（AI 任务挂靠：``task type="agent.run"`` + ``execution_mode``）。

W5 / T1-26（设计 §2.11 / §3-#12；``I-P1-12``）：

- 一次 Agent 执行创建 ``task``（``type="agent.run"``，``payload`` 带
  ``run_id`` / ``agent_id`` / ``conversation_id``），``agent_run.task_id`` 反向关联；
- ``task.execution_mode`` 与 ``agent_run.run_mode`` **同源**；
- **状态映射**：``RUNNING↔RUNNING``、``SUCCESS`` / ``FAILED`` / ``CANCELLED`` 一一对应；
- **INLINE 路径**：``CREATED → RUNNING → 终态``（**跳过 PENDING**）；
  **QUEUED 路径**：``CREATED → PENDING → RUNNING → 终态``。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from astra_common.time import utcnow
from astra_core import ErrorCode
from astra_domain import (
    RUN_MODE_INLINE,
    RUN_STATUS_FAILED,
    SANDBOX_SESSION_STATUS_STOPPED,
    AgentRun,
    SandboxSessionRepository,
    TaskRepository,
)
from astra_task import Task

from ..repositories import SqlAgentRunRepository

__all__ = ["RunService", "AGENT_RUN_TASK_TYPE"]

#: Agent 执行挂靠的任务类型。
AGENT_RUN_TASK_TYPE = "agent.run"

#: 心跳超期兜底失败的错误类型（W6 / T1-31）。
HEARTBEAT_TIMEOUT_ERROR_TYPE = str(ErrorCode.HEARTBEAT_TIMEOUT)

#: Run 状态 → Task 状态映射（一一对应，设计 §2.11）。
_RUN_TO_TASK_STATUS: dict[str, str] = {
    "PENDING": "PENDING",
    "RUNNING": "RUNNING",
    "SUCCESS": "SUCCESS",
    "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
}


class RunService:
    """Run ↔ Task 挂靠服务（经 DI 注入领域 Protocol 仓储）。"""

    def __init__(
        self,
        *,
        run_repository: SqlAgentRunRepository,
        task_repository: TaskRepository,
        sandbox_repository: SandboxSessionRepository | None = None,
        sandbox_provider: Any = None,
    ) -> None:
        self._runs = run_repository
        self._tasks = task_repository
        self._sandbox_sessions = sandbox_repository
        self._sandbox = sandbox_provider

    def create_for_run(
        self,
        run: AgentRun,
        *,
        request_fingerprint: str | None = None,
        user_message: str | None = None,
    ) -> Task:
        """为一次 Run 创建挂靠的 ``agent.run`` 任务并反向关联。

        - ``INLINE``：``CREATED → RUNNING``（``start_inline()``，跳过 ``PENDING``）；
        - ``QUEUED``：``CREATED → PENDING``（``enqueue()``）。

        同时把 ``task_id`` 回写 ``agent_run.task_id``。

        Args:
            run: 待挂靠的 Run。
            request_fingerprint: 可选的请求指纹（sha256 hex，W6 幂等「同键同体」判定，
                §2.13.1 / A28）。提供时写入 ``task.payload["request_fingerprint"]``；
                **缺省不改既有行为（向后兼容）**。
            user_message: 可选的用户输入（W6 / T1-28：供执行时 ``RunContext.user_message``
                取用；**缺省不改既有行为**）。
        """
        payload: dict[str, Any] = {
            "run_id": run.id,
            "agent_id": run.agent_id,
            "conversation_id": run.conversation_id,
        }
        if request_fingerprint is not None:
            payload["request_fingerprint"] = request_fingerprint
        if user_message is not None:
            payload["user_message"] = user_message
        task = Task(
            tenant_id=run.tenant_id,
            workspace_id=None,
            type=AGENT_RUN_TASK_TYPE,
            execution_mode=run.run_mode,
            payload=payload,
        )
        if run.run_mode == RUN_MODE_INLINE:
            task.start_inline()
        else:
            task.enqueue()
        task = self._tasks.add(task)
        run.task_id = task.task_id
        self._runs.update(run)
        return task

    def mark_running(self, task: Task) -> Task:
        """QUEUED 路径：``PENDING → RUNNING``。"""
        task.start()
        return self._tasks.update(task)

    def finish(
        self,
        run: AgentRun,
        run_status: str,
        *,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Task | None:
        """把挂靠任务的终态同步为 Run 的终态。

        终态语义恒定：``SUCCESS→succeed``、``FAILED→fail``、``CANCELLED→cancel``。

        ⚠️ **``error`` 不落 ``task``**（台账 A24）：``task`` 表**无** ``error`` 列，
        故此处**不再**把 ``error`` 写入 ``Task``（避免被静默丢弃的无效写入）。
        ``error`` 由 Run 层承载并落 ``agent_run.error``（见 :meth:`recover_stale_runs`）；
        形参保留仅为**向后兼容**既有调用方签名（``recover_stale_runs`` /
        ``AgentRunService._sync_task_terminal``）。

        Args:
            run: 已终态的 Run（须已 ``create_for_run`` 关联 ``task_id``）。
            run_status: Run 终态之一（``SUCCESS`` / ``FAILED`` / ``CANCELLED``）。
            error: 失败原因（**仅**由调用方 / ``agent_run`` 承载；不写入 ``Task``）。
            result: 结果（``SUCCESS`` 时写入）。

        Returns:
            更新后的 Task；若未关联任务则返回 ``None``。
        """
        if run.task_id is None:
            return None
        task = self._tasks.get(run.task_id)
        if task is None:
            return None
        self._apply_terminal(task, run_status, result=result)
        return self._tasks.update(task)

    def get_for_run(self, run: AgentRun) -> Task | None:
        """按 ``run.task_id`` 获取挂靠任务。"""
        if run.task_id is None:
            return None
        return self._tasks.get(run.task_id)

    def recover_stale_runs(self, threshold_ms: int, *, now: Any = None) -> list[AgentRun]:
        """重启兜底扫描：把心跳超期的 ``RUNNING`` Run 置 ``FAILED`` 并回收其沙箱。

        扫描 ``status=RUNNING`` 且 ``last_heartbeat_at`` 早于 ``now - threshold_ms``
        （或 ``last_heartbeat_at`` 为空且 ``started_at`` 早于阈值）的 Run（W6 / T1-31）：

        1. 置 ``status=FAILED`` / ``error_type="HEARTBEAT_TIMEOUT"`` / ``error`` /
           ``completed_at`` / ``success=False``；
        2. 经 :meth:`finish` 同步挂靠 ``task.status=FAILED``；
        3. 强制销毁关联 ``sandbox_session``（幂等）并置 ``status=STOPPED``。

        Args:
            threshold_ms: 超期阈值（毫秒；取 ``Settings.run_timeout_ms``）。
            now: 参照当前时刻（缺省取当前 UTC 时间；供测试注入）。

        Returns:
            被置败的 Run 列表（无超期者返回空列表）。
        """
        reference = now if now is not None else utcnow()
        threshold = reference - timedelta(milliseconds=int(threshold_ms))
        stale = self._runs.list_stale_running(threshold)
        recovered: list[AgentRun] = []
        for run in stale:
            run.status = RUN_STATUS_FAILED
            run.success = False
            run.error_type = HEARTBEAT_TIMEOUT_ERROR_TYPE
            run.error = "heartbeat timeout"
            run.completed_at = reference
            updated = self._runs.update(run)
            self.finish(updated, RUN_STATUS_FAILED, error="heartbeat timeout")
            self._destroy_sandboxes(updated.id)
            recovered.append(updated)
        return recovered

    def _destroy_sandboxes(self, run_id: str) -> int:
        """销毁某 Run 关联的全部沙箱会话（幂等；无仓储时返回 ``0``）。"""
        if self._sandbox_sessions is None:
            return 0
        destroyed = 0
        for session in self._sandbox_sessions.list_by_run(run_id):
            if self._sandbox is not None:
                try:
                    self._sandbox.destroy(session)
                except Exception:  # noqa: BLE001 - 回收幂等，失败不阻断兜底
                    pass
            session.status = SANDBOX_SESSION_STATUS_STOPPED
            self._sandbox_sessions.update(session)
            destroyed += 1
        return destroyed

    @staticmethod
    def _apply_terminal(
        task: Task,
        run_status: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        """按 Run 终态驱动 Task 终态（非法值 → ``DomainError``）。

        ⚠️ ``FAILED`` 仅置 ````task.status=FAILED`（``task.fail``），**不写 ``error``**
        （``task`` 表无 ``error`` 列，台账 A24；``error`` 落 ``agent_run``）。
        """
        target = _RUN_TO_TASK_STATUS.get(run_status)
        if target == "SUCCESS":
            task.succeed(result)
        elif target == "FAILED":
            task.fail(result=result)
        elif target == "CANCELLED":
            task.cancel()
        else:
            from astra_core import DomainError, ErrorCode

            raise DomainError(
                f"Run 状态无对应 Task 终态：{run_status}",
                code=ErrorCode.VALIDATION_ERROR,
                data={"run_status": run_status},
            )
