"""``SqlUserRepository``（实现领域 ``UserRepository``）。"""

from __future__ import annotations

from typing import Any

from astra_database import BaseRepository
from astra_database.models.identity import User as OrmUser
from astra_domain import User
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..mappers import user_to_domain, user_to_orm

__all__ = ["SqlUserRepository"]


class SqlUserRepository(BaseRepository[OrmUser]):
    """基于 SQLAlchemy 的用户仓储。"""

    model = OrmUser

    def __init__(self, session: Session) -> None:
        super().__init__(session, OrmUser)

    def get(self, entity_id: str) -> User | None:  # type: ignore[override]
        row = super().get(entity_id)
        return user_to_domain(row) if row is not None else None

    def get_by_username(self, tenant_id: str, username: str) -> User | None:
        statement = select(OrmUser).where(
            OrmUser.tenant_id == tenant_id, OrmUser.username == username
        )
        row = self.session.execute(statement).scalar_one_or_none()
        return user_to_domain(row) if row is not None else None

    def get_by_email(self, tenant_id: str, email: str) -> User | None:
        statement = select(OrmUser).where(OrmUser.tenant_id == tenant_id, OrmUser.email == email)
        row = self.session.execute(statement).scalar_one_or_none()
        return user_to_domain(row) if row is not None else None

    def add(self, entity: User) -> User:  # type: ignore[override]
        row = super().add(user_to_orm(entity))
        return user_to_domain(row)

    def list(self, **filters: Any) -> list[User]:  # type: ignore[override]
        return [user_to_domain(row) for row in super().list(**filters)]

    def update(self, entity: User) -> User:  # type: ignore[override]
        row = super().update(user_to_orm(entity))
        return user_to_domain(row)

    def delete(self, entity: User) -> None:  # type: ignore[override]
        row = self.session.get(OrmUser, entity.id)
        if row is not None:
            super().delete(row)
