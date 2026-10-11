"""审计落点（``AuditSink``）与**写库实现**（``RepositoryAuditSink``）——
设计 §2.18 / §2.15.1；W3 / T2-17 · 裁定 R7 §7.3；对齐 W1b ``audit_sink/v1`` 契约。

- :class:`AuditSink`：落点协议（``write`` / ``flush`` / ``health``），签名与
  :class:`astra_plugin.extension_points.audit_sink.AuditSink` 一致（``audit_sink/v1``）；
- :class:`RepositoryAuditSink`：**核心写库实现** —— 经**注入的**领域 Protocol
  :class:`~astra_domain.AuditRepository` 落 ``audit_log``（**四要素** who / action /
  resource / outcome 齐全）；``write`` 失败 → **降级本地落盘 + 告警**，**不静默丢弃**。

🔴 本包为**抽象包（零 ORM）**：**不得** import ``sqlalchemy`` / ``alembic`` /
   ``astra_database`` / ``astra_application``（W1 裁定 §2.2 / F17）；落库经注入的领域
   Protocol，降级落盘仅用标准库（``json`` + ``pathlib``）。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from astra_common.time import utcnow
from astra_domain import AuditEvent, AuditRepository, SinkHealth

__all__ = ["AuditSink", "RepositoryAuditSink", "resolve_fallback_dir"]

#: 降级落盘目录环境变量名（与 ``astra_application`` 的 spool 约定一致）。
FALLBACK_DIR_ENV = "ASTRA_AUDIT_SPOOL_DIR"

#: 默认降级落盘目录（相对用户主目录）。
_DEFAULT_FALLBACK_RELATIVE = (".astra-ai", "audit-spool")

#: 降级落盘文件前缀 / 后缀（JSON Line）。
_FILE_PREFIX = "audit-"
_FILE_SUFFIX = ".jsonl"


def resolve_fallback_dir(explicit: str | Path | None = None) -> Path:
    """解析审计降级落盘目录。

    Args:
        explicit: 显式目录；为 ``None`` 时读取 ``ASTRA_AUDIT_SPOOL_DIR``，
            仍为空则回退 ``~/.astra-ai/audit-spool/``。

    Returns:
        解析后的绝对目录 :class:`~pathlib.Path`。
    """
    if explicit:
        return Path(explicit).expanduser()
    env_value = os.environ.get(FALLBACK_DIR_ENV)
    if env_value:
        return Path(env_value).expanduser()
    return Path.home().joinpath(*_DEFAULT_FALLBACK_RELATIVE)


@runtime_checkable
class AuditSink(Protocol):
    """审计落点协议（对齐 ``audit_sink/v1``；SIEM / 外部审计系统）。"""

    def write(self, event: AuditEvent) -> None:
        """写入一条审计事件；失败须由调用方降级，**不得静默**。"""
        ...

    def flush(self) -> None:
        """刷写缓冲（落盘 / 远端提交）。"""
        ...

    def health(self) -> SinkHealth:
        """报告落点健康状态。"""
        ...


def _serialize(event: AuditEvent) -> str:
    """把审计事件序列化为一行 JSON（``metadata`` / ``extensions`` 已脱敏）。"""
    payload: dict[str, Any] = {
        "id": event.id,
        "tenant_id": event.tenant_id,
        "organization_id": event.organization_id,
        "workspace_id": event.workspace_id,
        "user_id": event.user_id,
        "agent_id": event.agent_id,
        "run_id": event.run_id,
        "tool_call_id": event.tool_call_id,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "outcome": event.outcome,
        "duration_ms": event.duration_ms,
        "request_id": event.request_id,
        "trace_id": event.trace_id,
        "metadata": event.metadata,
        "extensions": event.extensions,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


class RepositoryAuditSink:
    """审计**写库**实现（注入领域 ``AuditRepository``）+ 失败降级本地落盘。

    降级链：**写库 → 本地落盘（JSON Line）→ 告警**；任一级失败都**不静默丢弃**
    （落盘失败时经 ``on_error`` 回调 + ``ERROR`` 日志告警）。

    Args:
        repository: 目标审计仓储（领域 Protocol；零 ORM）。
        fallback_dir: 降级落盘目录；``None`` 时按 :func:`resolve_fallback_dir` 解析。
        fallback_enabled: 是否启用降级落盘（``False`` 时失败仅告警，不落盘）。
        logger: 结构化日志器（缺省取本模块 logger）。
        on_error: 可选告警回调 ``(event, exc)``。
    """

    def __init__(
        self,
        *,
        repository: AuditRepository,
        fallback_dir: str | Path | None = None,
        fallback_enabled: bool = True,
        logger: logging.Logger | None = None,
        on_error: Callable[[AuditEvent, Exception], None] | None = None,
    ) -> None:
        self._repository = repository
        self._fallback_dir = resolve_fallback_dir(fallback_dir)
        self._fallback_enabled = fallback_enabled
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self._on_error = on_error
        self._last_error: str | None = None
        self._failure_count = 0

    @property
    def repository(self) -> AuditRepository:
        """返回底层审计仓储（供重放复用）。"""
        return self._repository

    @property
    def fallback_dir(self) -> Path:
        """返回降级落盘目录。"""
        return self._fallback_dir

    @property
    def failure_count(self) -> int:
        """返回写库失败累计次数（含已降级）。"""
        return self._failure_count

    def write(self, event: AuditEvent) -> None:
        """写库；失败 → 降级本地落盘 + 告警（**不静默丢弃**）。"""
        try:
            self._repository.add(event)
        except Exception as exc:  # noqa: BLE001 - 显式降级路径，捕获全部异常
            self._last_error = str(exc)
            self._failure_count += 1
            self._logger.warning(
                "审计写库失败，降级本地落盘",
                extra={
                    "request_id": event.request_id,
                    "trace_id": event.trace_id,
                    "action": event.action,
                    "error": str(exc),
                },
            )
            self._fallback(event, exc)

    def _fallback(self, event: AuditEvent, exc: Exception) -> None:
        """降级本地落盘；落盘失败 / 未启用 → 结构化作 ``ERROR`` 告警。"""
        if not self._fallback_enabled:
            self._alert(event, exc)
            return
        try:
            self._append_to_fallback_file(event)
        except Exception as write_exc:  # noqa: BLE001 - 兜底：不静默丢弃
            self._logger.error(
                "审计降级落盘亦失败（写库与落盘均失败）",
                extra={
                    "request_id": event.request_id,
                    "trace_id": event.trace_id,
                    "action": event.action,
                    "error": str(write_exc),
                },
            )
            self._alert(event, write_exc)

    def _append_to_fallback_file(self, event: AuditEvent) -> None:
        """把事件追加写入当日 JSON Line 落盘文件。"""
        self._fallback_dir.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%d")
        path = self._fallback_dir / f"{_FILE_PREFIX}{stamp}{_FILE_SUFFIX}"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_serialize(event))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _alert(self, event: AuditEvent, exc: Exception) -> None:
        """调用告警回调（结构化告警；**不静默丢弃**）。"""
        if self._on_error is not None:
            try:
                self._on_error(event, exc)
            except Exception:  # noqa: BLE001 - 告警失败不影响主流程
                self._logger.debug("审计告警回调失败", exc_info=True)

    def flush(self) -> None:
        """刷写缓冲（本实现无外部缓冲，空操作）。"""
        return None

    def health(self) -> SinkHealth:
        """报告落点健康状态（以是否发生过写库失败为准）。"""
        if self._last_error is None:
            return SinkHealth(ok=True, message="ok")
        return SinkHealth(ok=False, message=f"last_error={self._last_error}")
