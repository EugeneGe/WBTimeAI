"""ExtensionPoint ③ ``audit_sink``（审计落点）——签名冻结（W1b 裁定 §1.3③）。

🔴 ``write()`` 抛异常时，核心**降级本地落盘（``AuditRepository``）+ 告警**，
   **不静默丢弃**（Phase 1 §2.18）。参考降级包装见
   :class:`astra_plugin.reference.audit_sink.FallbackAuditSink`。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import AuditEvent, SinkHealth

__all__ = ["AuditSink", "EXTENSION_POINT_VERSION"]

#: 扩展点版本（格式 ``<point>/vN``）。
EXTENSION_POINT_VERSION: str = "audit_sink/v1"


@runtime_checkable
class AuditSink(Protocol):
    """审计落点扩展点（SIEM / 外部审计系统）。"""

    def write(self, event: AuditEvent) -> None:
        """写入一条审计事件；失败须由调用方降级，**不得静默**。"""
        ...

    def flush(self) -> None:
        """刷写缓冲（落盘 / 远端提交）。"""
        ...

    def health(self) -> SinkHealth:
        """报告落点健康状态。"""
        ...
