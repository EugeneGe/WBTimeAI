"""``TenantSlug`` / ``OrgSlug`` 值对象（URL 友好标识）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from astra_core import ValidationError

__all__ = ["Slug", "TenantSlug", "OrgSlug"]

#: slug 允许小写字母 / 数字 / 连字符，首字符须为字母或数字。
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_MAX_LENGTH = 255


@dataclass(frozen=True)
class Slug:
    """slug 值对象基类（不可变）。

    Raises:
        ValidationError: 为空、过长、含非法字符时。
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not normalized:
            raise ValidationError("Slug 不能为空", data={"field": "slug"})
        if len(normalized) > _MAX_LENGTH:
            raise ValidationError("Slug 过长", data={"field": "slug", "max": _MAX_LENGTH})
        if not _SLUG_RE.match(normalized):
            raise ValidationError("Slug 格式非法", data={"field": "slug", "value": normalized})
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TenantSlug(Slug):
    """租户 slug。"""


@dataclass(frozen=True)
class OrgSlug(Slug):
    """组织 slug。"""
