"""身份与多租户 ORM 表组（设计 §2.4 / §2.11）。

⚠️ 本模块仅定义**表结构**；Identity 的业务逻辑（仓储 / 服务 / RBAC /
默认 Tenant 引导）属 T0-11，本轮不实现。
"""

from __future__ import annotations

from astra_core import generate_id
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID

__all__ = [
    "Tenant",
    "User",
    "Organization",
    "Membership",
    "Role",
    "Permission",
    "RolePermission",
]


class Tenant(Base, TimestampMixin):
    """租户（Tenant-ready 的根；默认仅一个 ``default`` Tenant）。"""

    __tablename__ = "tenant"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class User(Base, TimestampMixin):
    """用户。"""

    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Organization(Base, TimestampMixin):
    """组织（默认体验极简，Phase 0 从简）。"""

    __tablename__ = "organization"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)


class Role(Base, TimestampMixin):
    """角色。"""

    __tablename__ = "role"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_role_tenant_name"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Permission(Base, TimestampMixin):
    """权限（如 ``workspace:update``）。"""

    __tablename__ = "permission"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    code: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Membership(Base, TimestampMixin):
    """成员关系（用户 ↔ 组织 / 角色）。"""

    __tablename__ = "membership"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("user.id"), nullable=False, index=True)
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    role_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("role.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")


class RolePermission(Base, TimestampMixin):
    """角色 ↔ 权限 关联表。"""

    __tablename__ = "role_permission"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    role_id: Mapped[str] = mapped_column(GUID(), ForeignKey("role.id"), nullable=False, index=True)
    permission_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("permission.id"), nullable=False, index=True
    )
