"""``TenantService``（租户建立 / 查询）。"""

from __future__ import annotations

from astra_database import session_scope
from astra_domain import DEFAULT_TENANT_NAME, DEFAULT_TENANT_SLUG, Tenant
from sqlalchemy.orm import Session, sessionmaker

from ..repositories import SqlTenantRepository

__all__ = ["TenantService"]


class TenantService:
    """租户领域服务。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_by_id(self, tenant_id: str) -> Tenant | None:
        """按 id 获取租户。"""
        with session_scope(self._session_factory) as session:
            return SqlTenantRepository(session).get(tenant_id)

    def get_by_slug(self, slug: str) -> Tenant | None:
        """按 slug 获取租户。"""
        with session_scope(self._session_factory) as session:
            return SqlTenantRepository(session).get_by_slug(slug)

    def get_default(self) -> Tenant | None:
        """获取默认租户（slug=``default``）。"""
        return self.get_by_slug(DEFAULT_TENANT_SLUG)

    def ensure_tenant(self, slug: str, name: str) -> Tenant:
        """幂等确保租户存在：存在则返回，否则创建。

        Args:
            slug: 租户 slug（唯一）。
            name: 租户显示名。

        Returns:
            既存或新建的 :class:`~astra_domain.entities.Tenant`。
        """
        with session_scope(self._session_factory) as session:
            repo = SqlTenantRepository(session)
            existing = repo.get_by_slug(slug)
            if existing is not None:
                return existing
            return repo.add(Tenant(name=name, slug=slug))

    def ensure_default(self) -> Tenant:
        """幂等确保默认租户存在。"""
        return self.ensure_tenant(DEFAULT_TENANT_SLUG, DEFAULT_TENANT_NAME)
