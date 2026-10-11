"""UTC 时间工具。

约定：平台内时间戳统一使用 **UTC 时区感知（timezone-aware）** 的
:class:`datetime.datetime`；对外序列化统一为 ISO 8601 字符串。
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utcnow", "to_iso8601", "from_iso8601", "ensure_utc"]


def utcnow() -> datetime:
    """返回当前 UTC 时间（timezone-aware）。

    Returns:
        带 ``timezone.utc`` 时区的当前时间。
    """
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """将 ``datetime`` 归一化为 UTC 时区感知对象。

    - 若 ``value`` 无时区信息，则视为 UTC；
    - 若带时区，则转换为 UTC。

    Args:
        value: 待归一化的时间对象。

    Returns:
        归一化后的 UTC 时间对象。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_iso8601(value: datetime) -> str:
    """将 ``datetime`` 序列化为 ISO 8601 字符串（UTC）。

    Args:
        value: 待序列化的时间对象。

    Returns:
        ISO 8601 字符串（例如 ``2025-01-01T00:00:00+00:00``）。
    """
    return ensure_utc(value).isoformat()


def from_iso8601(value: str) -> datetime:
    """将 ISO 8601 字符串解析为 UTC 时间对象。

    Args:
        value: ISO 8601 字符串；``Z`` 后缀会被兼容处理。

    Returns:
        UTC 时间对象。

    Raises:
        ValueError: 当字符串不是合法的 ISO 8601 时间时。
    """
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    return ensure_utc(parsed)
