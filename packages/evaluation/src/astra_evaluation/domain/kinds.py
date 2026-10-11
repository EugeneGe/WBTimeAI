"""``astra_evaluation`` 领域常量 / 枚举（设计 §2.13.2；W9 裁定 §3 / §4 / §5）。

值域（DB 为**普通字符串列**，免枚举迁移，F17）：

- :class:`DatasetStatus`：``DRAFT | PUBLISHED | ARCHIVED``（任务集状态，§3.1①）；
- :class:`RunStatus`：``QUEUED | RUNNING | SUCCESS | FAILED | CANCELLED``
  （Evaluation Run 状态，§3.1③）；
- :class:`ResultStatus`：``SUCCESS | FAILED | CANCELLED``（逐 case 结果状态，§3.1④）。

配套校验函数（非法值抛 ``DomainError(VALIDATION_ERROR)``，仿 ``astra_memory.domain.kinds``）。

🔴 本模块**零 Web / ORM**（仅标准库 + ``astra_core``；受 ``test_layering.py``
   ``test_evaluation_package_domain_has_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from enum import StrEnum

from astra_core import DomainError, ErrorCode

__all__ = [
    # 常量 · DatasetStatus
    "DATASET_STATUS_DRAFT",
    "DATASET_STATUS_PUBLISHED",
    "DATASET_STATUS_ARCHIVED",
    # 常量 · RunStatus
    "RUN_STATUS_QUEUED",
    "RUN_STATUS_RUNNING",
    "RUN_STATUS_SUCCESS",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_CANCELLED",
    # 常量 · ResultStatus
    "RESULT_STATUS_SUCCESS",
    "RESULT_STATUS_FAILED",
    "RESULT_STATUS_CANCELLED",
    # 常量 · 通用
    "DEFAULT_DATASET_VERSION",
    "CANCELLED_ERROR_TYPE",
    # 枚举
    "DatasetStatus",
    "RunStatus",
    "ResultStatus",
    # 校验
    "assert_dataset_status",
    "assert_run_status",
    "assert_result_status",
]

# -- DatasetStatus（任务集状态） ---------------------------------------------

DATASET_STATUS_DRAFT = "DRAFT"
DATASET_STATUS_PUBLISHED = "PUBLISHED"
DATASET_STATUS_ARCHIVED = "ARCHIVED"

# -- RunStatus（Evaluation Run 状态） ----------------------------------------

RUN_STATUS_QUEUED = "QUEUED"
RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_SUCCESS = "SUCCESS"
RUN_STATUS_FAILED = "FAILED"
RUN_STATUS_CANCELLED = "CANCELLED"

# -- ResultStatus（逐 case 结果状态） ----------------------------------------

RESULT_STATUS_SUCCESS = "SUCCESS"
RESULT_STATUS_FAILED = "FAILED"
RESULT_STATUS_CANCELLED = "CANCELLED"

# -- 通用常量 ----------------------------------------------------------------

#: 任务集初始版本号（单调 +1，R12）。
DEFAULT_DATASET_VERSION = 1

#: 取消统一 ``error_type``（R6 / §5.3，「取消统一 ``CANCELLED``」）。
CANCELLED_ERROR_TYPE = "CANCELLED"


class DatasetStatus(StrEnum):
    """任务集状态（设计 §2.13.2 / W9 裁定 §3.1①，**冻结**）。"""

    DRAFT = DATASET_STATUS_DRAFT
    PUBLISHED = DATASET_STATUS_PUBLISHED
    ARCHIVED = DATASET_STATUS_ARCHIVED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class RunStatus(StrEnum):
    """Evaluation Run 状态（设计 §2.13.2 / W9 裁定 §3.1③，**冻结**）。"""

    QUEUED = RUN_STATUS_QUEUED
    RUNNING = RUN_STATUS_RUNNING
    SUCCESS = RUN_STATUS_SUCCESS
    FAILED = RUN_STATUS_FAILED
    CANCELLED = RUN_STATUS_CANCELLED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def terminal_values(cls) -> tuple[str, ...]:
        """返回终态字面值（``SUCCESS | FAILED | CANCELLED``）。"""
        return (RUN_STATUS_SUCCESS, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED)


class ResultStatus(StrEnum):
    """逐 case 结果状态（设计 §2.13.2 / W9 裁定 §3.1④，**冻结**）。"""

    SUCCESS = RESULT_STATUS_SUCCESS
    FAILED = RESULT_STATUS_FAILED
    CANCELLED = RESULT_STATUS_CANCELLED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


def _normalize(value: str | StrEnum) -> str:
    """将枚举 / 字符串统一为字面值。"""
    return value.value if isinstance(value, StrEnum) else str(value)


def _assert_membership(*, value: str | StrEnum, allowed: tuple[str, ...], field: str) -> str:
    """断言 ``value`` 属于 ``allowed``，否则抛 ``DomainError(VALIDATION_ERROR)``。

    Args:
        value: 待校验值（枚举 / 字符串）。
        allowed: 合法字面值集合。
        field: 字段名（用于错误 ``data``）。

    Returns:
        归一化后的合法字面值。

    Raises:
        DomainError: 值非法（``VALIDATION_ERROR``）。
    """
    normalized = _normalize(value)
    if normalized not in allowed:
        raise DomainError(
            f"非法 {field}：{normalized!r}（合法值：{list(allowed)}）",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "invalid_evaluation_value", "field": field, "value": normalized},
        )
    return normalized


def assert_dataset_status(value: str | DatasetStatus) -> str:
    """断言 ``status`` 合法，返回归一化字面值。"""
    return _assert_membership(value=value, allowed=DatasetStatus.values(), field="status")


def assert_run_status(value: str | RunStatus) -> str:
    """断言 Run ``status`` 合法，返回归一化字面值。"""
    return _assert_membership(value=value, allowed=RunStatus.values(), field="status")


def assert_result_status(value: str | ResultStatus) -> str:
    """断言结果 ``status`` 合法，返回归一化字面值。"""
    return _assert_membership(value=value, allowed=ResultStatus.values(), field="status")
