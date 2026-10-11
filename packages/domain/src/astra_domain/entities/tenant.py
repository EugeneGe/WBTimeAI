"""Tenant 实体（多租户根）。"""

from __future__ import annotations

from dataclasses import dataclass

from ..constants import DEFAULT_TENANT_NAME, DEFAULT_TENANT_SLUG
from .base import AggregateRoot

__all__ = ["Tenant"]


@dataclass
class Tenant(AggregateRoot):
    """租户。

    Community 默认仅一个 ``default`` 租户，用户无感（设计 §2.4 Tenant-ready）。
    """

    name: str = DEFAULT_TENANT_NAME
    slug: str = DEFAULT_TENANT_SLUG
    is_active: bool = True
