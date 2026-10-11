"""``SqlTenantRepository``（实现领域 ``TenantRepository``）。"""

from __future__ import annotations

from typing import Any

from astra_database import BaseRepository
from astra_database.models.identity import Tenant as OrmTenant
from astra_domain import Tenant, TenantRepository
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..mappers import tenant_to_domain, tenant_to_orm

__all__ = ["SqlTenantRepository"]


class SqlTenantRepository(BaseRepository[OrmTenant]):
    """基于 SQLAlchemy 的租户仓储（领域实体 ⇆ ORM 行）。"""

    model = OrmTenant

    def __init__(self, session: Session) -> None:
        super().__init__(session, OrmTenant)

    def get(self, entity_id: str) -> Tenant | None:  # type: ignore[override]
        row = super().get(entity_id)
        return tenant_to_domain(row) if row is not None else None

    def get_by_slug(self, slug: str) -> Tenant | None:
        statement = select(OrmTenant).where(OrmTenant.slug == slug)
        row = self.session.execute(statement).scalar_one_or_none()
        return tenant_to_domain(row) if row is not None else None

    def add(self, entity: Tenant) -> Tenant:  # type: ignore[override]
        row = super().add(tenant_to_orm(entity))
        return tenant_to_domain(row)

    def list(self, **filters: Any) -> list[Tenant]:  # type: ignore[override]
        return [tenant_to_domain(row) for row in super().list(**filters)]

    def update(self, entity: Tenant) -> Tenant:  # type: ignore[override]
        row = super().update(tenant_to_orm(entity))
        return tenant_to_domain(row)

    def delete(self, entity: Tenant) -> None:  # type: ignore[override]
        row = self.session.get(OrmTenant, entity.id)
        if row is not None:
            super().delete(row)


# 运行时结构校验（Protocol 一致性由 mypy 负责）。
_ = TenantRepository
