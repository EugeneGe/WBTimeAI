"""``Email`` 值对象（规范化 + 校验）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from astra_core import ValidationError

__all__ = ["Email"]

#: 保守的邮箱正则：``local@domain.tld``（不含空白）。
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: 邮箱最大长度（对齐 ORM ``String(320)``）。
_MAX_LENGTH = 320


@dataclass(frozen=True)
class Email:
    """邮箱值对象（不可变）。

    构造时进行规范化（去首尾空白 + 转小写）与合法性校验。

    Raises:
        ValidationError: 邮箱为空、过长或格式非法时。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not normalized:
            raise ValidationError("Email 不能为空", data={"field": "email"})
        if len(normalized) > _MAX_LENGTH:
            raise ValidationError("Email 过长", data={"field": "email", "max": _MAX_LENGTH})
        if not _EMAIL_RE.match(normalized):
            raise ValidationError("Email 格式非法", data={"field": "email", "value": normalized})
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value
