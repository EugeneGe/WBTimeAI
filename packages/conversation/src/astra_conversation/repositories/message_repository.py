"""``SqlMessageRepository``（实现领域 ``MessageRepository``）。

🔴 落在 Conversation 组**能力包**本包 ``repositories/``（W5 架构裁定 Q1 = 方案 B）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import session_scope
from astra_database.models.conversation import Message as OrmMessage
from astra_domain import Message
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..mappers import message_to_domain, message_to_orm

__all__ = ["SqlMessageRepository"]


class SqlMessageRepository:
    """基于 SQLAlchemy 的消息仓储（``message`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> Message | None:
        """按主键获取消息，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMessage, entity_id)
            return message_to_domain(row) if row is not None else None

    def add(self, entity: Message) -> Message:
        """新增消息并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = message_to_orm(entity)
            session.add(row)
            session.flush()
            return message_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[Message]:
        """按等值条件列出消息。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmMessage)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmMessage, field) == value)
            rows = session.execute(statement).scalars().all()
            return [message_to_domain(row) for row in rows]

    def update(self, entity: Message) -> Message:
        """更新消息并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMessage, entity.id)
            if row is None:
                return message_to_domain(message_to_orm(entity))
            row.role = entity.role
            row.content = entity.content
            row.content_parts = list(entity.content_parts or []) or None
            row.token_count = entity.token_count
            row.run_id = entity.run_id
            session.flush()
            return message_to_domain(row)

    def delete(self, entity: Message) -> None:
        """删除消息。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmMessage, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_conversation(self, conversation_id: str) -> builtins.list[Message]:
        """按创建顺序列出某会话的全部消息。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmMessage)
                .where(OrmMessage.conversation_id == conversation_id)
                .order_by(OrmMessage.created_at.asc(), OrmMessage.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [message_to_domain(row) for row in rows]

    def list_by_run(self, run_id: str) -> builtins.list[Message]:
        """按创建顺序列出某 Run 的全部消息。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmMessage)
                .where(OrmMessage.run_id == run_id)
                .order_by(OrmMessage.created_at.asc(), OrmMessage.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [message_to_domain(row) for row in rows]
