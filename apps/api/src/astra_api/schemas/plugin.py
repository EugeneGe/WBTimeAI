"""Plugin schema（W3 / T2-17；设计 §2.14 / §2.12）。

``/plugins`` 已装 / 安装 / 卸载 的请求 / 响应模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["InstallPluginRequest", "PluginResponse"]


class InstallPluginRequest(BaseModel):
    """安装插件请求。"""

    name: str = Field(min_length=1, max_length=150, description="插件名（全局唯一）")
    version: str = Field(min_length=1, max_length=50)
    kind: str = Field(min_length=1, max_length=50, description="种类（connector/tool/...）")
    entry_point: str | None = Field(default=None, max_length=255)
    permissions: list[str] = Field(default_factory=list, description="声明权限")
    manifest: dict[str, Any] = Field(default_factory=dict, description="插件清单")


class PluginResponse(BaseModel):
    """插件响应。"""

    id: str
    name: str
    version: str
    kind: str
    entry_point: str | None = Field(default=None)
    permissions: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    status: str = "installed"
    installed_at: datetime | None = Field(default=None)
