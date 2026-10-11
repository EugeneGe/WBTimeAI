"""领域实体汇总导出。"""

from __future__ import annotations

from .agent import Agent, AgentTool, AgentVersion
from .agent_skill import AgentSkill
from .audit import AuditLog
from .base import AggregateRoot, Entity
from .conversation import AgentEvent, AgentRun, Conversation, Message, ToolCall
from .membership import Membership
from .model import Model, ModelProvider
from .organization import Organization
from .permission import ResourcePermission
from .role import Permission, Role, RolePermission
from .sandbox import SandboxSession
from .tenant import Tenant
from .tool import Tool, ToolPermission, ToolVersion
from .user import User
from .workspace import Workspace

__all__ = [
    "Entity",
    "AggregateRoot",
    "Tenant",
    "User",
    "Organization",
    "Membership",
    "Role",
    "Permission",
    "RolePermission",
    "Workspace",
    # Phase 1 · Agent 组
    "Agent",
    "AgentVersion",
    "AgentTool",
    # Phase 2 · Skill 绑定（W2 / T2-07）
    "AgentSkill",
    # Phase 1 · Model 组
    "ModelProvider",
    "Model",
    # Phase 1 · Tool 组
    "Tool",
    "ToolVersion",
    "ToolPermission",
    # Phase 1 · Conversation 组
    "Conversation",
    "Message",
    "AgentRun",
    "ToolCall",
    "AgentEvent",
    # Phase 1 · Sandbox
    "SandboxSession",
    # Phase 1 · 审计
    "AuditLog",
    # Phase 2 · Resource Permission（W3 / T2-13）
    "ResourcePermission",
]
