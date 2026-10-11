"""``SqlModelRepository``（实现领域 ``ModelRepository``）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03）；由组合根 / 集成测试构造后，
   以**领域 Protocol** 注入 ``ModelCatalogService``（``packages/model`` 零 ORM）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_domain import Model
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models.model import Model as OrmModel
from ..session import session_scope
from .model_mappers import model_to_domain, model_to_orm

__all__ = ["SqlModelRepository"]


class SqlModelRepository:
    """基于 SQLAlchemy 的模型目录仓储（``model`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, entity: Model) -> Model:
        """新增模型并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = model_to_orm(entity)
            session.add(row)
            session.flush()
            return model_to_domain(row)

    def get(self, entity_id: str) -> Model | None:
        """按主键获取模型，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmModel, entity_id)
            return model_to_domain(row) if row is not None else None

    def list(self, **filters: Any) -> builtins.list[Model]:
        """按等值条件列出模型。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmModel)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmModel, field) == value)
            rows = session.execute(statement).scalars().all()
            return [model_to_domain(row) for row in rows]

    def list_by_provider(self, provider_id: str) -> builtins.list[Model]:
        """列出某提供方下的全部模型。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmModel)
                .where(OrmModel.provider_id == provider_id)
                .order_by(OrmModel.name.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [model_to_domain(row) for row in rows]

    def update(self, entity: Model) -> Model:
        """更新模型并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmModel, entity.id)
            if row is None:
                return model_to_domain(model_to_orm(entity))
            row.provider_id = entity.provider_id
            row.name = entity.name
            row.type = entity.type
            row.context_window = entity.context_window
            row.capabilities = dict(entity.capabilities) if entity.capabilities else {}
            row.status = entity.status
            session.flush()
            return model_to_domain(row)

    def delete(self, entity: Model) -> None:
        """删除模型。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmModel, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()
