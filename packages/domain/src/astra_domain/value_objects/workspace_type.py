"""``WorkspaceType`` 值对象（纯标准库）。

合法取值仅 ``personal`` / ``team``（设计 §2.9）；非法值以
``VALIDATION_ERROR`` 拒绝。
"""

from __future__ import annotations

from enum import StrEnum

from astra_core import ValidationError

from ..constants import WORKSPACE_TYPE_PERSONAL, WORKSPACE_TYPE_TEAM

__all__ = ["WorkspaceType"]


class WorkspaceType(StrEnum):
    """工作区类型（``str`` 枚举，序列化即为字面值）。"""

    PERSONAL = WORKSPACE_TYPE_PERSONAL
    TEAM = WORKSPACE_TYPE_TEAM

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return (cls.PERSONAL.value, cls.TEAM.value)

    @classmethod
    def ensure(cls, value: str | WorkspaceType) -> WorkspaceType:
        """校验并归一化工作区类型。

        Args:
            value: 待校验的取值（字符串或 :class:`WorkspaceType`）。

        Returns:
            归一化后的 :class:`WorkspaceType`。

        Raises:
            ValidationError: 取值不在 ``{personal, team}`` 内。
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError as exc:
            raise ValidationError(
                "workspace_type 仅允许 personal 或 team",
                data={"field": "workspace_type", "value": str(value)},
            ) from exc
