"""``astra_workspace`` Project / Environment 仓储（SQL 实现 ``domain`` Protocol）。

复用 ``astra_database.BaseRepository``（风格①：``session`` 入参，F8）；ORM 模型在
``astra_database.models.project``（随迁移 ``0015`` 落地）。

🔴 **落点勘误（W7 裁定 R4）**：本文件名为 ``project_repository.py``（**非**任务卡
   ``repositories/sql.py``），与既有 ``workspace_repository.py`` 命名一致。
🔴 **``scope`` 形参（W7 裁定 R12 → T2-40 §6）**：``ProjectRepository`` /
   ``WorkspaceEnvironmentRepository`` 的 ``list`` / ``list_by_workspace`` / ``get_by_name``
   接收 ``scope: ScopeFilter | None = None``（缺省 ``None`` ＝ 不额外过滤，仅维持 ``tenant_id``
   硬过滤）；经 :meth:`astra_database.BaseRepository._apply_scope` 叠加租户 / 组织 / 工作区谓词
   （**加性、向后兼容**）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_common.time import utcnow
from astra_database import BaseRepository
from astra_database.models.project import Project as OrmProject
from astra_database.models.project import WorkspaceEnvironment as OrmWorkspaceEnvironment
from astra_domain import ScopeFilter
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..domain import Project, WorkspaceEnvironment

__all__ = [
    "SqlProjectRepository",
    "SqlWorkspaceEnvironmentRepository",
    "project_to_domain",
    "project_to_orm",
    "environment_to_domain",
    "environment_to_orm",
]


def _dt(value: object) -> object:
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


# -- ORM 行 ⇆ 领域实体映射 ---------------------------------------------------


def project_to_domain(row: OrmProject) -> Project:
    """ORM ``project`` 行 → 领域 :class:`~astra_workspace.domain.Project`。"""
    return Project(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(row.created_at),  # type: ignore[arg-type]
        updated_at=_dt(row.updated_at),  # type: ignore[arg-type]
        workspace_id=row.workspace_id,
        organization_id=row.organization_id,
        name=row.name,
        description=row.description,
        repo_url=row.repo_url,
        default_branch=row.default_branch,
        settings=dict(row.settings) if row.settings else {},
        created_by=row.created_by,
    )


def project_to_orm(entity: Project) -> OrmProject:
    """领域 :class:`~astra_workspace.domain.Project` → ORM ``project`` 行。"""
    return OrmProject(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        organization_id=entity.organization_id,
        name=entity.name,
        description=entity.description,
        repo_url=entity.repo_url,
        default_branch=entity.default_branch,
        settings=dict(entity.settings) if entity.settings else {},
        created_by=entity.created_by,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def environment_to_domain(row: OrmWorkspaceEnvironment) -> WorkspaceEnvironment:
    """ORM ``workspace_environment`` 行 → 领域 ``WorkspaceEnvironment``。"""
    return WorkspaceEnvironment(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(row.created_at),  # type: ignore[arg-type]
        updated_at=_dt(row.updated_at),  # type: ignore[arg-type]
        workspace_id=row.workspace_id,
        organization_id=row.organization_id,
        name=row.name,
        env_vars=dict(row.env_vars) if row.env_vars else {},
        runtime=dict(row.runtime) if row.runtime else {},
    )


def environment_to_orm(entity: WorkspaceEnvironment) -> OrmWorkspaceEnvironment:
    """领域 :class:`~astra_workspace.domain.WorkspaceEnvironment` → ORM 行。"""
    return OrmWorkspaceEnvironment(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workspace_id=entity.workspace_id,
        organization_id=entity.organization_id,
        name=entity.name,
        env_vars=dict(entity.env_vars) if entity.env_vars else {},
        runtime=dict(entity.runtime) if entity.runtime else {},
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


# -- 仓储实现 ----------------------------------------------------------------


class SqlProjectRepository(BaseRepository[OrmProject]):
    """基于 SQLAlchemy 的项目仓储（领域实体 ⇆ ORM 行；风格①）。

    ``scope`` 缺省 ``None`` ＝ 不额外过滤（仅维持 ``tenant_id`` 硬过滤，R13 向后兼容）。
    """

    model = OrmProject

    def __init__(self, session: Session, scope: ScopeFilter | None = None) -> None:
        super().__init__(session, OrmProject, scope)

    def get(self, entity_id: str) -> Project | None:  # type: ignore[override]
        row = super().get(entity_id)
        return project_to_domain(row) if row is not None else None

    def add(self, entity: Project) -> Project:  # type: ignore[override]
        row = super().add(project_to_orm(entity))
        return project_to_domain(row)

    def update(self, entity: Project) -> Project:  # type: ignore[override]
        row = super().update(project_to_orm(entity))
        return project_to_domain(row)

    def delete(self, entity: Project) -> None:  # type: ignore[override]
        row = self.session.get(OrmProject, entity.id)
        if row is not None:
            super().delete(row)

    def list(  # type: ignore[override]
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[Project]:
        """按等值条件列出项目（``scope`` 叠加租户 / 组织 / 工作区过滤，缺省不过滤）。"""
        return [project_to_domain(row) for row in super().list(scope=scope, **filters)]

    def list_by_workspace(
        self, workspace_id: str, *, scope: ScopeFilter | None = None
    ) -> builtins.list[Project]:
        """列出某 Workspace 下的全部项目（按创建时间升序；``scope`` 叠加过滤）。"""
        statement: Select[Any] = select(OrmProject).where(OrmProject.workspace_id == workspace_id)
        statement = self._apply_scope(statement, scope if scope is not None else self.scope)
        statement = statement.order_by(OrmProject.created_at.asc())
        rows = self.session.execute(statement).scalars().all()
        return [project_to_domain(row) for row in rows]


class SqlWorkspaceEnvironmentRepository(BaseRepository[OrmWorkspaceEnvironment]):
    """基于 SQLAlchemy 的工作区环境仓储（风格①；``scope`` 叠加过滤）。"""

    model = OrmWorkspaceEnvironment

    def __init__(self, session: Session, scope: ScopeFilter | None = None) -> None:
        super().__init__(session, OrmWorkspaceEnvironment, scope)

    def get(self, entity_id: str) -> WorkspaceEnvironment | None:  # type: ignore[override]
        row = super().get(entity_id)
        return environment_to_domain(row) if row is not None else None

    def add(self, entity: WorkspaceEnvironment) -> WorkspaceEnvironment:  # type: ignore[override]
        row = super().add(environment_to_orm(entity))
        return environment_to_domain(row)

    def update(self, entity: WorkspaceEnvironment) -> WorkspaceEnvironment:  # type: ignore[override]
        row = super().update(environment_to_orm(entity))
        return environment_to_domain(row)

    def delete(self, entity: WorkspaceEnvironment) -> None:  # type: ignore[override]
        row = self.session.get(OrmWorkspaceEnvironment, entity.id)
        if row is not None:
            super().delete(row)

    def list(  # type: ignore[override]
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[WorkspaceEnvironment]:
        """按等值条件列出环境（``scope`` 叠加租户 / 组织 / 工作区过滤，缺省不过滤）。"""
        return [environment_to_domain(row) for row in super().list(scope=scope, **filters)]

    def list_by_workspace(
        self, workspace_id: str, *, scope: ScopeFilter | None = None
    ) -> builtins.list[WorkspaceEnvironment]:
        """列出某 Workspace 下的全部环境（按名称升序；``scope`` 叠加过滤）。"""
        statement: Select[Any] = select(OrmWorkspaceEnvironment).where(
            OrmWorkspaceEnvironment.workspace_id == workspace_id
        )
        statement = self._apply_scope(statement, scope if scope is not None else self.scope)
        statement = statement.order_by(OrmWorkspaceEnvironment.name.asc())
        rows = self.session.execute(statement).scalars().all()
        return [environment_to_domain(row) for row in rows]

    def get_by_name(
        self, workspace_id: str, name: str, *, scope: ScopeFilter | None = None
    ) -> WorkspaceEnvironment | None:
        """按 ``(workspace_id, name)`` 获取环境（唯一键语义），不存在返回 ``None``。"""
        statement: Select[Any] = select(OrmWorkspaceEnvironment).where(
            OrmWorkspaceEnvironment.workspace_id == workspace_id,
            OrmWorkspaceEnvironment.name == name,
        )
        statement = self._apply_scope(statement, scope if scope is not None else self.scope)
        row = self.session.execute(statement).scalars().first()
        return environment_to_domain(row) if row is not None else None
