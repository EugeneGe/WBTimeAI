"""Organization 实体（Phase 0 从简：默认组织自动建立）。"""

from __future__ import annotations

from dataclasses import dataclass

from ..constants import DEFAULT_ORG_NAME, DEFAULT_ORG_SLUG
from .base import AggregateRoot

__all__ = ["Organization"]


@dataclass
class Organization(AggregateRoot):
    """组织。"""

    name: str = DEFAULT_ORG_NAME
    slug: str = DEFAULT_ORG_SLUG
