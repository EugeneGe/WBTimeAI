"""``RetentionCleaner``——数据保留与清理的 **SQL 实现**（W9 / T2-48；设计 §2.19 / 裁定 R2）。

🔴 **分层落点（裁定 R2）**：本模块属 ``astra_database``（ORM **允许**；``astra_database``
已依赖 ``astra_task`` / ``astra_config``，**无新边**）。纯 VO :class:`~astra_task.maintenance.
cleanup.RetentionPolicy` 落 ``astra_task/maintenance/``；**批量删除 SQL** 落此处。

冻结口径（设计 §2.19 / §6）：

1. **批量删除 + 分批提交**：每批 ``<= batch_size`` 行，单事务内删该批并 ``commit``，
   避免长事务锁表；
2. **时间窗**：只删 ``created_at < now - N days``（``now`` 取 :func:`astra_common.utcnow`，
   便于 **fake clock monkeypatch**）；
3. **误删防护**：① **非终态 ``agent_run`` 关联的 ``agent_event`` 不清理**；
   ② ``retention.protected`` 命中（表名 / 行 ID）跳过；
4. **归档优先**：``audit_log`` 清理**前先导出 JSONL 归档**（未配置归档目录 → **不清理**
   ``audit_log``，避免无归档即删除）；
5. **级联正确**：删除按「子先父」；删除 ``tool_call`` 前先**置空**引用它的
   ``audit_log.tool_call_id``（避免悬挂外键；父行 ``agent_run`` / ``conversation`` 保留）。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import astra_common
from astra_domain import RunStatus
from astra_task.maintenance.cleanup import (
    AGENT_EVENT_TABLE,
    AUDIT_LOG_TABLE,
    MESSAGE_TABLE,
    RETENTION_TARGET_TABLES,
    TOOL_CALL_TABLE,
    RetentionPolicy,
)
from sqlalchemy import Select, delete, inspect, select, update

from astra_database.models.audit import AuditLog
from astra_database.models.conversation import AgentEvent, AgentRun, Message, ToolCall

__all__ = ["CleanupReport", "RetentionCleaner"]


@dataclass
class CleanupReport:
    """一次清理的变更报告。

    Attributes:
        deleted: ``{表名: 已删除行数}``。
        archived: ``{表名: 已归档行数}``（当前仅 ``audit_log``）。
        batches: 提交的批次数（分批提交）。
        paused: 是否因 ``paused`` 整体未动作。
        now: 本次清理采用的 ``now``（UTC）。
    """

    deleted: dict[str, int] = field(default_factory=dict)
    archived: dict[str, int] = field(default_factory=dict)
    batches: int = 0
    paused: bool = False
    now: datetime | None = None

    @property
    def total_deleted(self) -> int:
        """删除总行数。"""
        return sum(self.deleted.values())

    def as_dict(self) -> dict[str, Any]:
        """转为可序列化字典（供 Worker 结果 / CLI 输出复用）。"""
        return {
            "deleted": dict(self.deleted),
            "archived": dict(self.archived),
            "batches": self.batches,
            "paused": self.paused,
            "total_deleted": self.total_deleted,
            "now": self.now.isoformat() if self.now is not None else None,
        }


class RetentionCleaner:
    """按 :class:`~astra_task.maintenance.cleanup.RetentionPolicy` 清理到期数据。

    Args:
        session_factory: ``sessionmaker``（每批一个短事务）。
        policy: 保留策略（默认 :class:`RetentionPolicy` 全默认值）。
        clock: 取时函数；``None`` → 运行期调用 :func:`astra_common.utcnow`
            （**fake clock 可 monkeypatch ``astra_common.utcnow``**）。
        archive_dir: ``audit_log`` 归档目录；``None`` → **不清理** ``audit_log``
            （「归档优先」，避免无归档即删除）。
    """

    def __init__(
        self,
        session_factory: Any,
        policy: RetentionPolicy | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        archive_dir: Path | str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy if policy is not None else RetentionPolicy()
        self._clock = clock
        self._archive_dir = Path(archive_dir) if archive_dir is not None else None

    # -- 公共入口 -----------------------------------------------------------

    @property
    def policy(self) -> RetentionPolicy:
        """返回当前生效策略。"""
        return self._policy

    def _now(self) -> datetime:
        """取当前时间（运行期解析，便于 monkeypatch ``astra_common.utcnow``）。"""
        if self._clock is not None:
            return self._clock()
        return astra_common.utcnow()

    def run(self) -> CleanupReport:
        """执行一轮清理（分批提交）。

        Returns:
            :class:`CleanupReport`。``policy.paused`` 为真时**整体不动作**。
        """
        if self._policy.paused:
            return CleanupReport(paused=True, now=self._now())

        now = self._now()
        report = CleanupReport(now=now)

        # 处理顺序：audit_log（归档优先）→ agent_event → tool_call → message（子先父）。
        for table in RETENTION_TARGET_TABLES:
            if self._policy.is_protected_table(table):
                report.deleted[table] = 0
                report.archived[table] = 0
                continue
            if table == AUDIT_LOG_TABLE:
                deleted, batches, archived = self._clean_audit_log(now)
                report.archived[table] = archived
            elif table == AGENT_EVENT_TABLE:
                deleted, batches = self._clean_agent_event(now)
            elif table == TOOL_CALL_TABLE:
                deleted, batches = self._clean_tool_call(now)
            else:  # MESSAGE_TABLE
                deleted, batches = self._clean_message(now)
            report.deleted[table] = deleted
            report.batches += batches
        return report

    # -- 通用分批 -----------------------------------------------------------

    def _protected_ids(self) -> list[str]:
        """保护名单（同时含表名 / 行 ID；作为 SQL ``NOT IN`` 过滤无副作用）。"""
        return sorted(self._policy.protected)

    def _drain(
        self,
        base_stmt: Select[Any],
        apply_delete: Callable[[Any, list[str]], None],
    ) -> tuple[int, int]:
        """分批删除：每批 ``<= batch_size``，短事务提交。

        Args:
            base_stmt: 选取待删行 ``id`` 的 ``select``（不含 ``limit``）。
            apply_delete: 在给定 session 内删除这批 ``ids`` 的回调。

        Returns:
            ``(deleted_total, batches)``。
        """
        total = 0
        batches = 0
        while True:
            with self._session_factory() as session:
                ids = list(session.scalars(base_stmt.limit(self._policy.batch_size)))
                if not ids:
                    break
                apply_delete(session, ids)
                session.commit()
            total += len(ids)
            batches += 1
        return total, batches

    # -- 各目标表 -----------------------------------------------------------

    def _clean_agent_event(self, now: datetime) -> tuple[int, int]:
        """清理 ``agent_event``：**非终态 ``agent_run`` 关联者不清理**（误删防护）。"""
        cutoff = self._policy.cutoff(AGENT_EVENT_TABLE, now)
        non_terminal = list(RunStatus.non_terminal_values())
        protected = self._protected_ids()
        stmt = select(AgentEvent.id).where(AgentEvent.created_at < cutoff)
        # 非终态 Run 保护：run_id 属于 PENDING/RUNNING 的事件一律保留。
        stmt = stmt.where(
            AgentEvent.run_id.notin_(select(AgentRun.id).where(AgentRun.status.in_(non_terminal)))
        )
        if protected:
            stmt = stmt.where(AgentEvent.id.notin_(protected))

        def _apply(session: Any, ids: list[str]) -> None:
            session.execute(delete(AgentEvent).where(AgentEvent.id.in_(ids)))

        return self._drain(stmt, _apply)

    def _clean_tool_call(self, now: datetime) -> tuple[int, int]:
        """清理 ``tool_call``：先置空引用它的 ``audit_log.tool_call_id``（级联正确）。"""
        cutoff = self._policy.cutoff(TOOL_CALL_TABLE, now)
        protected = self._protected_ids()
        stmt = select(ToolCall.id).where(ToolCall.created_at < cutoff)
        if protected:
            stmt = stmt.where(ToolCall.id.notin_(protected))

        def _apply(session: Any, ids: list[str]) -> None:
            # 级联正确：解除审计对该批 tool_call 的引用（保留审计行）+ 删 tool_call。
            session.execute(
                update(AuditLog).where(AuditLog.tool_call_id.in_(ids)).values(tool_call_id=None)
            )
            session.execute(delete(ToolCall).where(ToolCall.id.in_(ids)))

        return self._drain(stmt, _apply)

    def _clean_message(self, now: datetime) -> tuple[int, int]:
        """清理 ``message``（父 ``conversation`` / ``agent_run`` 保留）。"""
        cutoff = self._policy.cutoff(MESSAGE_TABLE, now)
        protected = self._protected_ids()
        stmt = select(Message.id).where(Message.created_at < cutoff)
        if protected:
            stmt = stmt.where(Message.id.notin_(protected))

        def _apply(session: Any, ids: list[str]) -> None:
            session.execute(delete(Message).where(Message.id.in_(ids)))

        return self._drain(stmt, _apply)

    def _clean_audit_log(self, now: datetime) -> tuple[int, int, int]:
        """清理 ``audit_log``：**先导出 JSONL 归档再删**；未配置归档目录 → 不清理。"""
        if self._archive_dir is None:
            return 0, 0, 0  # 归档优先：无归档目录则不删 audit_log
        cutoff = self._policy.cutoff(AUDIT_LOG_TABLE, now)
        protected = self._protected_ids()
        total = 0
        archived = 0
        batches = 0
        archive_path = self._archive_dir / f"audit_log-{now.strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        while True:
            with self._session_factory() as session:
                stmt = select(AuditLog).where(AuditLog.created_at < cutoff)
                if protected:
                    stmt = stmt.where(AuditLog.id.notin_(protected))
                rows = list(session.scalars(stmt.limit(self._policy.batch_size)))
                if not rows:
                    break
                self._archive_dir.mkdir(parents=True, exist_ok=True)
                with archive_path.open("a", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(_row_to_dict(row), default=_json_default) + "\n")
                ids = [row.id for row in rows]
                session.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))
                session.commit()
            total += len(ids)
            archived += len(ids)
            batches += 1
        return total, batches, archived


def _row_to_dict(row: Any) -> dict[str, Any]:
    """把 ORM 行转为 ``{列名: 值}``（用 mapper 的 ``column_attrs`` 取**属性名**）。

    说明：``audit_log.metadata`` 的映射属性名为 ``metadata_``（避免与声明式 ``metadata``
    冲突），故不可用 ``__table__.columns`` 直接 ``getattr``（会取到类属性）。
    """
    payload: dict[str, Any] = {}
    for attr in inspect(row).mapper.column_attrs:
        payload[attr.key] = getattr(row, attr.key)
    return payload


def _json_default(value: Any) -> Any:
    """JSON 序列化兜底：``datetime`` → ISO 8601；``Decimal`` → ``str``。"""
    if isinstance(value, datetime):
        return astra_common.to_iso8601(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return str(value)


def iter_target_tables() -> Iterable[str]:
    """返回清理目标表序列（供调度 / 文档复用）。"""
    return RETENTION_TARGET_TABLES
