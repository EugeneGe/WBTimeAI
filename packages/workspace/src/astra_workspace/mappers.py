"""ORM 行 ↔ 领域 ``Workspace`` 映射。

将 ``astra_database.models.workspace.Workspace`` 的 SQLAlchemy 行转换为
``astra_domain`` 的 :class:`~astra_domain.entities.workspace.Workspace`（及反向），
使领域层保持零框架依赖。
"""

from __future__ import annotations

from astra_common.time import utcnow
from astra_database.models.workspace import Workspace as OrmWorkspace
from astra_domain import Workspace

__all__ = ["workspace_to_domain", "workspace_to_orm"]


def _dt(value: object):
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


def workspace_to_domain(row: OrmWorkspace) -> Workspace:
    """ORM 工作区行 → 领域 ``Workspace``。"""
    return Workspace(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
        owner_id=row.owner_id,
        name=row.name,
        workspace_type=row.workspace_type,
        settings=dict(row.settings) if row.settings else {},
        config=dict(row.config) if row.config else {},
    )


def workspace_to_orm(entity: Workspace) -> OrmWorkspace:
    """领域 ``Workspace`` → ORM 行。"""
    return OrmWorkspace(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        owner_id=entity.owner_id,
        name=entity.name,
        workspace_type=str(entity.workspace_type),
        settings=dict(entity.settings) if entity.settings else {},
        config=dict(entity.config) if entity.config else {},
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )
