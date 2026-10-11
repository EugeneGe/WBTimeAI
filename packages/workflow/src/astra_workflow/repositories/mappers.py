"""ORM 行 ↔ 领域实体映射（Workflow 组六类）。

将 ``astra_database.models.workflow`` 的 SQLAlchemy 行与 ``astra_workflow.domain``
领域实体互转。

🔴 落在能力包 ``repositories/``（显式允许的 ORM 落点，能力包仅禁 Web）。
"""

from __future__ import annotations

from datetime import datetime

from astra_common.time import ensure_utc, utcnow
from astra_database.models.workflow import Workflow as OrmWorkflow
from astra_database.models.workflow import WorkflowEdge as OrmWorkflowEdge
from astra_database.models.workflow import WorkflowNode as OrmWorkflowNode
from astra_database.models.workflow import WorkflowNodeRun as OrmWorkflowNodeRun
from astra_database.models.workflow import WorkflowRun as OrmWorkflowRun
from astra_database.models.workflow import WorkflowVersion as OrmWorkflowVersion

from ..domain import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowVersion,
)

__all__ = [
    "workflow_to_domain",
    "workflow_to_orm",
    "workflow_version_to_domain",
    "workflow_version_to_orm",
    "workflow_node_to_domain",
    "workflow_node_to_orm",
    "workflow_edge_to_domain",
    "workflow_edge_to_orm",
    "workflow_run_to_domain",
    "workflow_run_to_orm",
    "workflow_node_run_to_domain",
    "workflow_node_run_to_orm",
]


def _dt(value: datetime | None) -> datetime:
    """归一化时间戳：``None`` 时回退当前 UTC。"""
    return value if value is not None else utcnow()


def _opt_dt(value: datetime | None) -> datetime | None:
    """归一化**可空**时间戳：``None`` 原样返回；否则归一为 UTC-aware（``_dt()`` 会误填 now）。"""
    return ensure_utc(value) if value is not None else None


def _json(value: dict | None) -> dict:
    """归一化 JSON 列：``None`` 时回退空字典。"""
    return dict(value) if value else {}


def _opt_json(value: dict | None) -> dict | None:
    """归一化可空 JSON 列：``None`` 原样返回。"""
    return dict(value) if value is not None else None


# -- Workflow ---------------------------------------------------------------


def workflow_to_domain(row: OrmWorkflow) -> Workflow:
    """ORM Workflow 行 → 领域 ``Workflow``。"""
    return Workflow(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        name=row.name,
        description=row.description,
        workspace_id=row.workspace_id,
        status=row.status,
        current_version_id=row.current_version_id,
        created_by=row.created_by,
    )


def workflow_to_orm(entity: Workflow) -> OrmWorkflow:
    """领域 ``Workflow`` → ORM 行。"""
    return OrmWorkflow(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        name=entity.name,
        description=entity.description,
        workspace_id=entity.workspace_id,
        status=entity.status,
        current_version_id=entity.current_version_id,
        created_by=entity.created_by,
    )


# -- WorkflowVersion --------------------------------------------------------


def workflow_version_to_domain(row: OrmWorkflowVersion) -> WorkflowVersion:
    """ORM WorkflowVersion 行 → 领域 ``WorkflowVersion``（**不可变**快照）。"""
    return WorkflowVersion(
        id=row.id,
        workflow_id=row.workflow_id,
        version=row.version,
        definition=_json(row.definition),
        status=row.status,
        created_by=row.created_by,
        created_at=_dt(getattr(row, "created_at", None)),
    )


def workflow_version_to_orm(entity: WorkflowVersion) -> OrmWorkflowVersion:
    """领域 ``WorkflowVersion`` → ORM 行。"""
    return OrmWorkflowVersion(
        id=entity.id,
        workflow_id=entity.workflow_id,
        version=entity.version,
        definition=_json(entity.definition),
        status=entity.status,
        created_by=entity.created_by,
        created_at=_dt(entity.created_at),
    )


# -- WorkflowNode -----------------------------------------------------------


def workflow_node_to_domain(row: OrmWorkflowNode) -> WorkflowNode:
    """ORM WorkflowNode 行 → 领域 ``WorkflowNode``（**不可变**快照）。"""
    return WorkflowNode(
        id=row.id,
        workflow_version_id=row.workflow_version_id,
        node_key=row.node_key,
        type=row.type,
        config=_json(row.config),
        position=_json(row.position),
        created_at=_dt(getattr(row, "created_at", None)),
    )


