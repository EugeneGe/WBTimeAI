"""``TenantRepository`` 接口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.tenant import Tenant
from .base import Repository

__all__ = ["TenantRepository"]


@runtime_checkable
class TenantRepository(Repository[Tenant], Protocol):
    """租户仓储接口。"""

    def get_by_slug(self, slug: str) -> Tenant | None:
        """按 slug 获取租户，不存在返回 ``None``。"""
        ...
