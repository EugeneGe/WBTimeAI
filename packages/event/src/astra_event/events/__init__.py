"""Phase 0/1/2 事件汇总导出。

具体事件**继承** :class:`astra_core.events.DomainEvent`；本模块仅聚合导出。

Phase 2 · W3 / T2-16 新增 5 模块（``skill`` / ``workflow`` / ``knowledge`` / ``memory`` /
``approval``）；``MCPCall*`` 仍在 ``agent.py``（**不新建** ``events/mcp.py``，Errata-B）。
"""

from __future__ import annotations

from .agent import (
    AgentCompleted,
    AgentFailed,
    AgentMessage,
    AgentStarted,
    AgentThinking,
    MCPCallCompleted,
    MCPCallStarted,
    ToolCallCompleted,
    ToolCallStarted,
)
from .approval import ApprovalDecided, ApprovalRequested
from .knowledge import KnowledgeIndexed
from .memory import MemoryWritten
from .skill import SkillResolved
from .system import DefaultTenantInitialized, SystemShutdown, SystemStarted
from .user import UserLoggedIn, UserLoggedOut, UserRegistered
from .workflow import (
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowNodeCompleted,
    WorkflowNodeStarted,
    WorkflowStarted,
)
from .workspace import WorkspaceCreated, WorkspaceUpdated

__all__ = [
    "UserRegistered",
    "UserLoggedIn",
    "UserLoggedOut",
    "WorkspaceCreated",
    "WorkspaceUpdated",
    "SystemStarted",
    "SystemShutdown",
    "DefaultTenantInitialized",
    # Phase 1 · Agent 生命周期事件（W5 / T1-21，9 类）
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
