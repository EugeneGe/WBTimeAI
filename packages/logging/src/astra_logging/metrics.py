"""首批 Metrics 计数器与注册（设计 §2.7.3）。

首批 **5 个计数器**：
- ``run_total{status}``：一次 Run 的计数（按终态）；
- ``run_duration_ms``：一次 Run 的耗时（毫秒，以计数器累加）；
- ``tool_call_total{tool,status}``：工具调用计数；
- ``token_total{provider,model}``：Token 用量累计；
- ``provider_error_total{provider,code}``：Provider 错误计数。

开关：配置项 ``observability.metrics_enabled``（社区默认 ``false``，Team 可开）；
关闭时经 :func:`build_metrics` 返回 :class:`~astra_logging.observability.NoOpMetrics`。
"""

from __future__ import annotations

from typing import Any

from .observability import MetricsSink, NoOpMetrics

__all__ = [
    "RUN_TOTAL",
    "RUN_DURATION_MS",
    "TOOL_CALL_TOTAL",
    "TOKEN_TOTAL",
    "PROVIDER_ERROR_TOTAL",
    "DEFAULT_COUNTER_NAMES",
    "InMemoryMetrics",
    "build_metrics",
    "register_default_counters",
]

#: 一次 Run 计数（标签：``status``）。
RUN_TOTAL = "run_total"
#: 一次 Run 耗时（毫秒，累加）。
RUN_DURATION_MS = "run_duration_ms"
#: 工具调用计数（标签：``tool`` / ``status``）。
TOOL_CALL_TOTAL = "tool_call_total"
#: Token 用量累计（标签：``provider`` / ``model``）。
TOKEN_TOTAL = "token_total"
#: Provider 错误计数（标签：``provider`` / ``code``）。
PROVIDER_ERROR_TOTAL = "provider_error_total"

#: 首批计数器名称（顺序稳定）。
DEFAULT_COUNTER_NAMES: tuple[str, ...] = (
    RUN_TOTAL,
    RUN_DURATION_MS,
    TOOL_CALL_TOTAL,
    TOKEN_TOTAL,
    PROVIDER_ERROR_TOTAL,
)


class InMemoryMetrics:
    """进程内指标实现（:class:`MetricsSink`）。

    以内存字典记录计数器（按规范化标签键聚合）；供 ``/metrics`` 端点与单测断言使用。
    轻量、无外部依赖，契合社区单进程形态。
    """

    def __init__(self) -> None:
        self._counters: dict[str, dict[str, float]] = {}

    @staticmethod
    def _label_key(tags: dict[str, Any]) -> str:
        """把标签字典规范化为稳定的键（按标签名排序）。"""
        if not tags:
            return ""
        parts = [f"{key}={tags[key]}" for key in sorted(tags)]
        return ",".join(parts)

    def counter(self, name: str, value: int = 1, **tags: Any) -> None:
        """累加计数器。"""
        series = self._counters.setdefault(name, {})
        key = self._label_key(tags)
        series[key] = series.get(key, 0.0) + float(value)

    def gauge(self, name: str, value: float, **tags: Any) -> None:
        """设置瞬时值（本实现按计数器族记录当前值）。"""
        series = self._counters.setdefault(name, {})
        series[self._label_key(tags)] = float(value)

    def histogram(self, name: str, value: float, **tags: Any) -> None:
        """记录分布采样（本实现按计数器族累加，供粗略观测）。"""
        series = self._counters.setdefault(name, {})
        key = self._label_key(tags)
        series[key] = series.get(key, 0.0) + float(value)

    def value(self, name: str, **tags: Any) -> float:
        """读取某计数器（含指定标签）的当前值；不存在时返回 ``0``。"""
        return self._counters.get(name, {}).get(self._label_key(tags), 0.0)

    def snapshot(self) -> dict[str, dict[str, float]]:
        """返回全部计数器的快照（``{name: {label_key: value}}``）。"""
        return {name: dict(series) for name, series in self._counters.items()}


def build_metrics(*, enabled: bool) -> MetricsSink:
    """按开关构建指标实现。

    Args:
        enabled: ``observability.metrics_enabled``；``False`` 时返回 No-Op。

    Returns:
        启用 → :class:`InMemoryMetrics`；关闭 → :class:`NoOpMetrics`。
    """
    if not enabled:
        return NoOpMetrics()
    metrics = InMemoryMetrics()
    register_default_counters(metrics)
    return metrics


def register_default_counters(metrics: MetricsSink) -> None:
    """注册首批 5 个计数器（预置 0 值，使 ``/metrics`` 稳定可见）。"""
    for name in DEFAULT_COUNTER_NAMES:
        metrics.counter(name, 0)
