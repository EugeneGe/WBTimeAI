"""Astra AI 数据库层（``astra_database``）。

- :class:`~astra_database.base.Base` / :class:`~astra_database.base.TimestampMixin`
- :class:`~astra_database.types.GUID` / :class:`~astra_database.types.JSONType`（方言适配）
- :func:`~astra_database.engine.create_engine_from_settings`
- :func:`~astra_database.session.create_session_factory`
- :func:`~astra_database.session.session_scope`
- :class:`~astra_database.repository.BaseRepository`
- :class:`~astra_database.models.feature_flag.FeatureFlag` /
  :class:`~astra_database.feature_flags.SqlFeatureFlagStore`（T0-21）
"""

from __future__ import annotations

from .base import Base, TimestampMixin
from .engine import build_engine, create_engine_from_settings
from .feature_flags import SqlFeatureFlagStore
from .models.feature_flag import FeatureFlag
from .repositories import (
    SqlAuditRepository,
    SqlModelProviderRepository,
    SqlModelRepository,
    SqlPluginRepository,
    SqlResourcePermissionRepository,
    SqlSandboxSessionRepository,
    SqlScheduleRepository,
    SqlTaskExecutionRepository,
    SqlTaskRepository,
    SqlToolPermissionRepository,
    SqlToolRepository,
)
from .repository import BaseRepository, apply_scope
from .session import SessionLocal, create_session_factory, session_scope
from .types import GUID, JSONType

__all__ = [
    "Base",
    "TimestampMixin",
    "GUID",
    "JSONType",
    "create_engine_from_settings",
    "build_engine",
    "create_session_factory",
    "session_scope",
    "SessionLocal",
    "BaseRepository",
    "apply_scope",
    # Feature Flag（T0-21）
    "FeatureFlag",
    "SqlFeatureFlagStore",
    # 审计仓储（T1-09）
    "SqlAuditRepository",
    # Model 组仓储（T1-10）
    "SqlModelProviderRepository",
    "SqlModelRepository",
    # Tool 组仓储（T1-17，由 packages/tool 下移）
    "SqlToolRepository",
    "SqlToolPermissionRepository",
    # Sandbox 仓储（T1-18，由 packages/sandbox 下移）
    "SqlSandboxSessionRepository",
    # Task 仓储（W5 / T1-26）
    "SqlTaskRepository",
    # 调度 / 执行记录仓储（W7 / T2-39；迁移 0015）
    "SqlTaskExecutionRepository",
    "SqlScheduleRepository",
    # Resource Permission 仓储（W3 / T2-13）
    "SqlResourcePermissionRepository",
    "SqlPluginRepository",
]
