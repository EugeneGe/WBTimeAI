"""``astra_task.maintenance`` 子包门面（W9 / T2-48；裁定 R2）。

**纯 VO 落点**：``maintenance.cleanup`` 的任务类型常量 + :class:`RetentionPolicy` 值对象。
本子包 **零 ORM / 零 Web / 零 ``astra_database``**（SQL 清理实现落
``astra_database/maintenance/cleanup.py``，见 ``tests/integration/test_layering.py``）。
"""

from __future__ import annotations

from .cleanup import (
    AGENT_EVENT_TABLE,
    AUDIT_LOG_TABLE,
    DEFAULT_VACUUM_INTERVAL_DAYS,
    MESSAGE_TABLE,
    RETENTION_TARGET_TABLES,
    RETENTION_TASK_TYPE,
    TOOL_CALL_TABLE,
    RetentionPolicy,
)

__all__ = [
    "RETENTION_TASK_TYPE",
    "AGENT_EVENT_TABLE",
    "MESSAGE_TABLE",
    "TOOL_CALL_TABLE",
    "AUDIT_LOG_TABLE",
    "RETENTION_TARGET_TABLES",
    "DEFAULT_VACUUM_INTERVAL_DAYS",
    "RetentionPolicy",
]
