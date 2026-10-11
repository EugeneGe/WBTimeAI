"""``SqlToolCallRepository``（实现领域 ``ToolCallRepository``）。

🔴 落在 Conversation 组**能力包**本包 ``repositories/``（W5 架构裁定 Q1 = 方案 B）。

**重试新行（R-09，§5 #4）**：失败重试产生**新的** ``tool_call`` 行（``attempt`` 递增），
**不覆盖**原行——由 :meth:`next_attempt` 提供下一次尝试序号，写入方（Runtime
``ExecutionManager``）据此 ``add`` 新行。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import session_scope
from astra_database.models.conversation import ToolCall as OrmToolCall
from astra_domain import ToolCall
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..mappers import tool_call_to_domain, tool_call_to_orm

__all__ = ["SqlToolCallRepository"]


class SqlToolCallRepository:
    """基于 SQLAlchemy 的工具调用仓储（``tool_call`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> ToolCall | None:
        """按主键获取工具调用，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmToolCall, entity_id)
            return tool_call_to_domain(row) if row is not None else None

    def add(self, entity: ToolCall) -> ToolCall:
        """新增工具调用（**每次尝试一行**）并返回。"""
        with session_scope(self._session_factory) as session:
            row = tool_call_to_orm(entity)
            session.add(row)
            session.flush()
            return tool_call_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[ToolCall]:
        """按等值条件列出工具调用。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmToolCall)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmToolCall, field) == value)
            rows = session.execute(statement).scalars().all()
            return [tool_call_to_domain(row) for row in rows]

    def update(self, entity: ToolCall) -> ToolCall:
        """更新工具调用并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmToolCall, entity.id)
            if row is None:
                return tool_call_to_domain(tool_call_to_orm(entity))
            row.tool_id = entity.tool_id
            row.tool_name = entity.tool_name
            row.tool_type = entity.tool_type
            row.tool_ref = dict(entity.tool_ref or {}) or None
            row.attempt = entity.attempt
            row.trace_id = entity.trace_id
            row.span_id = entity.span_id
            row.input = dict(entity.input or {}) or None
            row.output = dict(entity.output) if entity.output is not None else None
            row.status = entity.status
            row.duration_ms = entity.duration_ms
            row.sandbox_session_id = entity.sandbox_session_id
            row.error = entity.error
            session.flush()
            return tool_call_to_domain(row)

    def delete(self, entity: ToolCall) -> None:
        """删除工具调用。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmToolCall, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_run(self, run_id: str) -> builtins.list[ToolCall]:
        """列出某 Run 下的全部工具调用（按创建时间升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmToolCall)
                .where(OrmToolCall.run_id == run_id)
                .order_by(OrmToolCall.created_at.asc(), OrmToolCall.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [tool_call_to_domain(row) for row in rows]

    def next_attempt(self, run_id: str, tool_name: str) -> int:
        """返回某 Run 下某工具的**下一次**尝试序号（首调返回 ``1``）。"""
        with session_scope(self._session_factory) as session:
            current = session.execute(
                select(func.max(OrmToolCall.attempt)).where(
                    OrmToolCall.run_id == run_id,
                    OrmToolCall.tool_name == tool_name,
                )
            ).scalar()
            return int(current or 0) + 1
