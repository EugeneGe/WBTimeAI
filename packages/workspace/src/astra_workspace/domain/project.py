"""``astra_workspace`` 领域实体：Project / WorkspaceEnvironment（设计 §2.8；W7 / T2-37）。

- :class:`Project`：Workspace 下的项目资源根（承载仓库地址 / 默认分支 / 设置）；
- :class:`WorkspaceEnvironment`：Workspace 内命名运行环境（``env_vars`` / ``runtime``）。

🔴 本模块**纯 dataclass，零框架依赖**（不引用 ORM / Web / 校验框架）；ORM 落
   ``astra_database.models.project``，映射经 ``repositories.project_repository``。
🔴 ``env_vars`` **仅非敏感项**（§3.2）；敏感值经 ``credential`` / ``SecretProvider``
   引用注入，**禁**明文落库。
🔴 ``repo_url`` **禁存用户名 / Token / 密码**（§2.8.1）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_domain import AggregateRoot

__all__ = ["Project", "WorkspaceEnvironment"]


@dataclass
class Project(AggregateRoot):
    """Workspace 下的项目聚合根（设计 §2.8.1）。

    Attributes:
        tenant_id: 所属租户标识（硬隔离，I-1；基类字段）。
        organization_id: 组织归属（可空，继承 Workspace；A-7）。
        workspace_id: 归属 Workspace 标识（NOT NULL 语义）。
        name: 项目名称。
        description: 项目描述。
        repo_url: 仓库地址（**禁存用户名 / Token / 密码**）。
        default_branch: 默认分支。
        settings: 项目设置（JSON 结构）。
        created_by: 创建者用户标识（可空）。
    """

    workspace_id: str = ""
    organization_id: str | None = None
    name: str = ""
    description: str | None = None
    repo_url: str | None = None
    default_branch: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    created_by: str | None = None

    def assert_valid(self) -> None:
        """断言项目必需字段齐备。

        Raises:
            DomainError: ``name`` 为空或 ``workspace_id`` 为空（``VALIDATION_ERROR``）。
        """
        from astra_core import DomainError, ErrorCode

        if not (self.name or "").strip():
            raise DomainError(
                "项目名称不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "name"},
            )
        if not (self.workspace_id or "").strip():
            raise DomainError(
                "项目必须归属某个工作区",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "workspace_id"},
            )


@dataclass
class WorkspaceEnvironment(AggregateRoot):
    """Workspace 内命名运行环境（设计 §2.8.1）。

    唯一键语义 ``(workspace_id, name)``（同一 Workspace 内环境名唯一）。

    Attributes:
        tenant_id: 所属租户标识（硬隔离，I-1；基类字段）。
        organization_id: 组织归属（可空，经 Workspace 推导；A-7）。
        workspace_id: 归属 Workspace 标识。
        name: 环境名称（如 ``dev`` / ``staging`` / ``prod``）。
        env_vars: 环境变量（🔴 **仅非敏感项**，§3.2）。
        runtime: 运行时描述（语言版本 / 依赖 / 镜像 / ``network_profile``）。
    """

    workspace_id: str = ""
    organization_id: str | None = None
    name: str = ""
    env_vars: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)

    def assert_valid(self) -> None:
        """断言环境必需字段齐备。

        Raises:
            DomainError: ``name`` 为空或 ``workspace_id`` 为空（``VALIDATION_ERROR``）。
        """
        from astra_core import DomainError, ErrorCode

        if not (self.name or "").strip():
            raise DomainError(
                "环境名称不能为空",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "name"},
            )
        if not (self.workspace_id or "").strip():
            raise DomainError(
                "环境必须归属某个工作区",
                code=ErrorCode.VALIDATION_ERROR,
                data={"field": "workspace_id"},
            )
