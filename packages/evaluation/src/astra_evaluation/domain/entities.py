"""``astra_evaluation`` 领域实体（设计 §2.13.2；W9 裁定 §4）。

- :class:`EvaluationDataset`：**可变聚合根**（任务集；``status`` 词表校验 + ``clone_as_new_version``
  意图；PUBLISHED 后连同用例构成**不可变版本**）；
- :class:`EvaluationCase`：任务用例（``dataset_id`` + ``case_key`` 唯一；关联 PUBLISHED 数据集后
  **不可修改**）；
- :class:`EvaluationRun`：一次批量评测（**固定** ``dataset_id`` 与 ``agent_version_id``，可重放；
  ``idempotency_key`` 可空唯一）；
- :class:`EvaluationResult`：逐 case 结果（``score`` 0–1；每 case 每 Run 恰一条）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py``
   ``test_evaluation_package_domain_has_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astra_domain import AggregateRoot

from .kinds import (
    DATASET_STATUS_DRAFT,
    DEFAULT_DATASET_VERSION,
    RUN_STATUS_QUEUED,
    DatasetStatus,
    RunStatus,
    assert_dataset_status,
    assert_result_status,
    assert_run_status,
)

__all__ = [
    "EvaluationDataset",
    "EvaluationCase",
    "EvaluationRun",
    "EvaluationResult",
]


@dataclass
class EvaluationDataset(AggregateRoot):
    """任务集（**可变聚合根**；设计 §2.13.2 / §4.3）。

    Attributes:
        tenant_id: 所属租户标识（**强制**，隔离不变量；基类字段）。
        organization_id: 组织归属（可空；A-7）。
        workspace_id: 归属工作区标识（可空）。
        name: 任务集名称。
        version: 版本号（默认 1，克隆时 +1；R12）。
        parent_dataset_id: 克隆溯源父任务集标识（可空）。
        status: 状态（``DatasetStatus`` 字面值；默认 ``DRAFT``）。
        description: 描述（可空）。
        created_by: 创建者用户标识（可空）。
    """

    organization_id: str | None = None
    workspace_id: str | None = None
    name: str = ""
    version: int = DEFAULT_DATASET_VERSION
    parent_dataset_id: str | None = None
    status: str = DATASET_STATUS_DRAFT
    description: str | None = None
    created_by: str | None = None

    def is_published(self) -> bool:
        """是否为已发布（不可变）版本。"""
        return self.status == DatasetStatus.PUBLISHED.value

    def publish(self) -> None:
        """置为已发布（``PUBLISHED``；此后用例不可修改）。"""
        self.status = DatasetStatus.PUBLISHED.value
        self.touch()

    def assert_valid(self) -> None:
        """断言状态合法。

        Raises:
            DomainError: 非法状态（``VALIDATION_ERROR``）。
        """
        assert_dataset_status(self.status)


@dataclass
class EvaluationCase(AggregateRoot):
    """任务用例（子资源；设计 §2.13.2）。

    🔴 唯一键 ``(dataset_id, case_key)``（**域内不表达约束**，落 ORM / 迁移唯一约束；
       本实体仅承载结构）。子资源**经父推导**（无 tenant / org / workspace 列）。

    Attributes:
        dataset_id: 所属任务集标识。
        case_key: 用例键（同任务集内唯一）。
        input: 输入（任意 JSON；**不得含凭证**）。
        expected: 期望值（可空）。
        assertions: 断言配置 ``list[{scorer, weight, params}]``（§5.4 / R6）。
        tags: 标签（可空）。
        position: 排序位次（默认 0）。
    """

    dataset_id: str = ""
    case_key: str = ""
    input: Any = None
    expected: Any = None
    assertions: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] | None = None
    position: int = 0


@dataclass
class EvaluationRun(AggregateRoot):
    """一次批量评测（**固定版本可重放**；设计 §2.13.2 / §4.2 / §4.4）。

    Attributes:
        tenant_id: 所属租户标识（**强制**；基类字段）。
        organization_id: 组织归属（可空；A-7）。
        workspace_id: 归属工作区标识（可空）。
        dataset_id: 目标任务集标识（**固定版本**）。
        agent_id: 目标 Agent 标识。
        agent_version_id: 目标 Agent 版本标识（**固定版本，可重放**）。
        status: 状态（``RunStatus`` 字面值；默认 ``QUEUED``）。
        idempotency_key: 幂等键（可空；唯一，NULL 可重复）。
        started_at: 开始时刻（可空）。
        completed_at: 完成时刻（可空）。
        summary: 汇总（通过率 / 平均分 / N/A 口径；可空）。
        created_by: 创建者用户标识（可空）。
    """

    organization_id: str | None = None
    workspace_id: str | None = None
    dataset_id: str = ""
    agent_id: str = ""
    agent_version_id: str = ""
    status: str = RUN_STATUS_QUEUED
    idempotency_key: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: dict[str, Any] | None = None
    created_by: str | None = None

    def is_terminal(self) -> bool:
        """是否为终态（``SUCCESS | FAILED | CANCELLED``）。"""
        return self.status in RunStatus.terminal_values()

    def assert_valid(self) -> None:
        """断言状态合法。

        Raises:
            DomainError: 非法状态（``VALIDATION_ERROR``）。
        """
        assert_run_status(self.status)


@dataclass
class EvaluationResult(AggregateRoot):
    """逐 case 结果（子资源；设计 §2.13.2）。

    每 ``(evaluation_run_id, case_id)`` 恰一条（ORM 唯一约束）。

    Attributes:
        evaluation_run_id: 所属评测标识。
        case_id: 对应用例标识。
        agent_run_id: 实际执行的 ``agent_run`` 标识（可空；全链路溯源）。
        status: 结果状态（``ResultStatus`` 字面值）。
        score: 得分（0–1；无断言 → ``None``（``N/A``，**不视为 0**））。
        assertion_results: 逐断言结果 ``list[{scorer, passed, weight, score, detail}]``（可空）。
        duration_ms: 耗时（毫秒，可空）。
        token_usage: token 用量（JSON，可空）。
        cost: 成本（可空）。
        error_type: 稳定 ``ErrorCode``（取消统一 ``CANCELLED``；可空）。
    """

    evaluation_run_id: str = ""
    case_id: str = ""
    agent_run_id: str | None = None
    status: str = ""
    score: float | None = None
    assertion_results: list[dict[str, Any]] | None = None
    duration_ms: int | None = None
    token_usage: dict[str, Any] | None = None
    cost: float | None = None
    error_type: str | None = None

    def assert_valid(self) -> None:
        """断言结果状态合法。

        Raises:
            DomainError: 非法状态（``VALIDATION_ERROR``）。
        """
        assert_result_status(self.status)
