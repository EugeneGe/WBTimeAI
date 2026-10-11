"""审计仓储接口（**仅 Protocol**，零 ORM，C-03）。

对应 ORM 表：``audit_log``。SQLAlchemy 实现位于 ``astra_database.repositories``。

🔴 ``add`` 记录中的 ``metadata`` 必须**已脱敏**（无明文凭证 / 密钥）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities.audit import AuditLog

__all__ = ["AuditRepository"]


@runtime_checkable
class AuditRepository(Protocol):
    """基础审计仓储接口。"""

    def add(self, record: AuditLog) -> AuditLog:
        """写入一条审计记录并返回。"""
        ...

    def exists_request_id(self, request_id: str) -> bool:
        """判断某 ``request_id`` 是否已入库（重放幂等去重）。"""
        ...

    def list_by_tenant(self, tenant_id: str, *, limit: int = 100) -> list[AuditLog]:
        """按创建时间倒序列出某租户的审计记录。"""
        ...
