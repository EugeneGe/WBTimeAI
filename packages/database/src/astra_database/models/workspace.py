"""Workspace ORM 表（设计 §2.9）。

⚠️ 仅表结构；Workspace 业务（创建 / 列表 / 设置）属 T0-17，本轮不实现。
"""

from __future__ import annotations

from typing import Any

from astra_core import generate_id
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Workspace"]


class Workspace(Base, TimestampMixin):
    """Workspace：平台资源的归属容器。"""

    __tablename__ = "workspace"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    owner_id: Mapped[str] = mapped_column(GUID(), ForeignKey("user.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_type: Mapped[str] = mapped_column(String(50), nullable=False, default="personal")
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