def workflow_node_to_orm(entity: WorkflowNode) -> OrmWorkflowNode:
    """领域 ``WorkflowNode`` → ORM 行。"""
    return OrmWorkflowNode(
        id=entity.id,
        workflow_version_id=entity.workflow_version_id,
        node_key=entity.node_key,
        type=entity.type,
        config=_json(entity.config),
        position=_json(entity.position),
        created_at=_dt(entity.created_at),
    )


# -- WorkflowEdge -----------------------------------------------------------


def workflow_edge_to_domain(row: OrmWorkflowEdge) -> WorkflowEdge:
    """ORM WorkflowEdge 行 → 领域 ``WorkflowEdge``（**不可变**快照）。"""
    return WorkflowEdge(
        id=row.id,
        workflow_version_id=row.workflow_version_id,
        from_node_key=row.from_node_key,
        to_node_key=row.to_node_key,
        condition=row.condition,
        created_at=_dt(getattr(row, "created_at", None)),
    )


def workflow_edge_to_orm(entity: WorkflowEdge) -> OrmWorkflowEdge:
    """领域 ``WorkflowEdge`` → ORM 行。"""
    return OrmWorkflowEdge(
        id=entity.id,
        workflow_version_id=entity.workflow_version_id,
        from_node_key=entity.from_node_key,
        to_node_key=entity.to_node_key,
        condition=entity.condition,
        created_at=_dt(entity.created_at),
    )


# -- WorkflowRun ------------------------------------------------------------


def workflow_run_to_domain(row: OrmWorkflowRun) -> WorkflowRun:
    """ORM WorkflowRun 行 → 领域 ``WorkflowRun``。"""
    return WorkflowRun(
        id=row.id,
        tenant_id=row.tenant_id,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        workflow_version_id=row.workflow_version_id,
        trigger=row.trigger,
        status=row.status,
        task_id=row.task_id,
        input=_opt_json(row.input),
        output=_opt_json(row.output),
        started_at=_opt_dt(row.started_at),
        completed_at=_opt_dt(row.completed_at),
        error=row.error,
    )


def workflow_run_to_orm(entity: WorkflowRun) -> OrmWorkflowRun:
    """领域 ``WorkflowRun`` → ORM 行。"""
    return OrmWorkflowRun(
        id=entity.id,
        tenant_id=entity.tenant_id or "",
        workflow_version_id=entity.workflow_version_id,
        trigger=entity.trigger,
        status=entity.status,
        task_id=entity.task_id,
        input=_opt_json(entity.input),
        output=_opt_json(entity.output),
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        error=entity.error,
    )


# -- WorkflowNodeRun --------------------------------------------------------


def workflow_node_run_to_domain(row: OrmWorkflowNodeRun) -> WorkflowNodeRun:
    """ORM WorkflowNodeRun 行 → 领域 ``WorkflowNodeRun``。"""
    return WorkflowNodeRun(
        id=row.id,
        tenant_id=None,
        created_at=_dt(getattr(row, "created_at", None)),
        updated_at=_dt(getattr(row, "updated_at", None)),
        workflow_run_id=row.workflow_run_id,
        node_key=row.node_key,
        status=row.status,
        attempt=int(row.attempt or 1),
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        approval_id=row.approval_id,
        input=_opt_json(row.input),
        output=_opt_json(row.output),
        started_at=_opt_dt(row.started_at),
        completed_at=_opt_dt(row.completed_at),
    )


def workflow_node_run_to_orm(entity: WorkflowNodeRun) -> OrmWorkflowNodeRun:
    """领域 ``WorkflowNodeRun`` → ORM 行。"""
    return OrmWorkflowNodeRun(
        id=entity.id,
        workflow_run_id=entity.workflow_run_id,
        node_key=entity.node_key,
        status=entity.status,
        attempt=entity.attempt,
        agent_run_id=entity.agent_run_id,
        tool_call_id=entity.tool_call_id,
        approval_id=entity.approval_id,
        input=_opt_json(entity.input),
        output=_opt_json(entity.output),
        started_at=entity.started_at,
        completed_at=entity.completed_at,
    )
