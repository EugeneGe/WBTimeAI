"""Workflow 组 ORM 表（设计 §2.5 / §2.15.1；W4 裁定 R2 / T2-20）。

- :class:`Workflow`：Workflow **身份与生命周期**（``(tenant_id, name)`` 唯一；
  ``current_version_id`` 指向当前生效版本）；
- :class:`WorkflowVersion`：**不可变**版本快照（``(workflow_id, version)`` 唯一；
  ``definition`` 为**完整图快照**，发布即冻结——可重建性 ``I-P2-06`` 的基石）；
- :class:`WorkflowNode`：版本内节点（``(workflow_version_id, node_key)`` 唯一，**验收 ② 硬性**）；
- :class:`WorkflowEdge`：版本内连边（``(workflow_version_id, from_node_key, to_node_key)`` 唯一，
  防重复连边）；
- :class:`WorkflowRun`：一次运行（**固定引用** ``workflow_version_id``，可重建；
  六态含 ``WAITING_APPROVAL``）；
- :class:`WorkflowNodeRun`：节点级执行记录（``(workflow_run_id, node_key, attempt)`` 唯一；
  ``agent_run_id`` / ``tool_call_id`` / ``approval_id`` 均为**可空加性外键**）。

🔴 本模块落在 ``astra_database``（ORM 允许位置）；域实体在 ``astra_workflow.domain``。
🔴 **``approval`` 表不在此处**——随迁移 ``0010``（2a）建于 ``models/approval.py``，
   ``workflow_node_run.approval_id`` 仅为其**加性外键**（W4 裁定 §2.1 / WR-1）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = [
    "Workflow",
    "WorkflowVersion",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowRun",
    "WorkflowNodeRun",
]


class Workflow(Base, TimestampMixin):
    """Workflow：流程定义（身份与生命周期；设计 §2.5）。"""

    __tablename__ = "workflow"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_workflow_tenant_name"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(
        GUID(),
        ForeignKey("workflow_version.id", use_alter=True, name="fk_workflow_current_version_id"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(
        GUID(), ForeignKey("user.id"), nullable=False, index=True
    )


class WorkflowVersion(Base):
    """WorkflowVersion：一次发布 = 一个新版本，**不可变**（发布即冻结）。"""

    __tablename__ = "workflow_version"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version_workflow_version"),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    workflow_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("workflow.id"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by: Mapped[str] = mapped_column(
        GUID(), ForeignKey("user.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class WorkflowNode(Base):
    """WorkflowNode：版本内节点（``node_key`` 版本内唯一；**验收 ② 硬性**）。"""

    __tablename__ = "workflow_node"
    __table_args__ = (
        UniqueConstraint(
            "workflow_version_id", "node_key", name="uq_workflow_node_version_node_key"
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    workflow_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("workflow_version.id"), nullable=False, index=True
    )
    node_key: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
    position: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class WorkflowEdge(Base):
    """WorkflowEdge：版本内连边（有向；防重复连边）。"""

    __tablename__ = "workflow_edge"
    __table_args__ = (
        UniqueConstraint(
            "workflow_version_id",
            "from_node_key",
            "to_node_key",
            name="uq_workflow_edge_version_from_to",
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    workflow_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("workflow_version.id"), nullable=False, index=True
    )
    from_node_key: Mapped[str] = mapped_column(String(255), nullable=False)
    to_node_key: Mapped[str] = mapped_column(String(255), nullable=False)
    condition: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class WorkflowRun(Base, TimestampMixin):
    """WorkflowRun：一次运行（**固定引用**不可变 ``workflow_version``，可重建）。"""

    __tablename__ = "workflow_run"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    workflow_version_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("workflow_version.id"), nullable=False, index=True
    )
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("task.id"), nullable=True, index=True
    )
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)


class WorkflowNodeRun(Base, TimestampMixin):
    """WorkflowNodeRun：节点级执行记录（重放 == golden 快照的数据源 ``I-P2-06``）。"""

    __tablename__ = "workflow_node_run"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "node_key", "attempt", name="uq_workflow_node_run_run_key_attempt"
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    workflow_run_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("workflow_run.id"), nullable=False, index=True
    )
    node_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    agent_run_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent_run.id"), nullable=True, index=True
    )
    tool_call_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("tool_call.id"), nullable=True
    )
    approval_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("approval.id"), nullable=True, index=True
    )
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
