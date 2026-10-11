"""统一 ID 入口（决策 D2）。

**全平台唯一 ID 入口**：一切实体主键 / 外键均通过 :func:`generate_id` 生成，
产出 **UUIDv7** 字符串（时间有序、索引友好、无需中心协调）。

实现策略：
- 优先使用 ``uuid-utils``（Rust 实现，``uuid7`` 高效且为业界常用依赖）；
- 若运行环境缺失该库，则回退到纯 Python 的 UUIDv7 实现（RFC 9562 布局，
  :func:`_pure_python_uuid7`），以保证 ``generate_id()`` 始终可用。

🔴 禁止在其它模块调用 ``uuid.uuid4()`` / ``uuid4()`` —— 统一入口由 T0-10 的
   扫描断言（``tests/integration/test_id_convention.py``）守护。
"""

from __future__ import annotations

import os
import time
from uuid import UUID

__all__ = ["generate_id", "new_uuid7"]

#: UUIDv7 时间戳位数（毫秒，48 位）。
_TIMESTAMP_BITS = 48
_TIMESTAMP_MASK = (1 << _TIMESTAMP_BITS) - 1

# 模块级探测 ``uuid-utils`` 是否可用。
# 🔴 关键：探测必须发生在**模块级**（而非函数体内），否则 ImportError 永不在
#   导入期抛出，``except`` 回退分支将不可达。此处保留 pragma：具体走哪个分支
#   依运行环境而定（本机两者均可能）。
try:  # pragma: no cover - 依环境而定
    from uuid_utils import uuid7 as _uuid7_impl

    _HAS_UUID_UTILS = True
except ImportError:  # pragma: no cover - 依环境而定
    _uuid7_impl = None  # type: ignore[assignment]
    _HAS_UUID_UTILS = False


def _pure_python_uuid7() -> UUID:
    """纯 Python 的 UUIDv7 生成（RFC 9562 布局）。

    布局（128 bit）：48 位毫秒时间戳 | 4 位版本(7) | 12 位 rand_a |
    2 位变体(10) | 62 位 rand_b。

    Returns:
        版本为 7、变体为 RFC 4122 的 :class:`~uuid.UUID`。
    """
    timestamp_ms = int(time.time() * 1000) & _TIMESTAMP_MASK
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bit
    rand_a = (rand >> 68) & 0xFFF  # 高 12 bit
    rand_b = rand & ((1 << 62) - 1)  # 低 62 bit
    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b
    return UUID(int=value)


def new_uuid7() -> UUID:
    """生成一个 UUIDv7 对象。

    优先使用 ``uuid-utils``；运行环境缺失该库时回退到纯 Python 实现。

    Returns:
        版本为 7 的 :class:`~uuid.UUID`。
    """
    if _HAS_UUID_UTILS:
        return UUID(str(_uuid7_impl()))
    return _pure_python_uuid7()


def generate_id() -> str:
    """生成一个新的 UUIDv7 字符串。

    Returns:
        标准 36 字符的 UUID 字符串（版本位为 ``7``，小写、带连字符），
        按时间单调递增，可直接用于字符串排序。
    """
    return str(new_uuid7())
