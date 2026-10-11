"""Workspace 实体（设计 §2.9）。

Workspace 是平台资源的归属容器：每个用户至少拥有一个 ``personal`` 工作区，
专业版可再建 ``team`` 工作区。``settings`` / ``config`` 为 JSON 结构，
由持久化层以 JSON 列承载。

⚠️ 本实体**纯 dataclass，零框架依赖**（不引用 ORM / Web / 校验框架）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import WORKSPACE_TYPE_PERSONAL
from .base import AggregateRoot

__all__ = ["Workspace"]


@dataclass
class Workspace(AggregateRoot):
    """工作区聚合根。

    Attributes:
        owner_id: 拥有者用户标识。
        name: 工作区名称。
        workspace_type: 工作区类型（``personal`` | ``team``）。
        settings: 工作区设置（JSON 结构）。
        config: 工作区配置（JSON 结构）。
    """

    owner_id: str = ""
    name: str = ""
    workspace_type: str = WORKSPACE_TYPE_PERSONAL
    settings: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
