"""Phase 0 基线迁移：Identity 表组 + workspace + task + credential。

Revision ID: 0001_phase0_baseline
Revises:
Create Date: 2025-01-01

约定（设计 §2.3.1 / §2.11）：
- 主键为 UUIDv7（以 ``GUID`` 方言适配类型存储为字符串）；
- 核心表均含 ``tenant_id``（Tenant-ready）；
- 时间戳列统一 UTC（``DateTime(timezone=True)``）；
- JSON 列经 ``JSONType`` 方言适配（PostgreSQL JSONB / SQLite JSON）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from astra_database.types import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "0001_phase0_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    """返回统一的时间戳列定义（UTC）。"""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    """创建 Phase 0 基线表结构。"""
    # -- 1. tenant -----------------------------------------------------------
    op.create_table(
        "tenant",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_tenant_slug", "tenant", ["slug"], unique=True)

    # -- 2. user -------------------------------------------------------------
    op.create_table(
        "user",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_user_tenant_id"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )
    op.create_index("ix_user_tenant_id", "user", ["tenant_id"])
    op.create_index("ix_user_username", "user", ["username"])
    op.create_index("ix_user_email", "user", ["email"])

    # -- 3. organization -----------------------------------------------------
    op.create_table(
        "organization",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_organization_tenant_id"),
    )
    op.create_index("ix_organization_tenant_id", "organization", ["tenant_id"])
    op.create_index("ix_organization_slug", "organization", ["slug"])

    # -- 4. role -------------------------------------------------------------
    op.create_table(
        "role",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_role_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_role_tenant_name"),
    )
    op.create_index("ix_role_tenant_id", "role", ["tenant_id"])

    # -- 5. permission -------------------------------------------------------
    op.create_table(
        "permission",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("code", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_permission_code", "permission", ["code"], unique=True)

    # -- 6. membership -------------------------------------------------------
    op.create_table(
        "membership",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("organization_id", GUID(), nullable=True),
        sa.Column("role_id", GUID(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_membership_tenant_id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_membership_user_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], name="fk_membership_organization_id"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="fk_membership_role_id"),
    )
    op.create_index("ix_membership_tenant_id", "membership", ["tenant_id"])
    op.create_index("ix_membership_user_id", "membership", ["user_id"])
    op.create_index("ix_membership_organization_id", "membership", ["organization_id"])
    op.create_index("ix_membership_role_id", "membership", ["role_id"])

    # -- 7. role_permission --------------------------------------------------
    op.create_table(
        "role_permission",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("role_id", GUID(), nullable=False),
        sa.Column("permission_id", GUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="fk_role_permission_role_id"),
        sa.ForeignKeyConstraint(
            ["permission_id"], ["permission.id"], name="fk_role_permission_permission_id"
        ),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )
    op.create_index("ix_role_permission_role_id", "role_permission", ["role_id"])
    op.create_index("ix_role_permission_permission_id", "role_permission", ["permission_id"])

    # -- 8. session ----------------------------------------------------------
    op.create_table(
        "session",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("device", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_session_tenant_id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_session_user_id"),
    )
    op.create_index("ix_session_tenant_id", "session", ["tenant_id"])
    op.create_index("ix_session_user_id", "session", ["user_id"])

    # -- 9. refresh_token ----------------------------------------------------
    op.create_table(
        "refresh_token",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("session_id", GUID(), nullable=True),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_refresh_token_tenant_id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_refresh_token_user_id"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], name="fk_refresh_token_session_id"),
    )
    op.create_index("ix_refresh_token_tenant_id", "refresh_token", ["tenant_id"])
    op.create_index("ix_refresh_token_user_id", "refresh_token", ["user_id"])
    op.create_index("ix_refresh_token_session_id", "refresh_token", ["session_id"])
    op.create_index("ix_refresh_token_token_hash", "refresh_token", ["token_hash"])

    # -- 10. login_attempt ---------------------------------------------------
    op.create_table(
        "login_attempt",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=True),
        sa.Column("username", sa.String(length=150), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_login_attempt_tenant_id"),
    )
    op.create_index("ix_login_attempt_tenant_id", "login_attempt", ["tenant_id"])
    op.create_index("ix_login_attempt_username", "login_attempt", ["username"])

    # -- 11. workspace -------------------------------------------------------
    op.create_table(
        "workspace",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("owner_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("workspace_type", sa.String(length=50), nullable=False),
        sa.Column("settings", JSONType(), nullable=True),
        sa.Column("config", JSONType(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_workspace_tenant_id"),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], name="fk_workspace_owner_id"),
    )
    op.create_index("ix_workspace_tenant_id", "workspace", ["tenant_id"])
    op.create_index("ix_workspace_owner_id", "workspace", ["owner_id"])

    # -- 12. task ------------------------------------------------------------
    op.create_table(
        "task",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("payload", JSONType(), nullable=True),
        sa.Column("result", JSONType(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_task_tenant_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], name="fk_task_workspace_id"),
    )
    op.create_index("ix_task_tenant_id", "task", ["tenant_id"])
    op.create_index("ix_task_workspace_id", "task", ["workspace_id"])
    op.create_index("ix_task_status", "task", ["status"])

    # -- 13. credential ------------------------------------------------------
    op.create_table(
        "credential",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("tenant_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("key_type", sa.String(length=50), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_credential_tenant_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_credential_workspace_id"
        ),
    )
    op.create_index("ix_credential_tenant_id", "credential", ["tenant_id"])
    op.create_index("ix_credential_workspace_id", "credential", ["workspace_id"])


def downgrade() -> None:
    """回滚：按创建逆序删除所有基线表。"""
    op.drop_table("credential")
    op.drop_table("task")
    op.drop_table("workspace")
    op.drop_table("login_attempt")
    op.drop_table("refresh_token")
    op.drop_table("session")
    op.drop_table("role_permission")
    op.drop_table("membership")
    op.drop_table("permission")
    op.drop_table("role")
    op.drop_table("organization")
    op.drop_table("user")
    op.drop_table("tenant")
