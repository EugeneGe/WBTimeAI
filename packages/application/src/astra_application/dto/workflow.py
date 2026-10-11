"""Workflow 相关 DTO（设计 §2.5 / §2.12；应用层，零框架依赖）。

- :class:`WorkflowDTO`：Workflow 聚合视图（身份 / 生命周期 / 当前版本）；
- :class:`WorkflowVersionDTO`：**不可变**版本快照视图（``definition`` 为完整图快照）；
- :class:`WorkflowRunDTO`：一次运行视图（**固定引用**版本，可重建 ``I-P2-06``）；
- :class:`WorkflowNodeRunDTO`：节点级执行记录视图（重放数据源）。

🔴 与 :mod:`astra_application.dto.run` 同口径：DTO 为**纯值**，仅由领域实体构造；
   应用层**不感知** Web / ORM（``test_application_import_boundary`` 强制）。

🔴 约定（A27）：业务 DTO 顶层键**不得**同时使用 ``{code, message, data, request_id}``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astra_workflow import Workflow, WorkflowNodeRun, WorkflowRun, WorkflowVersion

from .base import DTO

__all__ = [
    "WorkflowDTO",
    "WorkflowVersionDTO",
    "WorkflowRunDTO",
    "WorkflowNodeRunDTO",
]


@dataclass
class WorkflowDTO(DTO):
    """Workflow 聚合 DTO（身份 / 生命周期 / ``current_version_id``）。"""

    id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    name: str = ""
    description: str | None = None
    status: str = "DRAFT"
    current_version_id: str | None = None
    created_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: Workflow) -> WorkflowDTO:
        """由 Workflow 实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            workspace_id=entity.workspace_id,
            name=entity.name,
            description=entity.description,
            status=entity.status,
            current_version_id=entity.current_version_id,
            created_by=entity.created_by,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


@dataclass
class WorkflowVersionDTO(DTO):
    """WorkflowVersion DTO（**不可变**快照：``definition`` 为完整图快照）。"""

    id: str
    workflow_id: str = ""
    version: str = ""
    status: str = "DRAFT"
    definition: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: WorkflowVersion) -> WorkflowVersionDTO:
        """由 WorkflowVersion 实体构造 DTO。"""
        return cls(
            id=entity.id,
            workflow_id=entity.workflow_id,
            version=entity.version,
            status=entity.status,
            definition=dict(entity.definition or {}),
            created_by=entity.created_by,
            created_at=entity.created_at,
        )


@dataclass
class WorkflowRunDTO(DTO):
    """WorkflowRun DTO（一次运行；``workflow_version_id`` 恒定，可重建）。"""

    id: str
    tenant_id: str | None = None
    workflow_version_id: str = ""
    trigger: str = "user"
    status: str = "PENDING"
    task_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    @classmethod
    def from_entity(cls, entity: WorkflowRun) -> WorkflowRunDTO:
        """由 WorkflowRun 实体构造 DTO。"""
        return cls(
            id=entity.id,
            tenant_id=entity.tenant_id,
            workflow_version_id=entity.workflow_version_id,
            trigger=entity.trigger,
            status=entity.status,
            task_id=entity.task_id,
            input=dict(entity.input or {}),
            output=dict(entity.output) if entity.output is not None else None,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            error=entity.error,
        )


@dataclass
class WorkflowNodeRunDTO(DTO):
    """WorkflowNodeRun DTO（节点级执行记录；重放 == golden 快照的数据源）。"""

    id: str
    workflow_run_id: str = ""
    node_key: str = ""
    status: str = "PENDING"
    attempt: int = 1
    agent_run_id: str | None = None
    tool_call_id: str | None = None
    approval_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_entity(cls, entity: WorkflowNodeRun) -> WorkflowNodeRunDTO:
        """由 WorkflowNodeRun 实体构造 DTO。"""
        return cls(
            id=entity.id,
            workflow_run_id=entity.workflow_run_id,
            node_key=entity.node_key,
            status=entity.status,
            attempt=int(entity.attempt or 1),
            agent_run_id=entity.agent_run_id,
            tool_call_id=entity.tool_call_id,
            approval_id=entity.approval_id,
            input=dict(entity.input or {}),
            output=dict(entity.output or {}),
            started_at=entity.started_at,
            completed_at=entity.completed_at,
        )
