"""``SqlSessionRepository``（实现领域 ``SessionRepository``）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from astra_database.models.auth import UserSession as OrmUserSession
from astra_domain import SessionRecord
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

__all__ = ["SqlSessionRepository"]


def _to_record(row: OrmUserSession) -> SessionRecord:
    return SessionRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        device=row.device,
        ip_address=row.ip_address,
        user_agent=row.user_agent,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


class SqlSessionRepository:
    """基于 SQLAlchemy 的会话仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: SessionRecord) -> SessionRecord:
        row = OrmUserSession(
            id=record.id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            device=record.device,
            ip_address=record.ip_address,
            user_agent=record.user_agent,
            expires_at=record.expires_at,
        )
        self.session.add(row)
        self.session.flush()
        return _to_record(row)

    def get(self, session_id: str) -> SessionRecord | None:
        row = self.session.get(OrmUserSession, session_id)
        return _to_record(row) if row is not None else None

    def list_by_user(self, user_id: str) -> list[SessionRecord]:
        statement = (
            select(OrmUserSession)
            .where(OrmUserSession.user_id == user_id)
            .order_by(OrmUserSession.created_at.desc())
        )
        return [_to_record(row) for row in self.session.execute(statement).scalars().all()]

    def revoke(self, session_id: str, *, revoked_at: datetime) -> None:
        self.session.execute(
            update(OrmUserSession)
            .where(OrmUserSession.id == session_id, OrmUserSession.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        self.session.flush()

    def revoke_all_for_user(self, user_id: str, *, revoked_at: datetime) -> int:
        result = cast(
            "CursorResult[Any]",
            self.session.execute(
                update(OrmUserSession)
                .where(OrmUserSession.user_id == user_id, OrmUserSession.revoked_at.is_(None))
                .values(revoked_at=revoked_at)
            ),
        )
        self.session.flush()
        return int(result.rowcount or 0)
