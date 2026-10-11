"""Plugin ORM 表（设计 §2.14；W1b 裁定 §2.3）。

⚠️ **W1b（T2-05）只建模型类，不建表**：建表随迁移 **``0010_phase2_permission_plugin``**
   （2a）落地（F18）。迁移 ``0010`` 落地时已在 ``models/__init__.py`` **登记本模型**
   （W3 / T2-13 完成登记），以保证 ``Base.metadata`` 与 DB **零漂移**。

🔴 表结构对齐设计 §2.14：``id`` / ``name`` / ``version`` / ``kind`` / ``entry_point`` /
   ``permissions``（JSON）/ ``manifest``（JSON）/ ``status`` / ``installed_at``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID

__all__ = ["Plugin"]


class Plugin(Base, TimestampMixin):
    """插件记录（**模型类**；建表随迁移 ``0010``）。"""

    __tablename__ = "plugin"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True, unique=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    entry_point: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="installed")
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
