"""JSON 序列化工具。

在标准库 :mod:`json` 基础上提供统一的编码器，正确处理
``UUID`` / ``datetime`` / ``date`` / ``Enum`` 等常见类型，
确保跨包序列化行为一致。
"""

from __future__ import annotations

import json as _json
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from .time import to_iso8601

__all__ = ["AstraJSONEncoder", "default_encoder", "dumps", "loads", "dumps_compact", "dumps_pretty"]


def default_encoder(obj: Any) -> Any:
    """统一的 JSON 兜底编码器。

    支持的额外类型：``datetime`` / ``date`` / ``UUID`` / ``Enum`` / ``set``。

    Args:
        obj: 无法被标准 JSON 编码器处理的任意对象。

    Returns:
        可被 JSON 编码的替代值。

    Raises:
        TypeError: 当对象类型不被支持时。
    """
    if isinstance(obj, datetime):
        return to_iso8601(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    if hasattr(obj, "hex") and hasattr(obj, "int"):  # 兼容 uuid_utils.UUID 等
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class AstraJSONEncoder(_json.JSONEncoder):
    """Astra AI 统一 JSON 编码器（默认使用 :func:`default_encoder`）。"""

    def default(self, o: Any) -> Any:  # noqa: D102 - 继承覆盖
        return default_encoder(o)


def dumps(obj: Any, *, pretty: bool = False, **kwargs: Any) -> str:
    """序列化对象为 JSON 字符串。

    Args:
        obj: 待序列化对象。
        pretty: 是否美化输出（带缩进）。
        **kwargs: 传递给 :func:`json.dumps` 的额外参数。

    Returns:
        JSON 字符串。
    """
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("default", default_encoder)
    if pretty:
        kwargs.setdefault("indent", 2)
    return _json.dumps(obj, **kwargs)


def loads(value: str | bytes | bytearray, **kwargs: Any) -> Any:
    """解析 JSON 字符串。

    Args:
        value: JSON 文本。
        **kwargs: 传递给 :func:`json.loads` 的额外参数。

    Returns:
        反序列化后的 Python 对象。
    """
    return _json.loads(value, **kwargs)


def dumps_compact(obj: Any) -> str:
    """序列化为紧凑 JSON（无多余空格）。"""
    return dumps(obj, separators=(",", ":"))


def dumps_pretty(obj: Any) -> str:
    """序列化为美化 JSON（缩进 2）。"""
    return dumps(obj, pretty=True)
