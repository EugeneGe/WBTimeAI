"""ORM 模型汇总导入。

**必须**在此导入所有模型模块，以确保 ``Base.metadata`` 完整——
供 Alembic autogenerate 与 :func:`migrations.env` 使用。
"""

from __future__ import annotations

from ..base import Base
from .agent import Agent, AgentTool, AgentVersion
from .approval import Approval
from .audit import AuditLog
from .auth import LoginAttempt, RefreshToken, UserSession
from .conversation import AgentEvent, AgentRun, Conversation, Message, ToolCall
from .credential import Credential, ModelProviderCredential
from .evaluation import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from .feature_flag import FeatureFlag
from .identity import (
    Membership,
    Organization,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
)
from .knowledge import (
    AgentKnowledge,
    Document,
    DocumentChunk,
    Embedding,
    KnowledgeBase,
)
from .mcp import McpPermission, McpServer, McpTool
from .memory import Memory, MemoryRelation
from .model import Model, ModelProvider
from .permission import ResourcePermission
from .plugin import Plugin
from .project import Project, WorkspaceEnvironment
from .sandbox import SandboxSession
from .skill import AgentSkill, Skill, SkillResource, SkillVersion
from .task import Task
from .task_ext import Schedule, TaskExecution
from .tool import Tool, ToolPermission, ToolVersion
from .workflow import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowVersion,
)
from .workspace import Workspace

__all__ = [
    "Base",
    # identity
    "Tenant",
    "User",
    "Organization",
    "Membership",
    "Role",
    "Permission",
    "RolePermission",
    # auth
    "UserSession",
    "RefreshToken",
    "LoginAttempt",
    # workspace / task / credential
    "Workspace",
    "Task",
    "Credential",
    # Phase 2 · 多凭证关联（W3 / T2-15；迁移 0011）
    "ModelProviderCredential",
    # feature flag（T0-21 · 全局表）
    "FeatureFlag",
    # Phase 1 · Agent 组（T1-07）
    "Agent",
    "AgentVersion",
    "AgentTool",
    # Phase 1 · Model 组（T1-07）
    "ModelProvider",
    "Model",
    # Phase 1 · Tool 组（T1-07）
    "Tool",
    "ToolVersion",
    "ToolPermission",
    # Phase 2 · Skill 组（W2 / T2-07）
    "Skill",
    "SkillVersion",
    "SkillResource",
    "AgentSkill",
    # Phase 2 · MCP 组（W2 / T2-10）
    "McpServer",
    "McpTool",
    "McpPermission",
    # Phase 1 · Conversation 组（T1-07）
    "Conversation",
    "Message",
    "AgentRun",
    "ToolCall",
    "AgentEvent",
    # Phase 1 · Sandbox（T1-07）
    "SandboxSession",
    # Phase 1 · 审计（T1-07 / T1-09）
    "AuditLog",
    # Phase 2 · Plugin（W1b / T2-05；表随迁移 0010 落地，W3 / T2-13 登记）
    "Plugin",
    # Phase 2 · Resource Permission（W3 / T2-13；迁移 0010）
    "ResourcePermission",
    # Phase 2 · Approval（W3 / T2-13；表随 0010 建于 2a，接线归 2b）
    "Approval",
    # Phase 2 · Workflow 组（W4 / T2-20；迁移 0012；approval 不计本组）
    "Workflow",
    "WorkflowVersion",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowRun",
    "WorkflowNodeRun",
    # Phase 2 · Knowledge 组（W5 / T2-27；迁移 0013）
    "KnowledgeBase",
    "Document",
    "DocumentChunk",
    "Embedding",
    "AgentKnowledge",
    # Phase 2 · Memory 组（W6 / T2-32；迁移 0014）
    "Memory",
    "MemoryRelation",
    # Phase 2 · Workspace 增强 / Task 扩展（W7 / T2-37；迁移 0015）
    "Project",
    "WorkspaceEnvironment",
    "TaskExecution",
    "Schedule",
    # Phase 2 · Evaluation 组（W9 / T2-45；迁移 0017）
    "EvaluationDataset",
    "EvaluationCase",
    "EvaluationRun",
    "EvaluationResult",
]
