"""``/metrics`` 端点（设计 §2.7.3；开关 ``observability.metrics_enabled``）。

- 社区默认 **关闭**（``false``）：``create_app`` **不挂载**本路由 → 请求 ``/metrics`` 返回 404；
- 开启后：返回**文本格式**的进程内指标快照（首批 5 个计数器）。

本路由只读取 ``app.state.metrics``（由组合根在 ``create_app`` 装配），**不自建全局状态**。
"""

from __future__ import annotations

from astra_logging import InMemoryMetrics
from fastapi import APIRouter, Request
from starlette.responses import PlainTextResponse

__all__ = ["router", "render_metrics"]

router = APIRouter(tags=["observability"])


def render_metrics(snapshot: dict[str, dict[str, float]]) -> str:
    """把指标快照渲染为文本（Prometheus 风格的极简子集）。

    Args:
        snapshot: ``{counter_name: {label_key: value}}``。

    Returns:
        多行文本（含 ``# TYPE <name> counter`` 注释行）。
    """
    lines = ["# Astra AI metrics (in-memory)"]
    if not snapshot:
        lines.append("# no counters registered")
        return "\n".join(lines) + "\n"
    for name in sorted(snapshot):
        lines.append(f"# TYPE {name} counter")
        series = snapshot[name]
        if not series:
            lines.append(f"{name} 0")
            continue
        for label_key in sorted(series):
            label = f"{{{label_key}}}" if label_key else ""
            value = series[label_key]
            lines.append(f"{name}{label} {value:g}")
    return "\n".join(lines) + "\n"


@router.get("/metrics", summary="Metrics（开关控制）")
async def metrics(request: Request) -> PlainTextResponse:
    """返回进程内指标快照（仅当开关开启时挂载本路由）。"""
    registry = getattr(request.app.state, "metrics", None)
    snapshot = registry.snapshot() if isinstance(registry, InMemoryMetrics) else {}
    return PlainTextResponse(render_metrics(snapshot))
