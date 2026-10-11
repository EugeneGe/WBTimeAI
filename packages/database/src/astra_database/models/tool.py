"""Tool 组 ORM 表（设计 §2.15.1 Tool 组 / §2.5）。

- :class:`Tool`：工具目录（``tenant_id`` 可空 —— 内置工具为全局）。
- :class:`ToolVersion`：工具规格快照。
- :class:`ToolPermission`：Tool 权限（``effect`` 预留 ``APPROVAL``，本期恒 ``ALLOW``/``DENY``）。

⚠️ 仅表结构；Tool 实现 / 权限执行属 W4，本轮不实现。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Tool", "ToolVersion", "ToolPermission"]


class Tool(Base):
    """工具目录（内置工具 ``tenant_id = NULL`` 表示全局）。"""

    __tablename__ = "tool"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=True, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    # 🔴 全局内置 Tool（``source=builtin``）保持 ``NULL``（不表示跨组织共享）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    requires_sandbox: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    # W2 / T2-10（R9 §9.2）：MCP Tool 溯源引用（``{"kind":"mcp","id":<mcp_tool_id>,
    # "server_id":...,"name":"mcp:<server>.<tool>","version":...}``）；内置 Tool 为 ``None``。
    tool_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)


class ToolVersion(Base):
    """工具规格快照。"""

    __tablename__ = "tool_version"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tool_id: Mapped[str] = mapped_column(GUID(), ForeignKey("tool.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class ToolPermission(Base, TimestampMixin):
    """Tool 权限（ALLOW / DENY；``APPROVAL`` 预留，Phase 3）。"""

    __tablename__ = "tool_permission"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "tool_id", "action", name="uq_tool_permission_agent_tool_action"
        ),
        # 表注释：与迁移 ``0010_phase2_permission_plugin`` 的 ``COMMENT ON TABLE
        # tool_permission`` **逐字一致**（PG 权威零漂移前置；SQLite 无表注释能力，忽略）。
        {
            "comment": (
                "deprecated: default-policy template only; runtime permission source is "
                "resource_permission + agent_tool.permission_scope (W3 §1.2)"
            )
        },
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent.id"), nullable=True, index=True
    )
    agent_version_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent_version.id"), nullable=True, index=True
    )
    tool_id: Mapped[str] = mapped_column(GUID(), ForeignKey("tool.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    effect: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
