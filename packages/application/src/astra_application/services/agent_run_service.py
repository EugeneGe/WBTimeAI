"""``AgentRunService``——Agent / Run 用例编排器（W6 / T1-27；设计 §2.2 / §2.6 / §2.9）。

**应用/用例层（第三类）**：编排「Domain 校验 + 能力包服务 + Runtime 执行 + 持久化副作用」，
**不**承载实体持久化、**不**提供被 Runtime 消费的 Protocol、**零** Web / ORM
（Q1 §1.3；``test_application_import_boundary`` 强制）。

职责：

- :meth:`open_run`：先建 ``AgentRun(status=RUNNING)``（有并发约束时经 ``add_guarded``）→
  调 ``RunService.create_for_run`` 建 ``agent.run`` 挂靠任务（**断连取消方有 task 可同步**），
  返回 ``RunDTO``；**不执行**。
- :meth:`execute`：加载明确 ``AgentVersion`` → 组 ``RunContext(run=..., should_cancel=...)``
  → ``runtime.run(ctx)``（阻塞）→ 同步挂靠 ``task`` 终态。
- :meth:`cancel`：置取消信号（非阻塞）+ 置 ``CANCELLED`` 终态 + 同步 ``task`` + 回收沙箱。

Runtime 由 Application 调用（Router 不感知 Runtime，§2.2）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from astra_agent import AgentService
from astra_common.time import utcnow
from astra_conversation import RunService
from astra_core import DomainError, ErrorCode
from astra_domain import (
    RUN_MODE_INLINE,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_USER,
    SANDBOX_SESSION_STATUS_STOPPED,
    AgentEventRepository,
    AgentRun,
    AgentRunRepository,
    RunStatus,
    SandboxSessionRepository,
)
from astra_runtime import AgentRuntime, RunContext, RunResult, RuntimePermissionChecker

from ..dto.run import RunDTO, RunEventDTO
from .base import ApplicationService

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期（避免 commands ↔ services 循环导入）
    from ..commands.run import CreateAgentTaskCommand

__all__ = ["AgentRunService", "CANCELLED_ERROR_TYPE"]

#: 取消态 ``error_type``（复用 ``agent.error`` 通道，Q-note-2）。
CANCELLED_ERROR_TYPE = "CANCELLED"


class AgentRunService(ApplicationService):
    """Agent Run 用例编排器（DI 注入 Runtime + 能力包服务 + 领域 Protocol）。"""

    agents: AgentService
    runs: AgentRunRepository
    runtime: AgentRuntime
    run_service: RunService | None
    concurrency: Any
    sandbox_sessions: SandboxSessionRepository | None
    sandbox_provider: Any
    events: AgentEventRepository | None
    permission_checker_resolver: Callable[[str], RuntimePermissionChecker] | None

    def __init__(
        self,
        *,
        agents: AgentService,
        runs: AgentRunRepository,
        runtime: AgentRuntime,
        run_service: RunService | None = None,
        concurrency: Any = None,
        sandbox_sessions: SandboxSessionRepository | None = None,
        sandbox_provider: Any = None,
        events: AgentEventRepository | None = None,
        permission_checker_resolver: Callable[[str], RuntimePermissionChecker] | None = None,
    ) -> None:
        super().__init__(
            agents=agents,
            runs=runs,
            runtime=runtime,
            run_service=run_service,
            concurrency=concurrency,
            sandbox_sessions=sandbox_sessions,
            sandbox_provider=sandbox_provider,
            events=events,
            permission_checker_resolver=permission_checker_resolver,
        )
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()

    # -- 建 Run（不执行） ---------------------------------------------------

    def open_run(self, command: CreateAgentTaskCommand) -> RunDTO:
        """建 ``AgentRun``（``RUNNING``）并挂靠 ``agent.run`` 任务；返回 DTO（**不执行**）。

        Args:
            command: 创建任务命令（含租户 / Agent / 会话 / 用户 / 输入 / 幂等键 / 指纹）。

        Returns:
            :class:`~astra_application.dto.run.RunDTO`（含 ``run_id``，``status=RUNNING``）。

        Raises:
            DomainError: Agent 不存在（``NOT_FOUND``）；并发超限（``CONFLICT``）。
        """
        agent = self.agents.get_agent(command.agent_id)
        if agent is None or agent.tenant_id != command.tenant_id:
            raise DomainError(
                "Agent 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"agent_id": command.agent_id},
            )
        run = AgentRun(
            tenant_id=command.tenant_id,
            agent_id=command.agent_id,
            agent_version_id=agent.current_version_id or "",
            conversation_id=command.conversation_id,
            user_id=command.user_id,
            trigger=command.trigger or RUN_TRIGGER_USER,
            run_mode=command.run_mode or RUN_MODE_INLINE,
            status=RUN_STATUS_RUNNING,
            trace_id=command.trace_id,
            idempotency_key=command.idempotency_key,
            started_at=utcnow(),
        )
        if self.concurrency is not None:
            run = self.concurrency.guard_run_creation(self.runs, run)
        else:
            run = self.runs.add(run)
        if self.run_service is not None:
            self.run_service.create_for_run(
                run,
                request_fingerprint=command.request_fingerprint,
                user_message=command.user_message,
            )
            run = self.runs.get(run.id) or run
        return RunDTO.from_entity(run)

    # -- 执行（阻塞至终态） -------------------------------------------------

    def execute(self, run_id: str) -> RunResult:
        """同步执行一次 Run 至终态，并同步挂靠 ``task`` 的终态。

        Args:
            run_id: 目标 Run 标识。

        Returns:
            :class:`~astra_runtime.RunResult`。

        Raises:
            DomainError: Run 不存在（``NOT_FOUND``）；Agent / 版本丢失（``NOT_FOUND``）；
                未配置模型（``CONFIGURATION_ERROR``，由 Runtime 抛出）。
        """
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                "Run 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"run_id": run_id},
            )
        agent = self.agents.get_agent(run.agent_id)
        if agent is None:
            raise DomainError(
                "Agent 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"agent_id": run.agent_id},
            )
        agent_version = self.agents.load_version(agent, run.agent_version_id or None)
        # W8 / A36：按 ``run.agent_id``（授权维度）per-run 解析授权 → 构造**独立**校验器
        # （不写回共享单例；resolver 未接线时置 ``None`` → 回退 ToolExecutor 装配期默认）。
        permission_checker = (
            self.permission_checker_resolver(run.agent_id)
            if self.permission_checker_resolver is not None
            else None
        )
        context = RunContext(
            conversation_id=run.conversation_id,
            agent_id=run.agent_id,
            agent_version=agent_version,
            tenant_id=run.tenant_id or "",
            user_id=run.user_id,
            user_message=self._user_message(run),
            run_mode=run.run_mode,
            trigger=run.trigger,
            idempotency_key=run.idempotency_key,
            trace_id=run.trace_id,
            run=run,
            should_cancel=self._cancel_probe(run.id),
            permission_checker=permission_checker,
        )
        result = self.runtime.run(context)
        self._sync_task_terminal(run.id, result.status, error=result.error_type)
        return result

    # -- 只读辅助（供 SSE / 事件端点，Router 不感知仓储） --------------------

    def get_run(self, run_id: str) -> RunDTO:
        """返回某 Run 的 DTO（不存在 → ``NOT_FOUND``）。"""
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                "Run 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"run_id": run_id},
            )
        return RunDTO.from_entity(run)

    def status(self, run_id: str) -> str | None:
        """返回某 Run 当前状态（不存在 → ``None``）。"""
        run = self.runs.get(run_id)
        return None if run is None else str(run.status)

    def list_events(self, run_id: str, last_event_id: int | None = None) -> list[RunEventDTO]:
        """返回 ``seq > last_event_id`` 的事件 DTO（``seq`` 升序，供回放 / 续传）。

        Args:
            run_id: 目标 Run 标识。
            last_event_id: 续传起点（``None`` = 从头）。

        Returns:
            :class:`~astra_application.dto.run.RunEventDTO` 列表。
        """
        if self.events is None:
            return []
        return [
            RunEventDTO.from_entity(event)
            for event in self.events.list_after_seq(run_id, last_event_id)
        ]

    # -- 取消 ---------------------------------------------------------------

    def cancel(self, run_id: str) -> RunDTO:
        """取消一次 Run：置取消信号 + 终态 ``CANCELLED`` + 同步 ``task`` + 回收沙箱。

        Args:
            run_id: 目标 Run 标识。

        Returns:
            取消后的 :class:`~astra_application.dto.run.RunDTO`。

        Raises:
            DomainError: Run 不存在（``NOT_FOUND``）。
        """
        self._cancel_event(run_id).set()
        run = self.runs.get(run_id)
        if run is None:
            raise DomainError(
                "Run 不存在",
                code=ErrorCode.NOT_FOUND,
                data={"run_id": run_id},
            )
        if run.status not in RunStatus.terminal_values():
            run.status = RUN_STATUS_CANCELLED
            run.success = False
            run.error_type = CANCELLED_ERROR_TYPE
            run.completed_at = utcnow()
            run = self.runs.update(run)
            if self.run_service is not None:
                self.run_service.finish(run, RUN_STATUS_CANCELLED)
            self._destroy_sandboxes(run_id)
        return RunDTO.from_entity(run)

    # -- 内部 ---------------------------------------------------------------

    def _cancel_event(self, run_id: str) -> threading.Event:
        """取得（必要时创建）某 Run 的取消事件。"""
        with self._cancel_lock:
            event = self._cancel_events.get(run_id)
            if event is None:
                event = threading.Event()
                self._cancel_events[run_id] = event
            return event

    def _cancel_probe(self, run_id: str) -> Callable[[], bool]:
        """返回「该 Run 是否已请求取消」的探针（供 ``RunContext.should_cancel``）。"""
        event = self._cancel_event(run_id)

        def probe() -> bool:
            return event.is_set()

        return probe

    def _user_message(self, run: AgentRun) -> str:
        """读取 ``open_run`` 时写入挂靠 ``task.payload["user_message"]`` 的用户输入。

        无 ``RunService`` / 无 task / 无 payload 时返回空串（Runtime 仍按 system prompt 执行）。
        """
        if self.run_service is None:
            return ""
        task = self.run_service.get_for_run(run)
        if task is None:
            return ""
        payload = getattr(task, "payload", None) or {}
        value = payload.get("user_message")
        return str(value) if value is not None else ""

    def _sync_task_terminal(self, run_id: str, run_status: str, *, error: str | None) -> None:
        """把挂靠 ``task`` 的终态同步为 Run 终态（无 ``RunService`` 时跳过）。"""
        if self.run_service is None:
            return
        latest = self.runs.get(run_id)
        if latest is None:
            return
        self.run_service.finish(latest, run_status, error=error)

    def _destroy_sandboxes(self, run_id: str) -> int:
        """销毁某 Run 关联的全部沙箱会话（幂等；无仓储时返回 ``0``）。"""
        if self.sandbox_sessions is None:
            return 0
        destroyed = 0
        for session in self.sandbox_sessions.list_by_run(run_id):
            if self.sandbox_provider is not None:
                try:
                    self.sandbox_provider.destroy(session)
                except Exception:  # noqa: BLE001 - 回收幂等，失败不阻断取消
                    pass
            session.status = SANDBOX_SESSION_STATUS_STOPPED
            self.sandbox_sessions.update(session)
            destroyed += 1
        return destroyed
