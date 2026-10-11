"""Membership 实体（用户 ↔ 组织 ↔ 角色）。"""

from __future__ import annotations

from dataclasses import dataclass

from ..constants import MEMBERSHIP_STATUS_ACTIVE
from .base import AggregateRoot

__all__ = ["Membership"]


@dataclass
class Membership(AggregateRoot):
    """成员关系。

    Attributes:
        user_id: 关联用户标识。
        organization_id: 关联组织标识（可空）。
        role_id: 关联角色标识（可空）。
        status: 成员状态（默认 ``active``）。
    """

    user_id: str = ""
    organization_id: str | None = None
    role_id: str | None = None
    status: str = MEMBERSHIP_STATUS_ACTIVE
