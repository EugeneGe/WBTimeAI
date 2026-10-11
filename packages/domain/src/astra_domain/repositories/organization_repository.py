"""``OrganizationRepository`` 接口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.organization import Organization
from .base import Repository

__all__ = ["OrganizationRepository"]


@runtime_checkable
class OrganizationRepository(Repository[Organization], Protocol):
    """组织仓储接口。"""

    def get_by_slug(self, tenant_id: str, slug: str) -> Organization | None:
        """按租户 + slug 获取组织。"""
        ...
