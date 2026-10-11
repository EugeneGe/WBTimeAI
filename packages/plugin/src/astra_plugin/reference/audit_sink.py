"""``audit_sink`` 参考实现：:class:`NoopAuditSink` + :class:`FallbackAuditSink`。

- :class:`NoopAuditSink`：不做任何外部写入的落点（参考 / 测试用）；
- :class:`FallbackAuditSink`：**核心降级策略**参考——``sink.write`` 失败时
  降级本地落盘到 :class:`~astra_domain.AuditRepository` + 告警，
  **不静默丢弃**（Phase 1 §2.18 / 裁定 §1.3③）。
"""

from __future__ import annotations

from collections.abc import Callable

from astra_domain import AuditEvent, AuditRepository, SinkHealth

from ..extension_points.audit_sink import AuditSink

__all__ = ["NoopAuditSink", "FallbackAuditSink"]


class NoopAuditSink:
    """空审计落点（不写外部系统；仅健康可用）。"""

    def write(self, event: AuditEvent) -> None:
        """空操作。"""
        return None

    def flush(self) -> None:
        """空操作。"""
        return None

    def health(self) -> SinkHealth:
        """恒健康。"""
        return SinkHealth(ok=True, message="noop")


class FallbackAuditSink:
    """审计降级包装：外部 ``sink`` 失败 → 本地 ``AuditRepository`` 落盘 + 告警。

    🔴 不静默丢弃：降级路径必然把事件写入本地仓储；``on_error`` 供结构化告警。

    Args:
        sink: 被包装的外部审计落点。
        repository: 本地降级落盘仓储。
        on_error: 可选告警回调（事件 + 异常）。
    """

    def __init__(
        self,
        sink: AuditSink,
        repository: AuditRepository,
        *,
        on_error: Callable[[AuditEvent, Exception], None] | None = None,
    ) -> None:
        self._sink = sink
        self._repository = repository
        self._on_error = on_error

    def write(self, event: AuditEvent) -> None:
        """先写外部落点；失败则降级本地落盘并告警（不静默）。"""
        try:
            self._sink.write(event)
        except Exception as exc:  # noqa: BLE001 - 显式降级路径，捕获全部异常
            self._repository.add(event)
            if self._on_error is not None:
                self._on_error(event, exc)

    def flush(self) -> None:
        """尽力刷写外部落点（失败忽略，本地已落盘）。"""
        try:
            self._sink.flush()
        except Exception:  # noqa: BLE001 - 降级不影响主流程
            return None

    def health(self) -> SinkHealth:
        """代理外部落点健康状态。"""
        return self._sink.health()
