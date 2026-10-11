"""Tool schema（工具目录 / 权限，W6 / T1-29）。

工具视图来自 ``astra_tool.ToolRegistry``（``spec.metadata``）；权限视图来自
``astra_tool.PermissionService``（agent × tool × effect × scope）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "ToolResponse",
    "ToolPermissionRequest",
    "ToolPermissionResponse",
]


class ToolResponse(BaseModel):
    """工具目录项响应（内置工具浏览器）。"""

    id: str | None = None
    name: str
    display_name: str = ""
    description: str = ""
    category: str = ""
    type: str = "builtin"
    requires_sandbox: bool = False
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolPermissionRequest(BaseModel):
    """授予 / 更新一条 Tool 权限请求（agent × tool × effect × scope）。"""

    tool_id: str = Field(min_length=1)
    action: str = Field(default="EXECUTE", max_length=30)
    effect: str = Field(default="ALLOW", max_length=30)
    scope: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = None
    agent_version_id: str | None = None


class ToolPermissionResponse(BaseModel):
    """Tool 权限响应。"""

    id: str
    tenant_id: str | None = None
    agent_id: str | None = None
    agent_version_id: str | None = None
    tool_id: str
    action: str = "EXECUTE"
    effect: str = "ALLOW"
    scope: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
