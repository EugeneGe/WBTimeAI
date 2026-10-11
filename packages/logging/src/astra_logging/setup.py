"""日志初始化：结构化输出（JSON / 控制台）与级别配置。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from astra_config import Settings

from .context import install_log_context_factory

__all__ = ["JsonFormatter", "ConsoleFormatter", "configure_logging"]

#: 会被自动提升到结构化字段的 LogRecord 追加属性。
_EXTRA_FIELDS = (
    "event",
    "request_id",
    "trace_id",
    "span_id",
    "tenant_id",
    "run_id",
    "user_id",
    "duration_ms",
)


class JsonFormatter(logging.Formatter):
    """将日志记录格式化为单行 JSON（便于采集与检索）。"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化单条日志为 JSON 字符串。"""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """面向开发者的可读控制台格式。"""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )


def configure_logging(settings: Settings, *, force: bool = False) -> logging.Logger:
    """依据配置初始化根 logger。

    Args:
        settings: 生效配置（读取 ``log_level`` 与 ``log_format``）。
        force: 为 ``True`` 时强制重建 handler（默认仅在首次配置时生效）。

    Returns:
        配置后的根 logger。
    """
    numeric_level = logging.getLevelName(str(settings.log_level).upper())
    level = numeric_level if isinstance(numeric_level, int) else logging.INFO

    # 安装日志上下文工厂（幂等）：使每条日志携带 request_id/trace_id/span_id 等（T1-04）。
    install_log_context_factory()

    root = logging.getLogger()
    already_configured = getattr(root, "_astra_configured", False)
    if force or not already_configured:
        for handler in list(root.handlers):
            root.removeHandler(handler)

        handler = logging.StreamHandler(sys.stdout)
        if settings.log_format == "json":
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(ConsoleFormatter())
        root.addHandler(handler)
        root.setLevel(level)
        root._astra_configured = True  # type: ignore[attr-defined]

    return root
