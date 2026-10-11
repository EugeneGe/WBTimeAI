"""Evaluation 组 ORM 表（设计 §2.13.2 / §2.15.4；W9 裁定 §3.1 / R3）。

- :class:`EvaluationDataset`：任务集（L1 租户资源根；``status(DRAFT|PUBLISHED|ARCHIVED)``）；
- :class:`EvaluationCase`：任务用例（子资源 → 经父推导，无 tenant / org / workspace 列，
  镜像 ``memory_relation``）；
- :class:`EvaluationRun`：一次批量评测（L1 租户资源根；``idempotency_key`` 唯一可空）；
- :class:`EvaluationResult`：逐 case 结果（子资源 → 经父推导）。

🔴 组织范围落点（R3）：``evaluation_dataset`` / ``evaluation_run`` 落**直接列**
   ``organization_id``（可空 + 索引 + FK，镜像 ``0016`` L1）+ ``workspace_id``（可空 + 索引 +
   FK）；``evaluation_case`` / ``evaluation_result`` **经父推导**（不下组织列）。
🔴 单链：表由迁移 ``0017_phase2_evaluation`` 建立（「建表即含」列 + 唯一约束 + 索引 + 无回填）。
🔴 枚举列一律 ``String(50)``（app 层词表，**无 DB enum**，F17）；JSON 列一律 ``JSONType()``。

🔴 本模块落在 ``astra_database``（ORM 允许位置）；域实体在 ``astra_evaluation.domain``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = [
    "EvaluationDataset",
    "EvaluationCase",
    "EvaluationRun",
    "EvaluationResult",
]


class EvaluationDataset(Base, TimestampMixin):
    """``evaluation_dataset``：任务集（L1 租户资源根；A-7 组织范围）。"""

    __tablename__ = "evaluation_dataset"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · A-7；R3 直接列）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    parent_dataset_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("evaluation_dataset.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_by: Mapped[str | None] = mapped_column(GUID(), ForeignKey("user.id"), nullable=True)


class EvaluationCase(Base):
    """``evaluation_case``：任务用例（子资源；唯一键 ``(dataset_id, case_key)``）。"""

    __tablename__ = "evaluation_case"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "case_key",
            name="uq_evaluation_case_dataset_case_key",
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    dataset_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("evaluation_dataset.id"), nullable=False, index=True
    )
    case_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input: Mapped[Any] = mapped_column(JSONType(), nullable=False)
    expected: Mapped[Any | None] = mapped_column(JSONType(), nullable=True)
    assertions: Mapped[Any | None] = mapped_column(JSONType(), nullable=True)
    tags: Mapped[Any | None] = mapped_column(JSONType(), nullable=True)
    position: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class EvaluationRun(Base, TimestampMixin):
    """``evaluation_run``：一次批量评测（固定版本可重放；``idempotency_key`` 唯一可空）。"""

    __tablename__ = "evaluation_run"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_evaluation_run_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    dataset_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("evaluation_dataset.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent.id"), nullable=False, index=True
    )
    agent_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("agent_version.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="QUEUED")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(GUID(), ForeignKey("user.id"), nullable=True)


class EvaluationResult(Base):
    """``evaluation_result``：逐 case 结果（子资源；唯一键 ``(evaluation_run_id, case_id)``）。"""

    __tablename__ = "evaluation_result"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id",
            "case_id",
            name="uq_evaluation_result_run_case",
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    evaluation_run_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("evaluation_run.id"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("evaluation_case.id"), nullable=False, index=True
    )
    agent_run_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent_run.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float | None] = mapped_column(Float(), nullable=True)
    assertion_results: Mapped[Any | None] = mapped_column(JSONType(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    cost: Mapped[float | None] = mapped_column(Float(), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
