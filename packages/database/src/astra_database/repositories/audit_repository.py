"""``SqlAuditRepository``（实现领域 ``AuditRepository``）。

🔴 落在 ``astra_database``（ORM 允许位置，C-03）；应用层经**领域 Protocol** 依赖它，
   不在 application 内 import SQLAlchemy。
"""

from __future__ import annotations

from astra_domain import AuditLog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models.audit import AuditLog as OrmAuditLog
from ..session import session_scope

__all__ = ["SqlAuditRepository"]


def _to_entity(row: OrmAuditLog) -> AuditLog:
    """ORM 行 → 领域实体。"""
    return AuditLog(
        id=row.id,
        tenant_id=row.tenant_id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        agent_id=row.agent_id,
        run_id=row.run_id,
        tool_call_id=row.tool_call_id,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        outcome=row.outcome,
        duration_ms=row.duration_ms,
        token_usage=dict(row.token_usage or {}),
        cost=row.cost,
        request_id=row.request_id,
        trace_id=row.trace_id,
        ip=row.ip,
        metadata=dict(row.metadata_ or {}),
        extensions=dict(row.extensions or {}),
        created_at=row.created_at,
    )


class SqlAuditRepository:
    """基于 SQLAlchemy 的审计仓储（``audit_log`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, record: AuditLog) -> AuditLog:
        """写入一条审计记录并返回（各自事务）。"""
        with session_scope(self._session_factory) as session:
            row = OrmAuditLog(
                id=record.id,
                tenant_id=record.tenant_id,
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                user_id=record.user_id,
                agent_id=record.agent_id,
                run_id=record.run_id,
                tool_call_id=record.tool_call_id,
                action=record.action,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                outcome=record.outcome,
                duration_ms=record.duration_ms,
                token_usage=dict(record.token_usage or {}),
                cost=record.cost,
                request_id=record.request_id,
                trace_id=record.trace_id,
                ip=record.ip,
                metadata_=dict(record.metadata or {}),
                extensions=dict(record.extensions or {}),
                created_at=record.created_at,
            )
            session.add(row)
            session.flush()
            return _to_entity(row)

    def exists_request_id(self, request_id: str) -> bool:
        """判断某 ``request_id`` 是否已入库（重放幂等去重）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmAuditLog.id).where(OrmAuditLog.request_id == request_id).limit(1)
            return session.execute(statement).first() is not None

    def list_by_tenant(self, tenant_id: str, *, limit: int = 100) -> list[AuditLog]:
        """按创建时间倒序列出某租户的审计记录。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmAuditLog)
                .where(OrmAuditLog.tenant_id == tenant_id)
                .order_by(OrmAuditLog.created_at.desc())
                .limit(limit)
            )
            rows = session.execute(statement).scalars().all()
            return [_to_entity(row) for row in rows]
