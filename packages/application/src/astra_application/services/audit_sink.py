"""审计写入通道（``AuditSink``）：写库 + 降级落盘。

设计 §2.18.2：写入失败**不得静默丢弃**，降级链「写库 → 本地落盘 → ERROR 日志」。

- :class:`AuditSink`：写入协议（写库 / 落盘的统一抽象）。
- :class:`SqlAuditSink`：写库实现 —— 通过注入的
  :class:`~astra_domain.repositories.audit_repository.AuditRepository`（**领域 Protocol**）
  落库，**不**在本层 import ORM / SQLAlchemy（分层纪律，C-03）。
- :class:`SpoolAuditSink`：降级落盘实现。

SQLAlchemy 具体仓储位于 ``astra_database.repositories``，由组合根装配注入。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import AuditLog, AuditRepository

from .audit_spool import AuditSpool

__all__ = ["AuditSink", "SqlAuditSink", "SpoolAuditSink"]


@runtime_checkable
class AuditSink(Protocol):
    """审计写入通道协议。"""

    def write(self, record: AuditLog) -> None:
        """写入一条审计记录（失败应抛出异常，交由上层降级处理）。"""
        ...


class SqlAuditSink:
    """写库实现：委托领域 :class:`AuditRepository` 落 ``audit_log``。"""

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    @property
    def repository(self) -> AuditRepository:
        """返回底层仓储（供重放复用）。"""
        return self._repository

    def write(self, record: AuditLog) -> None:
        """写入一条审计记录（异常向上传播，触发降级）。"""
        self._repository.add(record)


class SpoolAuditSink:
    """降级落盘实现：把记录追加写入本地 spool 文件。"""

    def __init__(self, spool: AuditSpool) -> None:
        self._spool = spool

    @property
    def spool(self) -> AuditSpool:
        """返回底层 spool。"""
        return self._spool

    def write(self, record: AuditLog) -> None:
        """将审计记录落盘（异常向上传播，触发更高层兜底）。"""
        self._spool.write(record)
