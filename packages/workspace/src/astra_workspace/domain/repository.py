"""``astra_workspace`` 仓储接口（**仅 Protocol**，零 ORM；W7 / T2-37）。

- :class:`ProjectRepository`：Project 聚合仓储接口（多租户 / Workspace 归属查询）。

SQLAlchemy 实现落本包 ``repositories/project_repository.py``（能力包显式允许的 ORM 落点）。

🔴 **``scope`` 形参预留位（W7 裁定 R12 / R13）**：本波 ``ScopeFilter``（``astra_domain.scope``）
   尚未落地（归 T2-40），故此处以 ``Any | None`` 占位；T2-40 落地后将**类型收紧**为
   ``ScopeFilter | None``（**加性、向后兼容**：缺省 ``None`` ＝ 不额外过滤，仅维持
   ``tenant_id`` 硬过滤，I-1/I-2）。
🔴 本子模块**零 Web / ORM**（不 import ``sqlalchemy`` / ``alembic`` / ``fastapi`` /
   ``starlette``）。
"""

from __future__ import annotations

import builtins
from typing import Any, Protocol, runtime_checkable

from .project import Project, WorkspaceEnvironment

__all__ = ["ProjectRepository", "WorkspaceEnvironmentRepository"]


@runtime_checkable
class ProjectRepository(Protocol):
    """Project 聚合仓储接口（多租户 / Workspace 归属查询）。

    🔴 ``scope``：组织 / 工作区范围过滤（**可选**，缺省不过滤）；本波为占位签名，
       T2-40 收紧为 ``ScopeFilter | None``。
    """

    def get(self, project_id: str) -> Project | None:
        """按主键获取项目，不存在返回 ``None``。"""
        ...

    def add(self, entity: Project) -> Project:
        """新增项目并返回。"""
        ...

    def list(self, scope: Any | None = None, **filters: Any) -> builtins.list[Project]:
        """按等值条件列出项目（``scope`` 可选，缺省不额外过滤）。"""
        ...

    def update(self, entity: Project) -> Project:
        """更新项目并返回。"""
        ...

    def delete(self, entity: Project) -> None:
        """删除项目。"""
        ...

    def list_by_workspace(
        self, workspace_id: str, *, scope: Any | None = None
    ) -> builtins.list[Project]:
        """列出某 Workspace 下的全部项目（``scope`` 可选）。"""
        ...


@runtime_checkable
class WorkspaceEnvironmentRepository(Protocol):
    """Workspace 运行环境仓储接口（多租户 / Workspace 归属查询；``scope`` 可选的占位签名）。"""

    def get(self, environment_id: str) -> WorkspaceEnvironment | None:
        """按主键获取环境，不存在返回 ``None``。"""
        ...

    def add(self, entity: WorkspaceEnvironment) -> WorkspaceEnvironment:
        """新增环境并返回。"""
        ...

    def list(self, scope: Any | None = None, **filters: Any) -> builtins.list[WorkspaceEnvironment]:
        """按等值条件列出环境（``scope`` 可选）。"""
        ...

    def update(self, entity: WorkspaceEnvironment) -> WorkspaceEnvironment:
        """更新环境并返回。"""
        ...

    def delete(self, entity: WorkspaceEnvironment) -> None:
        """删除环境。"""
        ...

    def list_by_workspace(
        self, workspace_id: str, *, scope: Any | None = None
    ) -> builtins.list[WorkspaceEnvironment]:
        """列出某 Workspace 下的全部环境（``scope`` 可选）。"""
        ...

    def get_by_name(
        self, workspace_id: str, name: str, *, scope: Any | None = None
    ) -> WorkspaceEnvironment | None:
        """按 ``(workspace_id, name)`` 获取环境（唯一键语义）。"""
        ...
