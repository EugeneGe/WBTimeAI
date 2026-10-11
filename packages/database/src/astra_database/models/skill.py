"""Skill 组 ORM 表（设计 §2.3 / §2.15.1；W2 / T2-07）。

- :class:`Skill`：Skill 身份与生命周期（``(tenant_id, name)`` 唯一）；
- :class:`SkillVersion`：**不可变**版本快照（``(skill_id, version)`` 唯一；``instructions``
  为 ``Text``、``manifest`` 为 JSON）；
- :class:`SkillResource`：版本内资源（``storage_key`` 对接 ``Storage``）；
- :class:`AgentSkill`：Skill↔AgentVersion 绑定（随版本版本化；唯一键
  ``(agent_version_id, skill_id)``，同构 ``agent_tool``）。

🔴 本模块落在 ``astra_database``（ORM 允许位置）；域实体在 ``astra_skill.domain``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Skill", "SkillVersion", "SkillResource", "AgentSkill"]


class Skill(Base, TimestampMixin):
    """Skill：专业能力单元（身份与生命周期；设计 §2.3）。"""

    __tablename__ = "skill"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_skill_tenant_name"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(
        GUID(),
        ForeignKey("skill_version.id", use_alter=True, name="fk_skill_current_version_id"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(
        GUID(), ForeignKey("user.id"), nullable=False, index=True
    )


class SkillVersion(Base):
    """SkillVersion：一次发布 = 一个新版本，**不可变**（设计 §2.3）。"""

    __tablename__ = "skill_version"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_version_skill_version"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    skill_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("skill.id"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    instructions: Mapped[str] = mapped_column(Text(), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by: Mapped[str] = mapped_column(
        GUID(), ForeignKey("user.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class SkillResource(Base):
    """SkillResource：版本内资源（``storage_key`` 对接 ``Storage``）。"""

    __tablename__ = "skill_resource"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    skill_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("skill_version.id"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class AgentSkill(Base, TimestampMixin):
    """AgentSkill：绑定到 **AgentVersion** 的 Skill（随版本版本化；设计 §2.3）。"""

    __tablename__ = "agent_skill"
    __table_args__ = (
        UniqueConstraint("agent_version_id", "skill_id", name="uq_agent_skill_version_skill"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    agent_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent_version.id"), nullable=False, index=True
    )
    skill_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("skill.id"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
