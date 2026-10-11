"""轻量链路追踪（设计 §2.7.3）。

- :func:`new_trace_id`：一次 Run / 一次请求生成一个 ``trace_id``（**UUIDv7**，唯一 ID
  入口 :func:`astra_core.generate_id`）；
- :func:`new_span_id`：每步（模型调用 / 工具调用 / 沙箱会话）生成一个 ``span_id``；
- :func:`span`：轻量 span 上下文管理器——进入时把 ``span_id`` 写入日志上下文，
  退出时还原；并把 ``trace_id`` / ``span_id`` 绑定到当前上下文供结构化日志携带。

> Trace 的**产生**属**开源核心**（本模块）；商业侧只做视图 / 报表 / 导出 / 归档（R-07）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from astra_core import generate_id

from . import context

__all__ = ["new_trace_id", "new_span_id", "Span", "span"]


def new_trace_id() -> str:
    """生成新的 ``trace_id``（UUIDv7）。

    Returns:
        标准 36 字符 UUIDv7 字符串（来自 :func:`astra_core.generate_id`）。
    """
    return generate_id()


def new_span_id() -> str:
    """生成新的 ``span_id``（UUIDv7）。

    Returns:
        标准 36 字符 UUIDv7 字符串（来自 :func:`astra_core.generate_id`）。
    """
    return generate_id()


@dataclass
class Span:
    """一次 span 的标识。

    Attributes:
        name: span 名称（如 ``model.chat`` / ``tool.exec`` / ``sandbox.exec``）。
        trace_id: 所属 trace。
        span_id: 本次 span 唯一标识。
    """

    name: str
    trace_id: str
    span_id: str


@contextmanager
def span(name: str, *, trace_id: str | None = None, span_id: str | None = None) -> Iterator[Span]:
    """开启一个轻量 span，并绑定 ``trace_id`` / ``span_id`` 到日志上下文。

    Args:
        name: span 名称。
        trace_id: 显式 trace；为 ``None`` 时沿用当前上下文，仍无则新建。
        span_id: 显式 span；为 ``None`` 时新建。

    Yields:
        本次 :class:`Span`（含 ``name`` / ``trace_id`` / ``span_id``）。
    """
    effective_trace = trace_id or context.get_trace_id() or new_trace_id()
    effective_span = span_id or new_span_id()
    with context.bind_context(trace_id=effective_trace, span_id=effective_span):
        yield Span(name=name, trace_id=effective_trace, span_id=effective_span)
