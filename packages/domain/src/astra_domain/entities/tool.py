"""Tool 组领域实体（设计 §2.15.1 Tool 组 / §2.5）。

纯 dataclass，零框架依赖（C-03）。

- :class:`Tool`：工具目录（``tenant_id`` 为 ``None`` 表示全局内置工具）；
- :class:`ToolVersion`：工具规格快照；
- :class:`ToolPermission`：Tool 权限（``ToolEffect``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import (
    TOOL_ACTION_EXECUTE,
    TOOL_EFFECT_ALLOW,
    TOOL_SOURCE_BUILTIN,
)
from .base import AggregateRoot

__all__ = ["Tool", "ToolVersion", "ToolPermission"]


@dataclass
class Tool(AggregateRoot):
    """工具目录.

    Attributes:
        name: 工具名（如 ``filesystem``）。
        display_name: 展示名。
        description: 描述（可空）。
        category: 分类。
        source: 来源（``builtin`` / ``plugin`` / ``mcp``）。
        input_schema: 入参 JSON Schema。
        output_schema: 出参 JSON Schema。
        requires_sandbox: 是否须经 Sandbox 执行。
        status: 状态。
        tool_ref: 工具引用（JSON 结构；MCP Tool 溯源 ``{kind,id,server_id,name,version}``，
            内置 Tool 为空 ``{}``）——W2 / T2-10（R9.2）。
    """

    name: str = ""
    display_name: str = ""
    description: str | None = None
    category: str = ""
    source: str = TOOL_SOURCE_BUILTIN
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    requires_sandbox: bool = False
    status: str = ""
    tool_ref: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolVersion(AggregateRoot):
    """工具规格快照.

    Attributes:
        tool_id: 所属工具标识。
        version: 版本号。
        spec: 规格（JSON 结构）。
    """

    tool_id: str = ""
    version: str = ""
    spec: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolPermission(AggregateRoot):
    """Tool 权限（ALLOW / DENY；``APPROVAL`` 预留）.

    Attributes:
        agent_id: 关联 Agent 标识（可空）。
        agent_version_id: 关联 AgentVersion 标识（可空）。
        tool_id: 工具标识。
        action: 动作（``ToolAction`` 字面值）。
        effect: 效果（``ToolEffect`` 字面值）。
        scope: 权限 scope（JSON 结构）。
    """

    agent_id: str | None = None
    agent_version_id: str | None = None
    tool_id: str = ""
    action: str = TOOL_ACTION_EXECUTE
    effect: str = TOOL_EFFECT_ALLOW
    scope: dict[str, Any] = field(default_factory=dict)
