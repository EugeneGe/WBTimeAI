"""Role / Permission / RolePermission 实体。"""

from __future__ import annotations

from dataclasses import dataclass

from .base import AggregateRoot, Entity

__all__ = ["Role", "Permission", "RolePermission"]


@dataclass
class Role(AggregateRoot):
    """角色。"""

    name: str = ""
    description: str | None = None
    is_system: bool = False


@dataclass
class Permission(Entity):
    """权限（形如 ``workspace:update``，或通配 ``*``）。"""

    code: str = ""
    name: str = ""
    description: str | None = None


@dataclass
class RolePermission(Entity):
    """角色 ↔ 权限 关联。"""

    role_id: str = ""
    permission_id: str = ""
