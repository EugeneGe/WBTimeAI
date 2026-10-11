"""Project / WorkspaceEnvironment ORM 表（设计 §2.8；W7 / T2-37）。

- :class:`Project`：Workspace 下的「项目」资源根（承载 ``repo_url`` / ``default_branch`` /
  ``settings``），经 ``workspace_id`` 归属容器；
- :class:`WorkspaceEnvironment`：Workspace 下的「运行环境」定义（``env_vars`` / ``runtime``），
  同一 Workspace 内环境名唯一。

🔴 **组织维度（A-7 / §13 R-open#2）**：``organization_id`` 为**可空 FK→organization**，
   由迁移 ``0015`` **建表即含**（一次到位），``0016`` 仅**回填**（不再改本表结构）。
🔴 ``env_vars`` **仅承载非敏感项**（§3.2）；敏感值经 ``credential`` / ``SecretProvider``
   引用注入，**禁**明文落库。
🔴 ``repo_url`` **禁存用户名 / Token / 密码**（§2.8.1）。
🔴 ORM 落 ``astra_database``（``astra_task`` 零 ORM 不变量的同款纪律，R2）；域实体在
   ``astra_workspace.domain``。
"""

from __future__ import annotations

from typing import Any

from astra_core import generate_id
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["Project", "WorkspaceEnvironment"]


class Project(Base, TimestampMixin):
    """``project``：Workspace 归属容器下的项目资源根（设计 §2.8.1）。

    Attributes:
        tenant_id: 所属租户（硬隔离，I-1）。
        organization_id: 继承 Workspace 的组织归属（可空，A-7）。
        workspace_id: 归属 Workspace（NOT NULL）。
        name: 项目名称。
        description: 项目描述（可空）。
        repo_url: 仓库地址（**禁存用户名 / Token / 密码**）。
        default_branch: 默认分支（可空）。
        settings: 项目设置（JSON 结构）。
        created_by: 创建者用户标识（可空）。
    """

    __tablename__ = "project"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(GUID(), ForeignKey("user.id"), nullable=True)


class WorkspaceEnvironment(Base, TimestampMixin):
    """``workspace_environment``：Workspace 内命名运行环境（设计 §2.8.1）。

    唯一键 ``(workspace_id, name)``（同一 Workspace 内环境名唯一）。

    Attributes:
        env_vars: 环境变量（🔴 **仅非敏感项**，§3.2）。
        runtime: 运行时描述（语言 / 依赖 / 镜像 / ``network_profile``）。
    """

    __tablename__ = "workspace_environment"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_workspace_environment_ws_name"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    env_vars: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    runtime: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
