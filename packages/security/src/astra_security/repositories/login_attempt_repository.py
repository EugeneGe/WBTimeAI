"""``SqlLoginAttemptRepository``。"""

from __future__ import annotations

from astra_database.models.auth import LoginAttempt as OrmLoginAttempt
from astra_domain import LoginAttemptRecord
from sqlalchemy import select
from sqlalchemy.orm import Session

__all__ = ["SqlLoginAttemptRepository"]


def _to_record(row: OrmLoginAttempt) -> LoginAttemptRecord:
    return LoginAttemptRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        username=row.username,
        ip_address=row.ip_address,
        success=row.success,
        created_at=row.created_at,
    )


class SqlLoginAttemptRepository:
    """基于 SQLAlchemy 的登录尝试仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: LoginAttemptRecord) -> LoginAttemptRecord:
        row = OrmLoginAttempt(
            id=record.id,
            tenant_id=record.tenant_id,
            username=record.username,
            ip_address=record.ip_address,
            success=record.success,
        )
        self.session.add(row)
        self.session.flush()
        return _to_record(row)

    def recent_for_username(
        self, username: str, *, limit: int = 20, tenant_id: str | None = None
    ) -> list[LoginAttemptRecord]:
        statement = select(OrmLoginAttempt).where(OrmLoginAttempt.username == username)
        if tenant_id is not None:
            statement = statement.where(OrmLoginAttempt.tenant_id == tenant_id)
        statement = statement.order_by(OrmLoginAttempt.created_at.desc()).limit(limit)
        return [_to_record(row) for row in self.session.execute(statement).scalars().all()]
