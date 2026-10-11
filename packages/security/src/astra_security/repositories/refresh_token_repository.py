"""``SqlRefreshTokenRepository``（仅存哈希 ``token_hash``）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from astra_database.models.auth import RefreshToken as OrmRefreshToken
from astra_domain import RefreshTokenRecord
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

__all__ = ["SqlRefreshTokenRepository"]


def _to_record(row: OrmRefreshToken) -> RefreshTokenRecord:
    return RefreshTokenRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        session_id=row.session_id,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


class SqlRefreshTokenRepository:
    """基于 SQLAlchemy 的 refresh token 仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: RefreshTokenRecord) -> RefreshTokenRecord:
        row = OrmRefreshToken(
            id=record.id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            session_id=record.session_id,
            token_hash=record.token_hash,
            expires_at=record.expires_at,
        )
        self.session.add(row)
        self.session.flush()
        return _to_record(row)

    def get_by_hash(self, token_hash: str) -> RefreshTokenRecord | None:
        statement = select(OrmRefreshToken).where(OrmRefreshToken.token_hash == token_hash)
        row = self.session.execute(statement).scalar_one_or_none()
        return _to_record(row) if row is not None else None

    def revoke(self, token_id: str, *, revoked_at: datetime) -> None:
        self.session.execute(
            update(OrmRefreshToken)
            .where(OrmRefreshToken.id == token_id, OrmRefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        self.session.flush()

    def revoke_by_session(self, session_id: str, *, revoked_at: datetime) -> int:
        result = cast(
            "CursorResult[Any]",
            self.session.execute(
                update(OrmRefreshToken)
                .where(
                    OrmRefreshToken.session_id == session_id, OrmRefreshToken.revoked_at.is_(None)
                )
                .values(revoked_at=revoked_at)
            ),
        )
        self.session.flush()
        return int(result.rowcount or 0)

    def revoke_all_for_user(self, user_id: str, *, revoked_at: datetime) -> int:
        result = cast(
            "CursorResult[Any]",
            self.session.execute(
                update(OrmRefreshToken)
                .where(OrmRefreshToken.user_id == user_id, OrmRefreshToken.revoked_at.is_(None))
                .values(revoked_at=revoked_at)
            ),
        )
        self.session.flush()
        return int(result.rowcount or 0)
