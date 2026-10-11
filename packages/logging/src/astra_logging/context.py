"""日志上下文（contextvars）。

承载 ``request_id`` / ``trace_id`` / ``span_id`` / ``tenant_id`` / ``run_id``。

设计 §2.7.3：每条结构化日志应携带上述字段；本模块以 :mod:`contextvars` 承载
**请求 / 执行链路上下文**，使日志、审计与 Run 事件可串联（总纲 §11.4）。

实现要点：
- 五个字段各自一个 :class:`contextvars.ContextVar`（默认 ``None``）；
- :func:`install_log_context_factory` 安装 ``LogRecord`` 工厂，把当前上下文**注入
  每条日志记录**（因此 ``caplog`` 等直接检查 ``LogRecord`` 的场景亦可见）；
- 上下文设置与恢复以 :func:`bind_context` 上下文管理器为主，自动还原令牌。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

__all__ = [
    "CONTEXT_FIELDS",
    "get_request_id",
    "get_trace_id",
    "get_span_id",
    "get_tenant_id",
    "get_run_id",
    "get_context",
    "set_request_id",
    "set_trace_id",
    "set_span_id",
    "set_tenant_id",
    "set_run_id",
    "bind_context",
    "install_log_context_factory",
]

#: 注入日志记录的上下文字段（顺序稳定，便于格式化）。
CONTEXT_FIELDS: tuple[str, ...] = (
    "request_id",
    "trace_id",
    "span_id",
    "tenant_id",
    "run_id",
)

_REQUEST_ID: ContextVar[str | None] = ContextVar("astra_request_id", default=None)
_TRACE_ID: ContextVar[str | None] = ContextVar("astra_trace_id", default=None)
_SPAN_ID: ContextVar[str | None] = ContextVar("astra_span_id", default=None)
_TENANT_ID: ContextVar[str | None] = ContextVar("astra_tenant_id", default=None)
_RUN_ID: ContextVar[str | None] = ContextVar("astra_run_id", default=None)

_CONTEXT_VARS: dict[str, ContextVar[str | None]] = {
    "request_id": _REQUEST_ID,
    "trace_id": _TRACE_ID,
    "span_id": _SPAN_ID,
    "tenant_id": _TENANT_ID,
    "run_id": _RUN_ID,
}


def get_request_id() -> str | None:
    """返回当前 ``request_id``（无上下文时为 ``None``）。"""
    return _REQUEST_ID.get()


def get_trace_id() -> str | None:
    """返回当前 ``trace_id``（无上下文时为 ``None``）。"""
    return _TRACE_ID.get()


def get_span_id() -> str | None:
    """返回当前 ``span_id``（无上下文时为 ``None``）。"""
    return _SPAN_ID.get()


def get_tenant_id() -> str | None:
    """返回当前 ``tenant_id``（无上下文时为 ``None``）。"""
    return _TENANT_ID.get()


def get_run_id() -> str | None:
    """返回当前 ``run_id``（无上下文时为 ``None``）。"""
    return _RUN_ID.get()


def get_context() -> dict[str, str]:
    """返回当前上下文快照（仅含非 ``None`` 字段）。"""
    snapshot: dict[str, str] = {}
    for field, var in _CONTEXT_VARS.items():
        value = var.get()
        if value is not None:
            snapshot[field] = value
    return snapshot


def set_request_id(value: str | None) -> Token[str | None]:
    """设置 ``request_id``，返回用于还原的令牌。"""
    return _REQUEST_ID.set(value)


def set_trace_id(value: str | None) -> Token[str | None]:
    """设置 ``trace_id``，返回用于还原的令牌。"""
    return _TRACE_ID.set(value)


def set_span_id(value: str | None) -> Token[str | None]:
    """设置 ``span_id``，返回用于还原的令牌。"""
    return _SPAN_ID.set(value)


def set_tenant_id(value: str | None) -> Token[str | None]:
    """设置 ``tenant_id``，返回用于还原的令牌。"""
    return _TENANT_ID.set(value)


def set_run_id(value: str | None) -> Token[str | None]:
    """设置 ``run_id``，返回用于还原的令牌。"""
    return _RUN_ID.set(value)


@contextmanager
def bind_context(**fields: str | None) -> Iterator[None]:
    """在上下文中绑定若干字段，退出时自动还原。

    Args:
        **fields: 任意 ``request_id`` / ``trace_id`` / ``span_id`` / ``tenant_id`` /
            ``run_id``（未知键忽略）。

    Yields:
        ``None``（仅供 :keyword:`with` 使用）。
    """
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = []
    for field, value in fields.items():
        var = _CONTEXT_VARS.get(field)
        if var is not None:
            tokens.append((var, var.set(value)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def install_log_context_factory() -> None:
    """安装 ``LogRecord`` 工厂：把当前上下文注入每条日志记录（幂等）。

    注入字段见 :data:`CONTEXT_FIELDS`；仅在记录**尚无**该属性（或为 ``None``）时写入，
    不覆盖调用方显式传入的 ``extra``。
    """
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_astra_context_factory", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current_factory(*args, **kwargs)
        for field in CONTEXT_FIELDS:
            if getattr(record, field, None) is None:
                value = _CONTEXT_VARS[field].get()
                if value is not None:
                    setattr(record, field, value)
        return record

    factory._astra_context_factory = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
