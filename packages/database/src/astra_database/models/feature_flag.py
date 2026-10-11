"""Feature Flag ORM 表（设计 §2.3.4 / T0-21）。

⚠️ **全局表**（Phase 0 不带 ``tenant_id``）：Feature Flag 为**平台级行为开关**，
   不参与多租户隔离。

🔴 本表**仅用于覆盖**：注册表默认（全开）与配置覆盖由配置层提供；
   本表的存在性**不得**成为应用启动前置依赖（表缺失 → 读空覆盖，应用仍启动）。
"""

from __future__ import annotations

from astra_core import generate_id
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID

__all__ = ["FeatureFlag"]


class FeatureFlag(Base, TimestampMixin):
    """Feature Flag 覆盖记录（全局表）。"""

    __tablename__ = "feature_flag"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
