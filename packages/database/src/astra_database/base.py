"""SQLAlchemy 声明式基类与时间戳混入。

约定（设计 §2.3.1）：核心表统一使用 **UTC** 时间戳列 ``created_at`` / ``updated_at``。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import utcnow
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ["Base", "TimestampMixin"]


class Base(DeclarativeBase):
    """平台声明式基类（SQLAlchemy 2.x）。"""

    pass


class TimestampMixin:
    """为实体添加 UTC 的 ``created_at`` / ``updated_at`` 时间戳列。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )
