"""幂等键（W7 / T2-39；R6 冻结契约）。

幂等键 = ``f"{target_type}:{target_id}:{fire_time.isoformat()}"``——同一
``(target_type, target_id, fire_time)`` 二次触发**只产生 1 个 task**（命中
``task.idempotency_key`` 唯一索引 → 返回既有 task，§2.9）。

🔴 **零 ORM**：本模块**不 import** ``astra_database`` / ``sqlalchemy``（硬门禁，R2）。
"""

from __future__ import annotations

from datetime import datetime

__all__ = ["IdempotencyKey", "idempotency_key"]


def idempotency_key(target_type: str, target_id: str, fire_time: datetime) -> str:
    """生成幂等键（``f"{target_type}:{target_id}:{fire_time.isoformat()}"``）。

    Args:
        target_type: 目标类型（``agent`` / ``workflow``…）。
        target_id: 目标标识。
        fire_time: 本次触发时间（UTC，tz-aware）。

    Returns:
        字符串幂等键。
    """
    return f"{target_type}:{target_id}:{fire_time.isoformat()}"


class IdempotencyKey:
    """幂等键生成器（命名空间封装，便于注入 / 替换）。"""

    @staticmethod
    def key(target_type: str, target_id: str, fire_time: datetime) -> str:
        """生成幂等键（见 :func:`idempotency_key`）。"""
        return idempotency_key(target_type, target_id, fire_time)

    @staticmethod
    def for_schedule(target_type: str, target_id: str, fire_time: datetime) -> str:
        """按调度三元组生成幂等键（``key`` 的语义别名）。"""
        return idempotency_key(target_type, target_id, fire_time)
