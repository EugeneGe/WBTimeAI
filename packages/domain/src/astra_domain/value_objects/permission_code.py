"""``PermissionCode`` 值对象（形如 ``resource:action``）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from astra_core import ValidationError

__all__ = ["PermissionCode"]

#: 资源码：小写字母 / 数字 / ``_`` / ``.`` / ``-`` / ``:``。
_RESOURCE_RE = re.compile(r"^[a-z][a-z0-9_.:-]*$")
#: 动作码：小写字母 / 数字 / ``_`` / ``*``。
_ACTION_RE = re.compile(r"^[a-z0-9_*]+$")

#: 通配权限（admin = *）。
WILDCARD = "*"


@dataclass(frozen=True)
class PermissionCode:
    """权限码值对象（不可变）。

    合法形式：通配 ``*``，或 ``资源:动作``（如 ``workspace:update``）。

    Raises:
        ValidationError: 格式非法时。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if normalized == WILDCARD:
            object.__setattr__(self, "value", normalized)
            return
        parts = normalized.split(":", 1)
        if len(parts) != 2:
            raise ValidationError(
                "PermissionCode 需形如 resource:action 或 *",
                data={"field": "permission_code", "value": normalized},
            )
        resource, action = parts
        if not _RESOURCE_RE.match(resource) or not _ACTION_RE.match(action):
            raise ValidationError(
                "PermissionCode 格式非法",
                data={"field": "permission_code", "value": normalized},
            )
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value
