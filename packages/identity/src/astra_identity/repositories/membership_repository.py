"""``SqlMembershipRepository``（实现领域 ``MembershipRepository``）。"""

from __future__ import annotations

from typing import Any

from astra_database import BaseRepository
from astra_database.models.identity import Membership as OrmMembership
from astra_domain import Membership
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..mappers import membership_to_domain, membership_to_orm

__all__ = ["SqlMembershipRepository"]


class SqlMembershipRepository(BaseRepository[OrmMembership]):
    """基于 SQLAlchemy 的成员关系仓储。"""

    model = OrmMembership

    def __init__(self, session: Session) -> None:
        super().__init__(session, OrmMembership)

    def get(self, entity_id: str) -> Membership | None:  # type: ignore[override]
        row = super().get(entity_id)
        return membership_to_domain(row) if row is not None else None

    def list_by_user(self, user_id: str) -> list[Membership]:
        return self.list(user_id=user_id)

    def get_by_user_and_org(self, user_id: str, organization_id: str | None) -> Membership | None:
        statement = select(OrmMembership).where(
            OrmMembership.user_id == user_id,
            OrmMembership.organization_id == organization_id,
        )
        row = self.session.execute(statement).scalar_one_or_none()
        return membership_to_domain(row) if row is not None else None

    def add(self, entity: Membership) -> Membership:  # type: ignore[override]
        row = super().add(membership_to_orm(entity))
        return membership_to_domain(row)

    def list(self, **filters: Any) -> list[Membership]:  # type: ignore[override]
        return [membership_to_domain(row) for row in super().list(**filters)]

    def update(self, entity: Membership) -> Membership:  # type: ignore[override]
        row = super().update(membership_to_orm(entity))
        return membership_to_domain(row)

    def delete(self, entity: Membership) -> None:  # type: ignore[override]
        row = self.session.get(OrmMembership, entity.id)
        if row is not None:
            super().delete(row)
