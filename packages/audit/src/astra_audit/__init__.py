"""Astra AI 审计抽象包（``astra_audit``）。

设计 §2.15.1 / §2.18（修订 R-14）：``AuditSink`` Protocol + 写库实现 ``RepositoryAuditSink``。

- 包性质：**抽象包（零 ORM）**——不得 import ``sqlalchemy`` / ``alembic`` /
  ``astra_database``（W1 裁定 §2.2 / §2.3）；落库经**注入** ``AuditRepository``
  （已在 ``astra_domain``，Phase 1 已落 ``audit_log`` 表 / C2-05），本包**零 ORM**；
- W3 / T2-17：新增 :mod:`astra_audit.sink`（``AuditSink`` + ``RepositoryAuditSink``；
  写库失败 → 本地落盘 + 告警，**不静默丢弃**）。
"""

from __future__ import annotations

from .sink import (
    FALLBACK_DIR_ENV,
    AuditSink,
    RepositoryAuditSink,
    resolve_fallback_dir,
)

__all__ = [
    "AuditSink",
    "RepositoryAuditSink",
    "resolve_fallback_dir",
    "FALLBACK_DIR_ENV",
]
