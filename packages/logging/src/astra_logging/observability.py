"""可观测性预留接口：Metrics / Tracing。

Phase 0 仅提供 **接口（Protocol）+ No-Op 实现**，保证调用点稳定；
Phase 1+ 可替换为 Prometheus / OpenTelemetry 等真实实现而不改业务代码。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "MetricsSink",
    "TracingSink",
    "NoOpMetrics",
    "NoOpTracing",
    "get_metrics",
    "get_tracing",
]


@runtime_checkable
class MetricsSink(Protocol):
    """指标采集接口。"""

    def counter(self, name: str, value: int = 1, **tags: Any) -> None:
        """累加计数器。"""
        ...

    def gauge(self, name: str, value: float, **tags: Any) -> None:
        """设置瞬时值。"""
        ...

    def histogram(self, name: str, value: float, **tags: Any) -> None:
        """记录分布采样。"""
        ...


@runtime_checkable
class TracingSink(Protocol):
    """链路追踪接口。"""

    def span(self, name: str, **attributes: Any) -> AbstractContextManager[None]:
        """开启一个 span（上下文管理器）。"""
        ...


class NoOpMetrics:
    """空实现的指标接口（默认）。"""

    def counter(self, name: str, value: int = 1, **tags: Any) -> None:  # noqa: D102
        return None

    def gauge(self, name: str, value: float, **tags: Any) -> None:  # noqa: D102
        return None

    def histogram(self, name: str, value: float, **tags: Any) -> None:  # noqa: D102
        return None


class NoOpTracing:
    """空实现的追踪接口（默认）。"""

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[None]:  # noqa: D102
        yield


def get_metrics() -> MetricsSink:
    """返回指标接口（Phase 0 恒为 :class:`NoOpMetrics`）。"""
    return NoOpMetrics()


def get_tracing() -> TracingSink:
    """返回追踪接口（Phase 0 恒为 :class:`NoOpTracing`）。"""
    return NoOpTracing()
