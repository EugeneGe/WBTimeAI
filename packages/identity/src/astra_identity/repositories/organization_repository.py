"""``SqlOrganizationRepository``（实现领域 ``OrganizationRepository``）。"""

from __future__ import annotations

from typing import Any

from astra_database import BaseRepository
from astra_database.models.identity import Organization as OrmOrganization
from astra_domain import Organization
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..mappers import organization_to_domain, organization_to_orm

__all__ = ["SqlOrganizationRepository"]


class SqlOrganizationRepository(BaseRepository[OrmOrganization]):
    """基于 SQLAlchemy 的组织仓储。"""

    model = OrmOrganization

    def __init__(self, session: Session) -> None:
        super().__init__(session, OrmOrganization)

    def get(self, entity_id: str) -> Organization | None:  # type: ignore[override]
        row = super().get(entity_id)
        return organization_to_domain(row) if row is not None else None

    def get_by_slug(self, tenant_id: str, slug: str) -> Organization | None:
        statement = select(OrmOrganization).where(
            OrmOrganization.tenant_id == tenant_id, OrmOrganization.slug == slug
        )
        row = self.session.execute(statement).scalar_one_or_none()
        return organization_to_domain(row) if row is not None else None

    def add(self, entity: Organization) -> Organization:  # type: ignore[override]
        row = super().add(organization_to_orm(entity))
        return organization_to_domain(row)

    def list(self, **filters: Any) -> list[Organization]:  # type: ignore[override]
        return [organization_to_domain(row) for row in super().list(**filters)]

    def update(self, entity: Organization) -> Organization:  # type: ignore[override]
        row = super().update(organization_to_orm(entity))
        return organization_to_domain(row)

    def delete(self, entity: Organization) -> None:  # type: ignore[override]
        row = self.session.get(OrmOrganization, entity.id)
        if row is not None:
            super().delete(row)
