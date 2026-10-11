"""``SqlWorkspaceRepository``（实现领域 ``WorkspaceRepository``）。

复用 ``astra_database.BaseRepository``；工作区 ORM 模型已在
``astra_database.models.workspace`` 就位（W3 **不新增迁移**）。
"""

from __future__ import annotations

from typing import Any

from astra_database import BaseRepository
from astra_database.models.workspace import Workspace as OrmWorkspace
from astra_domain import ScopeFilter, Workspace
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..mappers import workspace_to_domain, workspace_to_orm

__all__ = ["SqlWorkspaceRepository"]


class SqlWorkspaceRepository(BaseRepository[OrmWorkspace]):
    """基于 SQLAlchemy 的工作区仓储（领域实体 ⇆ ORM 行）。"""

    model = OrmWorkspace

    def __init__(self, session: Session, scope: ScopeFilter | None = None) -> None:
        super().__init__(session, OrmWorkspace, scope)

    def get(self, entity_id: str) -> Workspace | None:  # type: ignore[override]
        row = super().get(entity_id)
        return workspace_to_domain(row) if row is not None else None

    def list_by_tenant(self, tenant_id: str) -> list[Workspace]:
        """列出某租户下的全部工作区（多租户隔离）。"""
        statement = (
            select(OrmWorkspace)
            .where(OrmWorkspace.tenant_id == tenant_id)
            .order_by(OrmWorkspace.created_at.asc())
        )
        rows = self.session.execute(statement).scalars().all()
        return [workspace_to_domain(row) for row in rows]

    def get_by_owner(self, tenant_id: str, owner_id: str) -> list[Workspace]:
        """列出某租户下某拥有者的全部工作区。"""
        statement = select(OrmWorkspace).where(
            OrmWorkspace.tenant_id == tenant_id,
            OrmWorkspace.owner_id == owner_id,
        )
        rows = self.session.execute(statement).scalars().all()
        return [workspace_to_domain(row) for row in rows]

    def add(self, entity: Workspace) -> Workspace:  # type: ignore[override]
        row = super().add(workspace_to_orm(entity))
        return workspace_to_domain(row)

    def list(  # type: ignore[override]
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> list[Workspace]:
        """按等值条件列出工作区（``scope`` 叠加租户 / 组织 / 工作区过滤，缺省不过滤）。"""
        return [workspace_to_domain(row) for row in super().list(scope=scope, **filters)]

    def update(self, entity: Workspace) -> Workspace:  # type: ignore[override]
        row = super().update(workspace_to_orm(entity))
        return workspace_to_domain(row)

    def delete(self, entity: Workspace) -> None:  # type: ignore[override]
        row = self.session.get(OrmWorkspace, entity.id)
        if row is not None:
            super().delete(row)
