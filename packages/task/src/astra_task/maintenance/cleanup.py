"""``maintenance.cleanup`` 任务类型 + 保留策略 VO（W9 / T2-48；设计 §2.19 / 裁定 R2）。

🔴 **分层关键（裁定 R2）**：``astra_task`` **硬禁** ``sqlalchemy`` / ``astra_database``
（见 ``tests/integration/test_layering.py::test_task_package_has_no_web_or_database_dependency``）。
故「批量删除」的 **SQL 清理实现** 落 ``astra_database/maintenance/cleanup.py``；本模块**仅**承载：

- **任务类型常量** ``RETENTION_TASK_TYPE = "maintenance.cleanup"``（由 ``schedule`` /
  ``TaskQueue`` 驱动，见设计 §2.9）；
- **纯值对象** :class:`RetentionPolicy`（``retention.*`` 参数的不可变承载 +
  时间窗 / 保护名单语义），**零 ORM / 零 Web / 零 ``astra_database``**；
- **VACUUM 调度常量**（``DEFAULT_VACUUM_INTERVAL_DAYS``）。

本模块仅依赖**标准库** + :mod:`astra_core`（错误类型），可被
``astra_database`` / 组合根 / CLI 安全复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from astra_core import DomainError, ErrorCode

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

#: ``maintenance.cleanup`` 任务类型字符串（设计 §2.19）。
RETENTION_TASK_TYPE = "maintenance.cleanup"

#: 清理目标表（Phase 1 事实表；**不改其结构**，裁定 R7）。
AGENT_EVENT_TABLE = "agent_event"
MESSAGE_TABLE = "message"
TOOL_CALL_TABLE = "tool_call"
AUDIT_LOG_TABLE = "audit_log"

#: 全部清理目标表（顺序即「归档优先 + 子先父后」的处理口径基础）。
RETENTION_TARGET_TABLES: tuple[str, ...] = (
    AUDIT_LOG_TABLE,
    AGENT_EVENT_TABLE,
    TOOL_CALL_TABLE,
    MESSAGE_TABLE,
)

#: SQLite ``VACUUM`` 默认调度间隔（天）——「默认每周一次，随清理任务后触发」（设计 §2.19）。
DEFAULT_VACUUM_INTERVAL_DAYS = 7

#: ``retention.*`` 默认值（**镜像** ``astra_config.defaults.DEFAULT_RETENTION_*``；
#: ``astra_task`` 不依赖 ``astra_config``，故此处独立固化为同名口径，两者须一致）。
_DEFAULT_AGENT_EVENT_DAYS = 90
_DEFAULT_MESSAGE_DAYS = 90
_DEFAULT_TOOL_CALL_DAYS = 90
_DEFAULT_AUDIT_LOG_DAYS = 180
_DEFAULT_BATCH_SIZE = 1000


@dataclass(frozen=True)
class RetentionPolicy:
    """数据保留策略值对象（**不可变**；设计 §2.19 / 裁定 R7 / R8）。

    承载 ``retention.*`` 配置语义：各目标表保留天数、批量删除批大小、保护名单
    （``retention.protected``：显式**表名 / 行 ID** 名单）。**零 ORM**。

    Attributes:
        agent_event_days: ``agent_event`` 保留天数（默认 90）。
        message_days: ``message`` 保留天数（默认 90，R8）。
        tool_call_days: ``tool_call`` 保留天数（默认 90，R8）。
        audit_log_days: ``audit_log`` 保留天数（默认 180）。
        batch_size: 每批删除行数（分批提交，避免长事务锁表；默认 1000）。
        protected: 保护名单——命中**目标表名**则整表跳过；命中**行 id** 则该行跳过
            （``retention.protected``；替代对 Phase 1 表加 ``pinned`` 列，裁定 R7）。
        remote_attempt_clone_days / remote_artifact_days / remote_log_days: 远程对象保留
            （W4 后增量的**接口位**；本波 **inert**，``None`` = 未启用）。
        paused: 紧急暂停开关（``True`` 时清理器整体不动作）。
    """

    agent_event_days: int = _DEFAULT_AGENT_EVENT_DAYS
    message_days: int = _DEFAULT_MESSAGE_DAYS
    tool_call_days: int = _DEFAULT_TOOL_CALL_DAYS
    audit_log_days: int = _DEFAULT_AUDIT_LOG_DAYS
    batch_size: int = _DEFAULT_BATCH_SIZE
    protected: frozenset[str] = field(default_factory=frozenset)
    remote_attempt_clone_days: int | None = None
    remote_artifact_days: int | None = None
    remote_log_days: int | None = None
    paused: bool = False

    def __post_init__(self) -> None:
        """校验参数（非法 → ``DomainError(VALIDATION_ERROR)``，**不静默**）。"""
        if self.batch_size < 1:
            raise DomainError(
                "retention.batch_size 必须 >= 1",
                code=ErrorCode.VALIDATION_ERROR,
                data={"batch_size": self.batch_size},
            )
        for name in ("agent_event_days", "message_days", "tool_call_days", "audit_log_days"):
            value = getattr(self, name)
            if value < 0:
                raise DomainError(
                    f"retention.{name} 必须 >= 0",
                    code=ErrorCode.VALIDATION_ERROR,
                    data={name: value},
                )
        for name in ("remote_attempt_clone_days", "remote_artifact_days", "remote_log_days"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise DomainError(
                    f"retention.{name} 必须 >= 0 或留空",
                    code=ErrorCode.VALIDATION_ERROR,
                    data={name: value},
                )

    # -- 查询语义 -----------------------------------------------------------

    def days_for(self, table: str) -> int:
        """返回目标表的保留天数。

        Args:
            table: 目标表名（``agent_event`` / ``message`` / ``tool_call`` / ``audit_log``）。

        Returns:
            该表的保留天数。

        Raises:
            DomainError: 未定义的清理目标表（``VALIDATION_ERROR``）。
        """
        mapping = {
            AGENT_EVENT_TABLE: self.agent_event_days,
            MESSAGE_TABLE: self.message_days,
            TOOL_CALL_TABLE: self.tool_call_days,
            AUDIT_LOG_TABLE: self.audit_log_days,
        }
        if table not in mapping:
            raise DomainError(
                "未知的清理目标表",
                code=ErrorCode.VALIDATION_ERROR,
                data={"table": table},
            )
        return mapping[table]

    def cutoff(self, table: str, now: datetime) -> datetime:
        """返回目标表的删除时间窗下界（``now - N days``）。

        只删除 ``created_at < cutoff`` 的行——「时间窗」误删防护（设计 §2.19）。

        Args:
            table: 目标表名。
            now: 当前时间（UTC，由 :func:`astra_common.utcnow` 提供，便于 fake clock）。

        Returns:
            ``now - timedelta(days=days_for(table))``。
        """
        return now - timedelta(days=self.days_for(table))

    def is_protected_table(self, table: str) -> bool:
        """目标表名是否在保护名单（整表跳过）。"""
        return table in self.protected

    def is_protected_id(self, row_id: str) -> bool:
        """行 id 是否在保护名单（单行跳过）。"""
        return row_id in self.protected

    def with_paused(self, paused: bool) -> RetentionPolicy:
        """返回 ``paused`` 覆盖后的**新**策略（不可变语义）。"""
        return replace(self, paused=paused)

    # -- 装配（duck-typing：不 import ``astra_config``） --------------------

    @classmethod
    def from_settings(cls, settings: Any) -> RetentionPolicy:
        """从配置对象（``Settings.retention``）构造策略（**duck-typing 读取**）。

        ``astra_task`` 不依赖 ``astra_config``，故此处只按属性名读取
        （``settings.retention.<key>``），缺失时回落本模块默认值。

        Args:
            settings: 生效配置对象（读取其 ``retention`` 子对象）。

        Returns:
            :class:`RetentionPolicy`。
        """
        retention = getattr(settings, "retention", None)

        def _read(name: str, default: Any) -> Any:
            if retention is None:
                return default
            return getattr(retention, name, default)

        protected_raw = _read("protected", ()) or ()
        return cls(
            agent_event_days=int(_read("agent_event_days", _DEFAULT_AGENT_EVENT_DAYS)),
            message_days=int(_read("message_days", _DEFAULT_MESSAGE_DAYS)),
            tool_call_days=int(_read("tool_call_days", _DEFAULT_TOOL_CALL_DAYS)),
            audit_log_days=int(_read("audit_log_days", _DEFAULT_AUDIT_LOG_DAYS)),
            batch_size=int(_read("batch_size", _DEFAULT_BATCH_SIZE)),
            protected=frozenset(str(item) for item in protected_raw),
            remote_attempt_clone_days=_read("remote_attempt_clone_days", None),
            remote_artifact_days=_read("remote_artifact_days", None),
            remote_log_days=_read("remote_log_days", None),
            paused=bool(_read("paused", False)),
        )
