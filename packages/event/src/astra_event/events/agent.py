"""Agent 生命周期事件（Phase 1 · W5 / T1-21；设计 §2.8 / §3-#8）。

9 类事件**全部继承** :class:`astra_core.events.DomainEvent`（事件基类唯一，C-02），
携带 ``ClassVar type``（类型字符串）与 ``ClassVar.create()``（便捷构造）。

类型字符串（与设计 §2.8 表格逐字一致，``I-P1-08``）：

- ``agent.started`` / ``agent.thinking`` / ``agent.message`` /
  ``agent.completed`` / ``agent.failed``（5 类，Phase 1 产出）；
- ``tool_call.started`` / ``tool_call.completed``（2 类，Phase 1 产出）；
- ``mcp_call.started`` / ``mcp_call.completed``（2 类，**定义但不产出**，§5 #14）。

🔴 本模块**只定义事件类型**，`EventBus` Protocol 保持不变；「落 ``agent_event``」由
   Runtime 的 ``EventDispatcher``（DI 注入 ``AgentEventRepository``）负责——**不在 event 包**。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = [
    "AgentStarted",
    "AgentThinking",
    "ToolCallStarted",
    "ToolCallCompleted",
    "MCPCallStarted",
    "MCPCallCompleted",
    "AgentMessage",
    "AgentCompleted",
    "AgentFailed",
]


@dataclass
class AgentStarted(DomainEvent):
    """Agent 开始执行事件（``agent.started``）。"""

    type: ClassVar[str] = "agent.started"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        agent_id: str,
        agent_version_id: str | None = None,
        conversation_id: str | None = None,
        run_mode: str | None = None,
    ) -> AgentStarted:
        """便捷构造。"""
        payload: dict[str, Any] = {"run_id": run_id, "agent_id": agent_id}
        if agent_version_id is not None:
            payload["agent_version_id"] = agent_version_id
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        if run_mode is not None:
            payload["run_mode"] = run_mode
        return cls(payload=payload)


@dataclass
class AgentThinking(DomainEvent):
    """Agent 思考中事件（``agent.thinking``，迭代开始）。"""

    type: ClassVar[str] = "agent.thinking"

    @classmethod
    def create(cls, *, run_id: str, iteration: int) -> AgentThinking:
        """便捷构造。"""
        return cls(payload={"run_id": run_id, "iteration": iteration})


@dataclass
class ToolCallStarted(DomainEvent):
    """工具调用开始事件（``tool_call.started``）。"""

    type: ClassVar[str] = "tool_call.started"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        attempt: int = 1,
        arguments: dict[str, Any] | None = None,
    ) -> ToolCallStarted:
        """便捷构造。"""
        payload: dict[str, Any] = {
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "attempt": attempt,
        }
        if arguments is not None:
            payload["arguments"] = dict(arguments)
        return cls(payload=payload)


@dataclass
class ToolCallCompleted(DomainEvent):
    """工具调用完成事件（``tool_call.completed``）。"""

    type: ClassVar[str] = "tool_call.completed"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        status: str,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> ToolCallCompleted:
        """便捷构造。"""
        payload: dict[str, Any] = {
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": status,
        }
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if error is not None:
            payload["error"] = error
        return cls(payload=payload)


@dataclass
class MCPCallStarted(DomainEvent):
    """MCP 调用开始事件（``mcp_call.started``；**定义但不产出**，§5 #14）。"""

    type: ClassVar[str] = "mcp_call.started"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        mcp_call_id: str,
        server: str,
        tool_name: str | None = None,
    ) -> MCPCallStarted:
        """便捷构造。"""
        payload: dict[str, Any] = {
            "run_id": run_id,
            "mcp_call_id": mcp_call_id,
            "server": server,
        }
        if tool_name is not None:
            payload["tool_name"] = tool_name
        return cls(payload=payload)


@dataclass
class MCPCallCompleted(DomainEvent):
    """MCP 调用完成事件（``mcp_call.completed``；**定义但不产出**，§5 #14）。"""

    type: ClassVar[str] = "mcp_call.completed"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        mcp_call_id: str,
        server: str,
        status: str,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> MCPCallCompleted:
        """便捷构造。"""
        payload: dict[str, Any] = {
            "run_id": run_id,
            "mcp_call_id": mcp_call_id,
            "server": server,
            "status": status,
        }
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if error is not None:
            payload["error"] = error
        return cls(payload=payload)


@dataclass
class AgentMessage(DomainEvent):
    """Agent 产出消息事件（``agent.message``）。"""

    type: ClassVar[str] = "agent.message"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        message_id: str,
        role: str,
        content: str | None = None,
    ) -> AgentMessage:
        """便捷构造。"""
        payload: dict[str, Any] = {"run_id": run_id, "message_id": message_id, "role": role}
        if content is not None:
            payload["content"] = content
        return cls(payload=payload)


@dataclass
class AgentCompleted(DomainEvent):
    """Agent 成功结束事件（``agent.completed``）。"""

    type: ClassVar[str] = "agent.completed"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        duration_ms: int | None = None,
        iterations: int | None = None,
    ) -> AgentCompleted:
        """便捷构造。"""
        payload: dict[str, Any] = {"run_id": run_id}
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if iterations is not None:
            payload["iterations"] = iterations
        return cls(payload=payload)


@dataclass
class AgentFailed(DomainEvent):
    """Agent 失败结束事件（``agent.failed``）。"""

    type: ClassVar[str] = "agent.failed"

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        error_type: str,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> AgentFailed:
        """便捷构造。"""
        payload: dict[str, Any] = {"run_id": run_id, "error_type": error_type}
        if error is not None:
            payload["error"] = error
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return cls(payload=payload)
