"""``SqlResourcePermissionRepository``（实现领域 ``ResourcePermissionRepository``）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03）；上层经**领域 Protocol** 依赖它。

🔴 **类型级（``resource_id IS NULL``）去重**：SQL 唯一约束**不判重 NULL**，故 ``upsert`` 以
   6 键（含 ``resource_id IS NULL`` 判定）在**应用层**做幂等 upsert（W3 裁定 §1.1）。
"""

from __future__ import annotations

from astra_domain import ResourcePermission
from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session, sessionmaker

from ..models.permission import ResourcePermission as OrmResourcePermission
from ..session import session_scope

__all__ = ["SqlResourcePermissionRepository"]


def _to_entity(row: OrmResourcePermission) -> ResourcePermission:
    """ORM 行 → 领域实体。"""
    return ResourcePermission(
        id=row.id,
        tenant_id=row.tenant_id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        action=row.action,
        effect=row.effect,
        scope=dict(row.scope or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_row(permission: ResourcePermission) -> OrmResourcePermission:
    """领域实体 → 新 ORM 行。"""
    return OrmResourcePermission(
        id=permission.id,
        tenant_id=permission.tenant_id,
        subject_type=permission.subject_type,
        subject_id=permission.subject_id,
        resource_type=permission.resource_type,
        resource_id=permission.resource_id,
        action=permission.action,
        effect=permission.effect,
        scope=dict(permission.scope or {}),
    )


def _resource_id_condition(resource_id: str | None) -> ColumnElement[bool]:
    """构造 ``resource_id`` 匹配条件（``NULL`` 用 ``IS NULL``）。"""
    if resource_id is None:
        return OrmResourcePermission.resource_id.is_(None)
    return OrmResourcePermission.resource_id == resource_id


class SqlResourcePermissionRepository:
    """基于 SQLAlchemy 的资源权限仓储（``resource_permission`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, permission_id: str) -> ResourcePermission | None:
        """按主键获取权限条目。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmResourcePermission, permission_id)
            return _to_entity(row) if row is not None else None

    def add(self, permission: ResourcePermission) -> ResourcePermission:
        """新增一条权限条目并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = _to_row(permission)
            session.add(row)
            session.flush()
            return _to_entity(row)

    def upsert(self, permission: ResourcePermission) -> ResourcePermission:
        """按 6 键**幂等**新增或更新（类型级 NULL 亦适用）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmResourcePermission).where(
                OrmResourcePermission.tenant_id == permission.tenant_id,
                OrmResourcePermission.subject_type == permission.subject_type,
                OrmResourcePermission.subject_id == permission.subject_id,
                OrmResourcePermission.resource_type == permission.resource_type,
                _resource_id_condition(permission.resource_id),
                OrmResourcePermission.action == permission.action,
            )
            existing = session.execute(statement).scalars().first()
            if existing is None:
                row = _to_row(permission)
                session.add(row)
                session.flush()
                return _to_entity(row)
            existing.effect = permission.effect
            existing.scope = dict(permission.scope or {})
            session.flush()
            return _to_entity(existing)

    def list_for_subject(
        self, tenant_id: str, subject_type: str, subject_id: str
    ) -> list[ResourcePermission]:
        """列出某主体在租户下的全部权限条目。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmResourcePermission)
                .where(
                    OrmResourcePermission.tenant_id == tenant_id,
                    OrmResourcePermission.subject_type == subject_type,
                    OrmResourcePermission.subject_id == subject_id,
                )
                .order_by(OrmResourcePermission.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [_to_entity(row) for row in rows]

    def list_by_resource(
        self, tenant_id: str, resource_type: str, resource_id: str
    ) -> list[ResourcePermission]:
        """列出某租户下、某 ``resource_type`` × ``resource_id`` 的全部权限条目。

        **与主体无关**（跨 subject 聚合）；命中既有索引 ``ix_resource_permission_resource``
        （W3 / T2-13 补丁 · 裁定 §21.4 X1/X2）。
        """
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmResourcePermission)
                .where(
                    OrmResourcePermission.tenant_id == tenant_id,
                    OrmResourcePermission.resource_type == resource_type,
                    _resource_id_condition(resource_id),
                )
                .order_by(OrmResourcePermission.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [_to_entity(row) for row in rows]

    def delete(self, permission_id: str) -> None:
        """删除一条权限条目。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmResourcePermission, permission_id)
            if row is not None:
                session.delete(row)
