"""``SqlPluginRepository``（实现领域 ``PluginRepository``）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03）；上层经**领域 Protocol** 依赖它，
   不在 Router / application 内 import SQLAlchemy（N-8）。

🔴 会话口径：本仓储持 **会话工厂**（``sessionmaker``），每次调用经
   :func:`astra_database.session.session_scope` 开**独立事务**——与
   ``SqlResourcePermissionRepository`` / ``SqlAuditRepository`` **同型**
   （W3 / T2-17）。
"""

from __future__ import annotations

from astra_domain import PluginRecord
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models.plugin import Plugin as OrmPlugin
from ..session import session_scope

__all__ = ["SqlPluginRepository"]


def _to_record(row: OrmPlugin) -> PluginRecord:
    """ORM 行 → 领域记录。"""
    return PluginRecord(
        id=row.id,
        name=row.name,
        version=row.version,
        kind=row.kind,
        entry_point=row.entry_point,
        permissions=list(row.permissions or []),
        manifest=dict(row.manifest or {}),
        status=row.status,
        installed_at=row.installed_at,
    )


def _to_row(record: PluginRecord) -> OrmPlugin:
    """领域记录 → 新 ORM 行。"""
    return OrmPlugin(
        id=record.id,
        name=record.name,
        version=record.version,
        kind=record.kind,
        entry_point=record.entry_point,
        permissions=list(record.permissions or []),
        manifest=dict(record.manifest or {}),
        status=record.status,
        installed_at=record.installed_at,
    )


class SqlPluginRepository:
    """基于 SQLAlchemy 的插件仓储（``plugin`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, record: PluginRecord) -> PluginRecord:
        """新增（安装）插件并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = _to_row(record)
            session.add(row)
            session.flush()
            return _to_record(row)

    def get(self, plugin_id: str) -> PluginRecord | None:
        """按 id 获取插件，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmPlugin, plugin_id)
            return _to_record(row) if row is not None else None

    def get_by_name(self, name: str) -> PluginRecord | None:
        """按 ``name`` 取插件（全局唯一），不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.execute(select(OrmPlugin).where(OrmPlugin.name == name)).scalars().first()
            return _to_record(row) if row is not None else None

    def list_all(self) -> list[PluginRecord]:
        """列出全部插件（按 ``name`` 升序）。"""
        with session_scope(self._session_factory) as session:
            rows = session.execute(select(OrmPlugin).order_by(OrmPlugin.name.asc())).scalars().all()
            return [_to_record(row) for row in rows]

    def delete(self, plugin_id: str) -> None:
        """删除（卸载）插件（幂等：不存在不报错）。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmPlugin, plugin_id)
            if row is not None:
                session.delete(row)
                session.flush()
