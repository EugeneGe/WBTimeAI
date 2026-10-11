"""SQLite ``VACUUM`` 调度与安全快照（W9 / T2-48；设计 §2.19 / 裁定 R9 · R10）。

**显式方言分支**（禁 try/except 推断）：

- ``sqlite`` → 执行 ``VACUUM``（回收空闲页）；或 ``VACUUM INTO``（产出安全快照，
  供 ``astra data backup`` 复用）；
- 其它方言（``postgresql`` 等）→ **no-op**（PG 自带 autovacuum，且本机无 ``pg_dump``）。

**调度**：:class:`VacuumScheduler` 表达「默认每周一次、随清理任务后触发」的口径
（``weekly_vacuum_schedule()``）；由 ``schedule`` / ``TaskQueue`` 产生周期性
``maintenance.cleanup``（含 VACUUM 尾步）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from astra_core import DomainError, ErrorCode
from astra_task.maintenance.cleanup import DEFAULT_VACUUM_INTERVAL_DAYS
from sqlalchemy.engine import Engine

__all__ = [
    "DEFAULT_VACUUM_INTERVAL_DAYS",
    "VacuumScheduler",
    "weekly_vacuum_schedule",
    "vacuum_database",
    "vacuum_into",
]


def _raw_execute(engine: Engine, sql: str) -> None:
    """在**自动提交**的原始连接上执行一条 SQL（``VACUUM`` 不能在事务内运行）。"""
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute(sql)
        finally:
            cursor.close()
        raw.commit()
    finally:
        raw.close()


def vacuum_database(engine: Engine) -> bool:
    """对数据库执行 ``VACUUM``（仅 SQLite；其它方言 no-op）。

    Args:
        engine: SQLAlchemy 引擎。

    Returns:
        ``True`` = 已执行 ``VACUUM``（SQLite）；``False`` = no-op（非 SQLite 方言）。
    """
    if engine.dialect.name != "sqlite":
        return False  # PG 等由自身 autovacuum 管理（显式 no-op，非静默丢错）
    _raw_execute(engine, "VACUUM")
    return True


def vacuum_into(engine: Engine, target: Path | str) -> Path:
    """经 ``VACUUM INTO`` 产出**一致性安全快照**（仅 SQLite）。

    ``VACUUM INTO`` 在同一读快照下重建全库到目标文件，**不阻塞**其它读者，
    适合作为 ``astra data backup`` 的落地实现（设计 §6.6 / R10）。

    Args:
        engine: SQLAlchemy 引擎（须为 SQLite）。
        target: 目标快照文件路径（父目录会被创建）。

    Returns:
        目标 :class:`~pathlib.Path`。

    Raises:
        DomainError: 非 SQLite 方言（``CONFIGURATION_ERROR``；**显式报错，不静默**）。
    """
    if engine.dialect.name != "sqlite":
        raise DomainError(
            "仅 SQLite 支持 VACUUM INTO 安全快照；PostgreSQL 请使用 pg_dump",
            code=ErrorCode.CONFIGURATION_ERROR,
            data={"dialect": engine.dialect.name},
        )
    out = Path(target)
    out.parent.mkdir(parents=True, exist_ok=True)
    literal = out.as_posix().replace("'", "''")  # SQLite 字符串字面量转义
    _raw_execute(engine, f"VACUUM INTO '{literal}'")
    return out


@dataclass(frozen=True)
class VacuumScheduler:
    """``VACUUM`` 周期调度口径（设计 §2.19：低频、默认每周一次）。

    Attributes:
        interval_days: 两次 ``VACUUM`` 的最小间隔（天；默认 7）。
    """

    interval_days: int = DEFAULT_VACUUM_INTERVAL_DAYS

    def __post_init__(self) -> None:
        if self.interval_days < 1:
            raise DomainError(
                "vacuum interval_days 必须 >= 1",
                code=ErrorCode.VALIDATION_ERROR,
                data={"interval_days": self.interval_days},
            )

    def is_due(self, now: datetime, last_vacuum: datetime | None) -> bool:
        """判断是否到达下一次 ``VACUUM`` 时点。

        Args:
            now: 当前时间（UTC）。
            last_vacuum: 上次 ``VACUUM`` 时间；``None`` = 从未执行 → 立即到点。

        Returns:
            ``True`` = 应在本轮清理任务后触发 ``VACUUM``。
        """
        if last_vacuum is None:
            return True
        return now - last_vacuum >= timedelta(days=self.interval_days)

    def next_due(self, last_vacuum: datetime) -> datetime:
        """返回上次 ``VACUUM`` 之后的下一次到期时间。"""
        return last_vacuum + timedelta(days=self.interval_days)


def weekly_vacuum_schedule() -> VacuumScheduler:
    """返回默认「每周一次」的 ``VACUUM`` 调度（设计 §2.19 / R9）。"""
    return VacuumScheduler(interval_days=DEFAULT_VACUUM_INTERVAL_DAYS)
