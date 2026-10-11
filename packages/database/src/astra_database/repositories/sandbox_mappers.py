"""ORM 行 ↔ 领域 ``SandboxSession`` 映射。

将 ``astra_database.models.sandbox`` 的 SQLAlchemy 行转换为 ``astra_domain`` 的
:class:`~astra_domain.entities.sandbox.SandboxSession`（及反向）。

⚠️ ``sandbox_session`` 表**无** ``updated_at`` 列，故 ``to_domain`` 的 ``updated_at``
   以 ``created_at`` 回退（同 ``model_mappers`` 口径）。
"""

from __future__ import annotations

from astra_common.time import utcnow
from astra_domain import SandboxSession

from ..models.sandbox import SandboxSession as OrmSandboxSession

__all__ = ["sandbox_session_to_domain", "sandbox_session_to_orm"]


def sandbox_session_to_domain(row: OrmSandboxSession) -> SandboxSession:
    """ORM 沙箱会话行 → 领域 ``SandboxSession``。"""
    created_at = row.created_at if row.created_at is not None else utcnow()
    return SandboxSession(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=created_at,
        updated_at=getattr(row, "updated_at", None) or created_at,
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        provider=row.provider,
        image=row.image,
        status=row.status,
        container_ref=row.container_ref,
        workdir=row.workdir,
        ended_at=row.ended_at,
    )


def sandbox_session_to_orm(entity: SandboxSession) -> OrmSandboxSession:
    """领域 ``SandboxSession`` → ORM 行。"""
    return OrmSandboxSession(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        run_id=entity.run_id,
        workspace_id=entity.workspace_id,
        provider=entity.provider,
        image=entity.image,
        status=entity.status,
        container_ref=entity.container_ref,
        workdir=entity.workdir,
        ended_at=entity.ended_at,
    )
