"""Agent 组 ORM 表（设计 §2.15.1 Agent 组 / §2.4）。

- :class:`Agent`：Agent 身份与生命周期（数据驱动配置的聚合根）。
- :class:`AgentVersion`：**不可变**版本快照（Prompt / Model / Runtime）。
- :class:`AgentTool`：Tool 绑定（随版本版本化 / 可回滚）+ 每 Tool 权限 scope。

⚠️ 仅表结构；Agent 业务用例（创建 / 发布 / 执行）属 W5/W6，本轮不实现。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Agent", "AgentVersion", "AgentTool"]


class Agent(Base, TimestampMixin):
    """Agent：可组合配置的身份与生命周期（设计 §2.4）。"""

    __tablename__ = "agent"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(
        GUID(),
        ForeignKey("agent_version.id", use_alter=True, name="fk_agent_current_version_id"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(
        GUID(), ForeignKey("user.id"), nullable=False, index=True
    )


class AgentVersion(Base):
    """AgentVersion：一次发布 = 一个新版本，**不可变**（设计 §2.4）。"""

    __tablename__ = "agent_version"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    agent_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent.id"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text(), nullable=False)
    model_config: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False)
    runtime_config: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by: Mapped[str] = mapped_column(
        GUID(), ForeignKey("user.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class AgentTool(Base):
    """AgentTool：绑定到 **AgentVersion** 的 Tool + 权限 scope（设计 §2.4）。"""

    __tablename__ = "agent_tool"
    __table_args__ = (
        UniqueConstraint("agent_version_id", "tool_id", name="uq_agent_tool_version_tool"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    agent_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent_version.id"), nullable=False, index=True
    )
    tool_id: Mapped[str] = mapped_column(GUID(), ForeignKey("tool.id"), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    permission_scope: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
