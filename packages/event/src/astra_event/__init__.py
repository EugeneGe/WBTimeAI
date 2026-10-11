"""Astra AI 事件总线（``astra_event``）。

- ``base``：``EventBus`` Protocol + 处理器类型别名（**不定义事件基类**）
- ``handler``：``EventHandler`` Protocol + ``FunctionHandler`` + ``handler_for``
- ``dispatcher``：``EventDispatcher``（匹配 / 分发 / 异常隔离）
- ``bus``：``LocalEventBus``（进程内）
- ``placeholder``：``UnsupportedEventBus``（server 占位）
- ``events``：Phase 0 事件（继承 ``astra_core.DomainEvent``）
- ``factory``：``create_local_event_bus()``（模式无关）
"""

from __future__ import annotations

from .base import AsyncHandler, EventBus, HandlerFn, SyncHandler
from .bus import LocalEventBus
from .dispatcher import EventDispatcher
from .events import (
    AgentCompleted,
    AgentFailed,
    AgentMessage,
    AgentStarted,
    AgentThinking,
    ApprovalDecided,
    ApprovalRequested,
    DefaultTenantInitialized,
    KnowledgeIndexed,
    MCPCallCompleted,
    MCPCallStarted,
    MemoryWritten,
    SkillResolved,
    SystemShutdown,
    SystemStarted,
    ToolCallCompleted,
    ToolCallStarted,
    UserLoggedIn,
    UserLoggedOut,
    UserRegistered,
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowNodeCompleted,
    WorkflowNodeStarted,
    WorkflowStarted,
    WorkspaceCreated,
    WorkspaceUpdated,
)
from .factory import create_local_event_bus
from .handler import EventHandler, FunctionHandler, get_event_type, handler_for
from .placeholder import UnsupportedEventBus

__all__ = [
    "EventBus",
    "SyncHandler",
    "AsyncHandler",
    "HandlerFn",
    "EventHandler",
    "FunctionHandler",
    "handler_for",
    "get_event_type",
    "EventDispatcher",
    "LocalEventBus",
    "UnsupportedEventBus",
    "create_local_event_bus",
    # events
    "UserRegistered",
    "UserLoggedIn",
    "UserLoggedOut",
    "WorkspaceCreated",
    "WorkspaceUpdated",
    "SystemStarted",
    "SystemShutdown",
    "DefaultTenantInitialized",
    # Phase 1 · Agent 生命周期事件（W5 / T1-21）
    "AgentStarted",
    "AgentThinking",
    "ToolCallStarted",
    "ToolCallCompleted",
    "MCPCallStarted",
    "MCPCallCompleted",
    "AgentMessage",
    "AgentCompleted",
    "AgentFailed",
    # Phase 2 · W3 / T2-16 新增领域事件（设计 §2.11）
    "SkillResolved",
    "WorkflowStarted",
    "WorkflowNodeStarted",
    "WorkflowNodeCompleted",
    "WorkflowCompleted",
    "WorkflowFailed",
    "KnowledgeIndexed",
    "MemoryWritten",
    "ApprovalRequested",
    "ApprovalDecided",
]
