"""Astra AI 通用类型与工具（base 层）。

本包不依赖任何第三方库，作为全平台最底层被复用：

- :mod:`astra_common.types`：通用类型别名（``ID`` / ``JSONDict`` 等）
- :mod:`astra_common.time`：UTC 时间工具（``utcnow()`` 等）
- :mod:`astra_common.json`：JSON 序列化工具（含 UUID / datetime 编码器）
"""

from __future__ import annotations

from .json import dumps, dumps_compact, dumps_pretty, loads
from .time import ensure_utc, from_iso8601, to_iso8601, utcnow
from .types import ID, JSONDict, JSONList, JSONValue, T

__all__ = [
    # types
    "ID",
    "T",
    "JSONValue",
    "JSONDict",
    "JSONList",
    # time
    "utcnow",
    "to_iso8601",
    "from_iso8601",
    "ensure_utc",
    # json
    "dumps",
    "loads",
    "dumps_compact",
    "dumps_pretty",
]
