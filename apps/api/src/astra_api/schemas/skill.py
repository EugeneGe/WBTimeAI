"""Skill schema（W3 / T2-17；设计 §2.3 / §2.12）。

``/skills`` CRUD + 版本 / 发布 的请求 / 响应模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CreateSkillRequest",
    "UpdateSkillRequest",
    "CreateSkillVersionRequest",
    "SkillResponse",
    "SkillVersionResponse",
]


class CreateSkillRequest(BaseModel):
    """创建 Skill 请求。"""

    name: str = Field(min_length=1, max_length=64, description="Skill 名（租户内唯一）")
    display_name: str = Field(default="", max_length=255, description="展示名")
    description: str | None = Field(default=None, description="描述")
    category: str = Field(default="", max_length=100, description="分类")


class UpdateSkillRequest(BaseModel):
    """更新 Skill 请求（仅提供需变更字段）。"""

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None)
    category: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, description="生命周期状态（DRAFT/ACTIVE/ARCHIVED）")


class CreateSkillVersionRequest(BaseModel):
    """创建 Skill 版本请求。"""

    version: str = Field(min_length=1, max_length=50, description="语义化版本")
    instructions: str = Field(default="", description="指令文本")
    manifest: dict[str, Any] = Field(default_factory=dict, description="版本清单")


class SkillResponse(BaseModel):
    """Skill 响应。"""

    id: str
    tenant_id: str | None = Field(default=None)
    name: str
    display_name: str = ""
    description: str | None = Field(default=None)
    category: str = ""
    status: str = "DRAFT"
    current_version_id: str | None = Field(default=None)
    current_version: str | None = Field(default=None, description="当前生效版本号（可空）")
    created_by: str = ""
    created_at: datetime | None = Field(default=None)


class SkillVersionResponse(BaseModel):
    """SkillVersion 响应（**不含**资源二进制）。"""

    id: str
    skill_id: str
    version: str
    instructions: str = ""
    manifest: dict[str, Any] = Field(default_factory=dict)
    status: str = "DRAFT"
    created_by: str = ""
    created_at: datetime | None = Field(default=None)
