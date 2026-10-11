"""``SqlModelProviderRepository``（实现领域 ``ModelProviderRepository``）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03）；由组合根 / 集成测试构造后，
   以**领域 Protocol** 注入 ``ModelCatalogService``（``packages/model`` 零 ORM）。

``credential_id`` **仅存引用**（指向 ``credential.id``，C-07；不建 ``model_credential``）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_domain import ModelProvider
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models.model import ModelProvider as OrmModelProvider
from ..session import session_scope
from .model_mappers import model_provider_to_domain, model_provider_to_orm

__all__ = ["SqlModelProviderRepository"]


class SqlModelProviderRepository:
    """基于 SQLAlchemy 的模型提供方仓储（``model_provider`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, entity: ModelProvider) -> ModelProvider:
        """新增提供方并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = model_provider_to_orm(entity)
            session.add(row)
            session.flush()
            return model_provider_to_domain(row)

    def get(self, entity_id: str) -> ModelProvider | None:
        """按主键获取提供方，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmModelProvider, entity_id)
            return model_provider_to_domain(row) if row is not None else None

    def list(self, **filters: Any) -> builtins.list[ModelProvider]:
        """按等值条件列出提供方。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmModelProvider)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmModelProvider, field) == value)
            rows = session.execute(statement).scalars().all()
            return [model_provider_to_domain(row) for row in rows]

    def list_by_tenant(self, tenant_id: str) -> builtins.list[ModelProvider]:
        """列出某租户下的全部提供方（多租户隔离）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmModelProvider)
                .where(OrmModelProvider.tenant_id == tenant_id)
                .order_by(OrmModelProvider.name.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [model_provider_to_domain(row) for row in rows]

    def update(self, entity: ModelProvider) -> ModelProvider:
        """更新提供方并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmModelProvider, entity.id)
            if row is None:
                return model_provider_to_domain(model_provider_to_orm(entity))
            row.workspace_id = entity.workspace_id
            row.name = entity.name
            row.type = entity.type
            row.endpoint = entity.endpoint
            row.credential_id = entity.credential_id
            row.status = entity.status
            row.config = dict(entity.config) if entity.config else {}
            session.flush()
            return model_provider_to_domain(row)

    def delete(self, entity: ModelProvider) -> None:
        """删除提供方。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmModelProvider, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()
