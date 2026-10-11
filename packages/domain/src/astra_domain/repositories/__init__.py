"""仓储接口汇总导出（**仅 Protocol**，零 ORM 依赖）。"""

from __future__ import annotations

from .agent_repository import (
    AgentRepository,
    AgentSkillRepository,
    AgentToolRepository,
    AgentVersionRepository,
)
from .approval_repository import ApprovalRepository
from .audit_repository import AuditRepository
from .auth import (
    LoginAttemptRecord,
    LoginAttemptRepository,
    RefreshTokenRecord,
    RefreshTokenRepository,
    SessionRecord,
    SessionRepository,
)
from .base import Repository
from .conversation_repository import (
    AgentEventRepository,
    AgentRunRepository,
    ConversationRepository,
    MessageRepository,
    ToolCallRepository,
)
from .credential_repository import (
    CredentialRecord,
    CredentialRepository,
    ModelProviderCredentialRecord,
)
from .membership_repository import MembershipRepository
from .model_repository import ModelProviderRepository, ModelRepository
from .organization_repository import OrganizationRepository
from .permission_repository import ResourcePermissionRepository
from .plugin_repository import (
    PLUGIN_STATUS_INSTALLED,
    PLUGIN_STATUS_UNINSTALLED,
    PluginRecord,
    PluginRepository,
)
from .role_repository import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
)
from .sandbox_repository import SandboxSessionRepository
from .task_repository import ScheduleRepository, TaskExecutionRepository, TaskRepository
from .tenant_repository import TenantRepository
from .tool_repository import (
    ToolPermissionRepository,
    ToolRepository,
    ToolVersionRepository,
)
from .user_repository import UserRepository
from .workspace_repository import WorkspaceRepository

__all__ = [
    "Repository",
    "TenantRepository",
    "UserRepository",
    "OrganizationRepository",
    "MembershipRepository",
    "RoleRepository",
    "PermissionRepository",
    "RolePermissionRepository",
    # auth
    "SessionRepository",
    "RefreshTokenRepository",
    "LoginAttemptRepository",
    "SessionRecord",
    "RefreshTokenRecord",
    "LoginAttemptRecord",
    # workspace / credential
    "WorkspaceRepository",
    "CredentialRepository",
    "CredentialRecord",
    "ModelProviderCredentialRecord",
    "PluginRepository",
    "PluginRecord",
    "PLUGIN_STATUS_INSTALLED",
    "PLUGIN_STATUS_UNINSTALLED",
    # Phase 1 · Agent 组
    "AgentRepository",
    "AgentVersionRepository",
    "AgentToolRepository",
    # Phase 2 · Skill 绑定（W2 / T2-07）
    "AgentSkillRepository",
    # Phase 1 · Model 组
    "ModelProviderRepository",
    "ModelRepository",
    # Phase 1 · Tool 组
    "ToolRepository",
    "ToolVersionRepository",
    "ToolPermissionRepository",
    # Phase 1 · Conversation 组
    "ConversationRepository",
    "MessageRepository",
    "AgentRunRepository",
    "ToolCallRepository",
    "AgentEventRepository",
    # Phase 1 · Sandbox
    "SandboxSessionRepository",
    # Phase 1 · 审计
    "AuditRepository",
    # Phase 1 · Task 持久化（W5 / T1-26）
    "TaskRepository",
    # Phase 2 · 调度增强（W7 / T2-39）
    "TaskExecutionRepository",
    "ScheduleRepository",
    # Phase 2 · Resource Permission（W3 / T2-13）
    "ResourcePermissionRepository",
    # Phase 2 · Approval（W4 / T2-26，零迁移；表随 0010）
    "ApprovalRepository",
]
