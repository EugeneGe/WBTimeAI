"""Sandbox 组 ORM 表（设计 §2.15.1 Sandbox 组 / §2.11）。

- :class:`SandboxSession`：沙箱会话（``provider ∈ {docker, local_process}``）。

⚠️ 仅表结构；SandboxProvider 实现属 W4，本轮不实现。

⚠️ 本表字段严格对齐设计 §2.15.1（**11 列**，含 ``created_at`` 与 ``ended_at``，
   但**无** ``updated_at``）——故**不使用** :class:`~astra_database.base.TimestampMixin`。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import GUID

__all__ = ["SandboxSession"]


class SandboxSession(Base):
    """沙箱会话（容器 / 子进程的生命周期记录）。"""

    __tablename__ = "sandbox_session"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent_run.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    container_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workdir: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
