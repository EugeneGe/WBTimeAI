"""工作区 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CreateWorkspaceRequest",
    "UpdateWorkspaceSettingsRequest",
    "WorkspaceResponse",
]


class CreateWorkspaceRequest(BaseModel):
    """创建工作区请求。"""

    name: str = Field(min_length=1, max_length=255, description="工作区名称")
    workspace_type: str = Field(default="personal", description="personal | team")
    settings: dict[str, Any] = Field(default_factory=dict, description="初始设置（JSON）")
    config: dict[str, Any] = Field(default_factory=dict, description="初始配置（JSON）")


class UpdateWorkspaceSettingsRequest(BaseModel):
    """更新工作区设置请求。"""

    settings: dict[str, Any] = Field(default_factory=dict, description="设置（JSON）")


class WorkspaceResponse(BaseModel):
    """工作区响应。"""

    id: str
    tenant_id: str | None = None
    owner_id: str
    name: str
    workspace_type: str
    settings: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
