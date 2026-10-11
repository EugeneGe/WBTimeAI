"""``SqlApprovalRepository``（实现领域 ``ApprovalRepository``；W4 / T2-26，**零迁移**）。

- 表 ``approval`` 随迁移 ``0010``（2a）建——**不重建**；
- 复用 ``astra_database.BaseRepository`` 骨架（``add`` / ``get``）；
- **会话自管理**：以 ``session_factory`` 构造（长生命周期 / 单例安全），
  每次操作在 ``session_scope`` 内开启独立事务——与 ``astra_workflow`` 组仓储约定一致。
"""

from __future__ import annotations

from astra_database import BaseRepository, session_scope
from astra_database.models.approval import Approval as OrmApproval
from astra_domain import Approval, ApprovalStatus
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

__all__ = ["SqlApprovalRepository"]


def _to_domain(row: OrmApproval) -> Approval:
    """ORM 行 → 领域实体。"""
    return Approval(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        subject_type=row.subject_type,
        subject_ref=row.subject_ref,
        requested_by=row.requested_by,
        status=row.status,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        payload=dict(row.payload or {}),
        expires_at=row.expires_at,
    )


def _to_orm(approval: Approval) -> OrmApproval:
    """领域实体 → ORM 行（**新增**用）。"""
    return OrmApproval(
        id=approval.id,
        tenant_id=approval.tenant_id or "",
        subject_type=approval.subject_type,
        subject_ref=approval.subject_ref,
        requested_by=approval.requested_by,
        status=str(approval.status),
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        payload=dict(approval.payload or {}),
        expires_at=approval.expires_at,
    )


def _apply(row: OrmApproval, approval: Approval) -> None:
    """把领域实体字段写回既有 ORM 行（**更新**用；``id`` / ``created_at`` 不动）。"""
    row.tenant_id = approval.tenant_id or ""
    row.subject_type = approval.subject_type
    row.subject_ref = approval.subject_ref
    row.requested_by = approval.requested_by
    row.status = str(approval.status)
    row.decided_by = approval.decided_by
    row.decided_at = approval.decided_at
    row.payload = dict(approval.payload or {})
    row.expires_at = approval.expires_at


class SqlApprovalRepository:
    """基于 SQLAlchemy 的审批仓储（``approval`` 表；**会话自管理**）。"""

    model = OrmApproval

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """初始化。

        Args:
            session_factory: SQLAlchemy 会话工厂（由组合根提供）。
        """
        self._session_factory = session_factory

    def add(self, approval: Approval) -> Approval:
        """新增审批记录并返回领域实体。"""
        with session_scope(self._session_factory) as session:
            row = BaseRepository(session, OrmApproval).add(_to_orm(approval))
            return _to_domain(row)

    def get(self, approval_id: str) -> Approval | None:
        """按主键获取审批记录，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = BaseRepository(session, OrmApproval).get(approval_id)
            return _to_domain(row) if row is not None else None

    def update(self, approval: Approval) -> Approval:
        """更新审批记录并返回（不存在则新增）。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmApproval, approval.id)
            if row is None:
                row = _to_orm(approval)
                session.add(row)
            else:
                _apply(row, approval)
            session.flush()
            return _to_domain(row)

    def list_pending(self, *, tenant_id: str | None = None) -> list[Approval]:
        """列出待决议（``PENDING``）的审批记录（按 ``created_at`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmApproval).where(OrmApproval.status == str(ApprovalStatus.PENDING))
            if tenant_id is not None:
                statement = statement.where(OrmApproval.tenant_id == tenant_id)
            statement = statement.order_by(OrmApproval.created_at.asc())
            rows = session.execute(statement).scalars().all()
            return [_to_domain(row) for row in rows]

    def get_by_subject_ref(self, *, subject_type: str, subject_ref: str) -> Approval | None:
        """取 ``(subject_type, subject_ref)`` 的最近一条审批记录（``created_at`` 降序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmApproval)
                .where(
                    OrmApproval.subject_type == subject_type,
                    OrmApproval.subject_ref == subject_ref,
                )
                .order_by(OrmApproval.created_at.desc(), OrmApproval.id.desc())
                .limit(1)
            )
            row = session.execute(statement).scalars().first()
            return _to_domain(row) if row is not None else None
