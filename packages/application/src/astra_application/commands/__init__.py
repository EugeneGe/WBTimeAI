"""命令子包导出。"""

from __future__ import annotations

from .agent import (
    CreateAgentCommand,
    CreateAgentHandler,
    PublishAgentVersionCommand,
    PublishAgentVersionHandler,
    UpdateAgentCommand,
    UpdateAgentHandler,
)
from .auth import (
    LoginUserCommand,
    LoginUserHandler,
    LogoutUserCommand,
    LogoutUserHandler,
    RefreshTokenCommand,
    RefreshTokenHandler,
    RegisterUserCommand,
    RegisterUserHandler,
)
from .base import Command, CommandHandler
from .bootstrap_tenant import (
    BootstrapDefaultTenantCommand,
    BootstrapDefaultTenantHandler,
    BootstrapResultDTO,
)
from .run import (
    CancelAgentRunCommand,
    CancelAgentRunHandler,
    CreateAgentTaskCommand,
    CreateAgentTaskHandler,
    ExecuteAgentCommand,
    ExecuteAgentHandler,
)
from .workspace import (
    CreateWorkspaceCommand,
    CreateWorkspaceHandler,
    UpdateWorkspaceSettingsCommand,
    UpdateWorkspaceSettingsHandler,
)

__all__ = [
    "Command",
    "CommandHandler",
    "BootstrapDefaultTenantCommand",
    "BootstrapDefaultTenantHandler",
    "BootstrapResultDTO",
    # auth
    "RegisterUserCommand",
    "RegisterUserHandler",
    "LoginUserCommand",
    "LoginUserHandler",
    "LogoutUserCommand",
    "LogoutUserHandler",
    "RefreshTokenCommand",
    "RefreshTokenHandler",
    # workspace
    "CreateWorkspaceCommand",
    "CreateWorkspaceHandler",
    "UpdateWorkspaceSettingsCommand",
    "UpdateWorkspaceSettingsHandler",
    # agent / run（W6 / T1-27）
    "CreateAgentCommand",
    "CreateAgentHandler",
    "UpdateAgentCommand",
    "UpdateAgentHandler",
    "PublishAgentVersionCommand",
    "PublishAgentVersionHandler",
    "CreateAgentTaskCommand",
    "CreateAgentTaskHandler",
    "ExecuteAgentCommand",
    "ExecuteAgentHandler",
    "CancelAgentRunCommand",
    "CancelAgentRunHandler",
]
