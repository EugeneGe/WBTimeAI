"""结构化日志（``astra_logging``）。

- :func:`~astra_logging.setup.configure_logging`：依据配置初始化日志（JSON / console）
- :func:`~astra_logging.logger.get_logger`：获取命名 logger
- :mod:`astra_logging.observability`：Metrics / Tracing 预留接口（No-Op 实现）
- :mod:`astra_logging.context`：日志上下文（``request_id``/``trace_id``/``span_id``/
  ``tenant_id``/``run_id`` 的 contextvar，T1-04）
- :mod:`astra_logging.tracing`：轻量链路追踪（``new_trace_id``/``new_span_id``/``span``）
- :mod:`astra_logging.metrics`：首批 5 个 Metrics 计数器

注意：本包目录名为 ``packages/logging``，但**导入名为 ``astra_logging``**（src 布局），
不会与标准库 :mod:`logging` 冲突；包内一律使用**绝对导入**。
"""

from __future__ import annotations

from . import context, metrics, tracing
from .context import (
    bind_context,
    get_context,
    get_request_id,
    get_run_id,
    get_span_id,
    get_tenant_id,
    get_trace_id,
    install_log_context_factory,
)
from .logger import get_logger
from .metrics import (
    DEFAULT_COUNTER_NAMES,
    PROVIDER_ERROR_TOTAL,
    RUN_DURATION_MS,
    RUN_TOTAL,
    TOKEN_TOTAL,
    TOOL_CALL_TOTAL,
    InMemoryMetrics,
    build_metrics,
    register_default_counters,
)
from .observability import (
    MetricsSink,
    NoOpMetrics,
    NoOpTracing,
    TracingSink,
    get_metrics,
    get_tracing,
)
from .setup import ConsoleFormatter, JsonFormatter, configure_logging
from .tracing import Span, new_span_id, new_trace_id, span

__all__ = [
    "configure_logging",
    "get_logger",
    "JsonFormatter",
    "ConsoleFormatter",
    "MetricsSink",
    "TracingSink",
    "NoOpMetrics",
    "NoOpTracing",
    "get_metrics",
    "get_tracing",
    # context（T1-04）
    "context",
    "bind_context",
    "get_context",
    "get_request_id",
    "get_trace_id",
    "get_span_id",
    "get_tenant_id",
    "get_run_id",
    "install_log_context_factory",
    # tracing（T1-04）
    "tracing",
    "Span",
    "new_trace_id",
    "new_span_id",
    "span",
    # metrics（T1-04）
    "metrics",
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
