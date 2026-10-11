"""``Username`` 值对象（规范化 + 校验）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from astra_core import ValidationError

__all__ = ["Username"]

#: 允许的字符：字母 / 数字 / ``_`` / ``-`` / ``.``。
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

_MIN_LENGTH = 3
_MAX_LENGTH = 150


@dataclass(frozen=True)
class Username:
    """用户名值对象（不可变）。

    Raises:
        ValidationError: 长度不合法或包含非法字符时。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not (_MIN_LENGTH <= len(normalized) <= _MAX_LENGTH):
            raise ValidationError(
                "Username 长度非法",
                data={"field": "username", "min": _MIN_LENGTH, "max": _MAX_LENGTH},
            )
        if not _USERNAME_RE.match(normalized):
            raise ValidationError("Username 含非法字符", data={"field": "username"})
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value
