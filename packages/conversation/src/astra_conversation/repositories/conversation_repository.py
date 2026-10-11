"""``SqlConversationRepository``（实现领域 ``ConversationRepository``）。

🔴 落在 Conversation 组**能力包**本包 ``repositories/``（W5 架构裁定 Q1 = 方案 B：
   能力包承载业务聚合持久化，SQL 仓储留本包）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_database import session_scope
from astra_database.models.conversation import Conversation as OrmConversation
from astra_domain import Conversation
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..mappers import conversation_to_domain, conversation_to_orm

__all__ = ["SqlConversationRepository"]


class SqlConversationRepository:
    """基于 SQLAlchemy 的会话仓储（``conversation`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> Conversation | None:
        """按主键获取会话，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmConversation, entity_id)
            return conversation_to_domain(row) if row is not None else None

    def add(self, entity: Conversation) -> Conversation:
        """新增会话并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = conversation_to_orm(entity)
            session.add(row)
            session.flush()
            return conversation_to_domain(row)

    def list(self, **filters: Any) -> builtins.list[Conversation]:
        """按等值条件列出会话。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmConversation)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmConversation, field) == value)
            rows = session.execute(statement).scalars().all()
            return [conversation_to_domain(row) for row in rows]

    def update(self, entity: Conversation) -> Conversation:
        """更新会话并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmConversation, entity.id)
            if row is None:
                return conversation_to_domain(conversation_to_orm(entity))
            row.workspace_id = entity.workspace_id
            row.agent_id = entity.agent_id
            row.user_id = entity.user_id
            row.title = entity.title
            row.status = entity.status
            session.flush()
            return conversation_to_domain(row)

    def delete(self, entity: Conversation) -> None:
        """删除会话。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmConversation, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()

    def list_by_tenant(self, tenant_id: str) -> builtins.list[Conversation]:
        """列出某租户下的全部会话（按创建时间升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmConversation)
                .where(OrmConversation.tenant_id == tenant_id)
                .order_by(OrmConversation.created_at.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [conversation_to_domain(row) for row in rows]
