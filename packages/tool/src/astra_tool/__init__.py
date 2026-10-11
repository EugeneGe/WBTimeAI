"""Astra AI Tool 系统（``astra_tool``，设计 §2.5）。

- 统一接口：:class:`Tool` Protocol + :class:`ToolSpec` + :class:`ToolResult`（``base``）；
- 注册表：:class:`ToolRegistry`（``registry``，同构 ``ModelRegistry``）；
- 上下文：:class:`ToolContext`（``context``，注入 ``SandboxProvider`` 句柄）；
- 首批 5 Tool：``filesystem`` / ``shell`` / ``git`` / ``http`` / ``python``（``tools``）；
- 权限：:class:`PermissionChecker`（纯逻辑）+ PEP/PDP 挂点（``permission_checker``）、
  :class:`PermissionService`（DI 领域服务，``services``）；
- 安全：``security``（路径逃逸 / SSRF / 危险命令，纯逻辑）；
- 装配：:func:`build_tool_registry` / :func:`build_tool_services`（``factory``）。

🔴 ``astra_tool`` 属**抽象包**：零 ORM、零 ``astra_database`` 导入（分层纪律）。
"""

from __future__ import annotations

from .base import (
    TOOL_RESOURCE,
    BaseTool,
    Tool,
    ToolMetadata,
    ToolPermissionRequirement,
    ToolResult,
    ToolSpec,
)
from .context import ToolContext
from .errors import ToolErrorCode
from .factory import build_tool_registry, build_tool_services
from .permission_checker import (
    NoopPolicyDecisionPoint,
    NoopPolicyEnforcementPoint,
    PermissionChecker,
    PermissionRequest,
    PolicyDecisionPoint,
    PolicyEnforcementPoint,
)
from .permissions import (
    TOOL_PERMISSION_MATRIX,
    default_permission,
    permission_code,
    resolve_permission_scope,
    tool_actions,
)
from .registry import ToolRegistry
from .services import PermissionService
from .tools import (
    BUILTIN_TOOL_CLASSES,
    FilesystemTool,
    GitTool,
    HttpTool,
    PythonTool,
    ShellTool,
    register_builtin_tools,
)

__all__ = [
    # 接口 / DTO
    "Tool",
    "BaseTool",
    "ToolMetadata",
    "ToolPermissionRequirement",
    "ToolSpec",
    "ToolResult",
    "TOOL_RESOURCE",
    # 注册表 / 上下文
    "ToolRegistry",
    "ToolContext",
    # 权限
    "PermissionChecker",
    "PermissionRequest",
    "PolicyEnforcementPoint",
    "PolicyDecisionPoint",
    "NoopPolicyEnforcementPoint",
    "NoopPolicyDecisionPoint",
    "PermissionService",
    "ToolErrorCode",
    # 权限定义
    "TOOL_PERMISSION_MATRIX",
    "permission_code",
    "default_permission",
    "tool_actions",
    "resolve_permission_scope",
    # 首批工具
    "FilesystemTool",
    "ShellTool",
    "GitTool",
    "HttpTool",
    "PythonTool",
    "BUILTIN_TOOL_CLASSES",
    "register_builtin_tools",
    # 装配
    "build_tool_registry",
    "build_tool_services",
]
