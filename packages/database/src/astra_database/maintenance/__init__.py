"""``astra_database.maintenance`` 子包门面（W9 / T2-48；裁定 R2）。

**SQL 清理实现落点**（ORM 允许）：:class:`RetentionCleaner`（批量删除 + 分批提交）+
:func:`vacuum_database` / :func:`vacuum_into`（SQLite ``VACUUM`` / 安全快照；PG no-op）。
纯 VO :class:`~astra_task.maintenance.cleanup.RetentionPolicy` 落 ``astra_task/maintenance/``。
"""

from __future__ import annotations

from .cleanup import CleanupReport, RetentionCleaner, iter_target_tables
from .vacuum import (
    DEFAULT_VACUUM_INTERVAL_DAYS,
    VacuumScheduler,
    vacuum_database,
    vacuum_into,
    weekly_vacuum_schedule,
)

__all__ = [
    "CleanupReport",
    "RetentionCleaner",
    "iter_target_tables",
    "DEFAULT_VACUUM_INTERVAL_DAYS",
    "VacuumScheduler",
    "weekly_vacuum_schedule",
    "vacuum_database",
    "vacuum_into",
]
