"""Run 用例（Command / CommandHandler）——设计 §2.2 / §2.6 / §2.9。

命令：创建 Agent 任务（open_run：建 Run + task，**不执行**）/ 执行 Agent（
同步执行一次 Run，编排 Runtime + 事件/消息/工具调用持久化 + 结算）/ 取消 Agent Run。

处理器委托 :class:`~astra_application.services.agent_run_service.AgentRunService`。
Application **不感知** Web / ORM（C-03 / Q1）；Runtime 由 Application 调用（§2.2）。
"""

from __future__ import annotations

from dataclasses import dataclass

from astra_domain import RUN_MODE_INLINE, RUN_TRIGGER_USER
from astra_runtime import RunResult

from ..dto.run import RunDTO
from ..services.agent_run_service import AgentRunService
from .base import Command

__all__ = [
    "CreateAgentTaskCommand",
    "CreateAgentTaskHandler",
    "ExecuteAgentCommand",
    "ExecuteAgentHandler",
    "CancelAgentRunCommand",
    "CancelAgentRunHandler",
]


@dataclass
class CreateAgentTaskCommand(Command):
    """创建 Agent 任务命令（建 Run（``RUNNING``）+ 挂靠 ``task``，**不执行**）。"""

    tenant_id: str = ""
    agent_id: str = ""
    conversation_id: str = ""
    user_id: str | None = None
    user_message: str = ""
    workspace_id: str | None = None
    run_mode: str = RUN_MODE_INLINE
    trigger: str = RUN_TRIGGER_USER
    idempotency_key: str | None = None
    trace_id: str | None = None
    request_fingerprint: str | None = None


class CreateAgentTaskHandler:
    """创建 Agent 任务命令处理器。"""

    def __init__(self, agent_run_service: AgentRunService) -> None:
        self._service = agent_run_service

    def handle(self, command: CreateAgentTaskCommand) -> RunDTO:
        """建 Run + 挂靠 task 并返回 RunDTO（**不执行**）。"""
        return self._service.open_run(command)


@dataclass
class ExecuteAgentCommand(Command):
    """执行 Agent 命令（同步执行一次 Run 至终态）。"""

    run_id: str = ""


class ExecuteAgentHandler:
    """执行 Agent 命令处理器（阻塞至终态）。"""

    def __init__(self, agent_run_service: AgentRunService) -> None:
        self._service = agent_run_service

    def handle(self, command: ExecuteAgentCommand) -> RunResult:
        """同步执行 Run 并返回 :class:`~astra_runtime.RunResult`。"""
        return self._service.execute(command.run_id)


@dataclass
class CancelAgentRunCommand(Command):
    """取消 Agent Run 命令。"""

    run_id: str = ""
    tenant_id: str = ""


class CancelAgentRunHandler:
    """取消 Agent Run 命令处理器。"""

    def __init__(self, agent_run_service: AgentRunService) -> None:
        self._service = agent_run_service

    def handle(self, command: CancelAgentRunCommand) -> RunDTO:
        """置取消信号 + 终态 ``CANCELLED``（+ task 同步 + 沙箱回收），返回 RunDTO。"""
        return self._service.cancel(command.run_id)
