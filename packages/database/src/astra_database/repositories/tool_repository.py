"""``SqlToolRepository``（实现领域 ``ToolRepository`` / ``ToolVersionRepository``）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03）；由组合根 / 集成测试构造后，以**领域 Protocol**
   注入 ``astra_tool``（``packages/tool`` 零 ORM，W4 架构裁定 Q1 = 方案 B）。

同一类同时承载 ``tool`` 与 ``tool_version`` 两张表的读写（``add`` / ``update`` / ``delete`` 按
实体类型分派），以对齐设计“ToolVersionRepository”归属（设计 §2.15.1）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_domain import Tool, ToolVersion
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models.tool import Tool as OrmTool
from ..models.tool import ToolVersion as OrmToolVersion
from ..session import session_scope
from .tool_mappers import (
    tool_to_domain,
    tool_to_orm,
    tool_version_to_domain,
    tool_version_to_orm,
)

__all__ = ["SqlToolRepository"]


class SqlToolRepository:
    """基于 SQLAlchemy 的工具目录仓储（``tool`` / ``tool_version`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- ToolRepository ------------------------------------------------------

    def get(self, entity_id: str) -> Tool | ToolVersion | None:
        """按主键获取工具（不存在返回 ``None``）。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmTool, entity_id)
            return tool_to_domain(row) if row is not None else None

    def add(self, entity: Tool | ToolVersion) -> Tool | ToolVersion:
        """新增工具或工具版本并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            if isinstance(entity, ToolVersion):
                version_row = tool_version_to_orm(entity)
                session.add(version_row)
                session.flush()
                return tool_version_to_domain(version_row)
            row = tool_to_orm(entity)
            session.add(row)
            session.flush()
            return tool_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[Tool]:
        """按等值条件列出工具。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmTool)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmTool, field) == value)
            rows = session.execute(statement).scalars().all()
            return [tool_to_domain(row) for row in rows]

    def update(self, entity: Tool | ToolVersion) -> Tool | ToolVersion:
        """更新工具或工具版本并返回。"""
        with session_scope(self._session_factory) as session:
            if isinstance(entity, ToolVersion):
                return self._update_version(session, entity)
            row = session.get(OrmTool, entity.id)
            if row is None:
                return tool_to_domain(tool_to_orm(entity))
            row.name = entity.name
            row.display_name = entity.display_name
            row.description = entity.description
            row.category = entity.category
            row.source = entity.source
            row.input_schema = dict(entity.input_schema) if entity.input_schema else {}
            row.output_schema = dict(entity.output_schema) if entity.output_schema else {}
            row.requires_sandbox = bool(entity.requires_sandbox)
            row.status = entity.status
            row.tool_ref = dict(entity.tool_ref) if entity.tool_ref else None
            session.flush()
            return tool_to_domain(row)

    def delete(self, entity: Tool | ToolVersion) -> None:
        """删除工具或工具版本。"""
        with session_scope(self._session_factory) as session:
            row: Any
            if isinstance(entity, ToolVersion):
                row = session.get(OrmToolVersion, entity.id)
            else:
                row = session.get(OrmTool, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def get_by_name(self, name: str, tenant_id: str | None = None) -> Tool | None:
        """按名获取工具（``tenant_id=None`` 表示全局内置工具）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmTool).where(OrmTool.name == name)
            if tenant_id is None:
                statement = statement.where(OrmTool.tenant_id.is_(None))
            else:
                statement = statement.where(OrmTool.tenant_id == tenant_id)
            row = session.execute(statement).scalars().first()
            return tool_to_domain(row) if row is not None else None

    def list_builtin(self) -> builtins.list[Tool]:
        """列出全部全局内置工具（``tenant_id IS NULL``）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmTool).where(OrmTool.tenant_id.is_(None)).order_by(OrmTool.name.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [tool_to_domain(row) for row in rows]

    # -- ToolVersionRepository ----------------------------------------------

    def list_by_tool(self, tool_id: str) -> builtins.list[ToolVersion]:
        """列出某工具的全部规格快照。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmToolVersion)
                .where(OrmToolVersion.tool_id == tool_id)
                .order_by(OrmToolVersion.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [tool_version_to_domain(row) for row in rows]

    # -- 内部 ---------------------------------------------------------------

    def _update_version(self, session: Session, entity: ToolVersion) -> ToolVersion:
        """更新一条工具版本行。"""
        row = session.get(OrmToolVersion, entity.id)
        if row is None:
            return tool_version_to_domain(tool_version_to_orm(entity))
        row.tool_id = entity.tool_id
        row.version = entity.version
        row.spec = dict(entity.spec) if entity.spec else {}
        session.flush()
        return tool_version_to_domain(row)
