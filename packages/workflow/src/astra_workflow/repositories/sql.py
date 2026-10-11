"""``SqlWorkflowRepository`` 等（实现 ``astra_workflow`` 的领域仓储 Protocol）。

- :class:`SqlWorkflowRepository`（``workflow`` 表，``(tenant_id, name)`` 唯一）；
- :class:`SqlWorkflowVersionRepository`（``workflow_version`` 表；``update()`` 内置
  **发布即冻结**守卫——已 ``PUBLISHED`` 行的 ``definition`` 变更 → ``CONFLICT``）；
- :class:`SqlWorkflowRunRepository`（``workflow_run`` 表；固定引用版本，可重建）；
- :class:`SqlWorkflowNodeRunRepository`（``workflow_node_run`` 表；重放数据源）。

🔴 落在能力包 ``repositories/``（W4 裁定 R3 §3.1；能力包仅禁 Web，ORM 允许）。
"""

from __future__ import annotations

import builtins
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_database import apply_scope, session_scope
from astra_database.models.workflow import Workflow as OrmWorkflow
from astra_database.models.workflow import WorkflowNodeRun as OrmWorkflowNodeRun
from astra_database.models.workflow import WorkflowRun as OrmWorkflowRun
from astra_database.models.workflow import WorkflowVersion as OrmWorkflowVersion
from astra_domain import ScopeFilter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..domain import (
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    Workflow,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowVersion,
)
from .mappers import (
    workflow_node_run_to_domain,
    workflow_node_run_to_orm,
    workflow_run_to_domain,
    workflow_run_to_orm,
    workflow_to_domain,
    workflow_to_orm,
    workflow_version_to_domain,
    workflow_version_to_orm,
)

__all__ = [
    "SqlWorkflowRepository",
    "SqlWorkflowVersionRepository",
    "SqlWorkflowRunRepository",
    "SqlWorkflowNodeRunRepository",
]


class SqlWorkflowRepository:
    """基于 SQLAlchemy 的 Workflow 仓储（``workflow`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> Workflow | None:
        """按主键获取 Workflow，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflow, entity_id)
            return workflow_to_domain(row) if row is not None else None

    def get_by_name(self, tenant_id: str, name: str) -> Workflow | None:
        """按 ``(tenant_id, name)`` 获取 Workflow，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmWorkflow).where(
                OrmWorkflow.tenant_id == tenant_id, OrmWorkflow.name == name
            )
            row = session.execute(statement).scalars().first()
            return workflow_to_domain(row) if row is not None else None

    def add(self, entity: Workflow) -> Workflow:
        """新增 Workflow 并返回。"""
        with session_scope(self._session_factory) as session:
            row = workflow_to_orm(entity)
            session.add(row)
            session.flush()
            return workflow_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[Workflow]:
        """按等值条件列出 Workflow（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmWorkflow)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmWorkflow, field) == value)
            statement = apply_scope(statement, OrmWorkflow, scope)
            rows = session.execute(statement).scalars().all()
            return [workflow_to_domain(row) for row in rows]

    def list_by_tenant(self, tenant_id: str) -> builtins.list[Workflow]:
        """列出某租户下的全部 Workflow。"""
        return self.list(tenant_id=tenant_id)

    def update(self, entity: Workflow) -> Workflow:
        """更新 Workflow 并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflow, entity.id)
            if row is None:
                return workflow_to_domain(workflow_to_orm(entity))
            row.name = entity.name
            row.description = entity.description
            row.workspace_id = entity.workspace_id
            row.status = entity.status
            row.current_version_id = entity.current_version_id
            session.flush()
            return workflow_to_domain(row)

    def delete(self, entity: Workflow) -> None:
        """删除 Workflow。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflow, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlWorkflowVersionRepository:
    """基于 SQLAlchemy 的 WorkflowVersion 仓储（``workflow_version`` 表）。

    ``update()`` 内置**发布即冻结**守卫：已 ``PUBLISHED`` 行的 ``definition`` 与库中值
    不一致 → ``DomainError(CONFLICT, published_immutable)``（仅允许 ``status`` 变更）。
    此为保证可重建性 ``I-P2-06`` 的**仓储层**第二道闸（域层 ``frozen`` 为第一道）。
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> WorkflowVersion | None:
        """按主键获取版本，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowVersion, entity_id)
            return workflow_version_to_domain(row) if row is not None else None

    def get_by_version(self, workflow_id: str, version: str) -> WorkflowVersion | None:
        """按 ``(workflow_id, version)`` 获取版本，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmWorkflowVersion).where(
                OrmWorkflowVersion.workflow_id == workflow_id,
                OrmWorkflowVersion.version == version,
            )
            row = session.execute(statement).scalars().first()
            return workflow_version_to_domain(row) if row is not None else None

    def add(self, entity: WorkflowVersion) -> WorkflowVersion:
        """新增版本并返回。"""
        with session_scope(self._session_factory) as session:
            row = workflow_version_to_orm(entity)
            session.add(row)
            session.flush()
            return workflow_version_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[WorkflowVersion]:
        """按等值条件列出版本（``scope`` 叠加租户过滤；版本表无组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmWorkflowVersion)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmWorkflowVersion, field) == value)
            statement = apply_scope(statement, OrmWorkflowVersion, scope)
            rows = session.execute(statement).scalars().all()
            return [workflow_version_to_domain(row) for row in rows]

    def list_by_workflow(self, workflow_id: str) -> builtins.list[WorkflowVersion]:
        """列出某 Workflow 的全部版本（按 ``id`` 升序：UUIDv7 时间有序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmWorkflowVersion)
                .where(OrmWorkflowVersion.workflow_id == workflow_id)
                .order_by(OrmWorkflowVersion.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [workflow_version_to_domain(row) for row in rows]

    def update(self, entity: WorkflowVersion) -> WorkflowVersion:
        """更新版本并返回；已发布行的 ``definition`` 变更被拒。

        Raises:
            DomainError: 已 ``PUBLISHED`` 行的 ``definition`` 变更
                （``CONFLICT``，``reason="published_immutable"``）。
        """
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowVersion, entity.id)
            if row is None:
                return workflow_version_to_domain(workflow_version_to_orm(entity))
            if row.status == WORKFLOW_VERSION_STATUS_PUBLISHED:
                if dict(row.definition or {}) != dict(entity.definition or {}):
                    raise DomainError(
                        "已发布的 WorkflowVersion 不可变更 definition（可重建性 I-P2-06）",
                        code=ErrorCode.CONFLICT,
                        data={
                            "reason": "published_immutable",
                            "workflow_version_id": entity.id,
                        },
                    )
            row.definition = dict(entity.definition or {})
            row.status = entity.status
            session.flush()
            return workflow_version_to_domain(row)

    def delete(self, entity: WorkflowVersion) -> None:
        """删除版本。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowVersion, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlWorkflowRunRepository:
    """基于 SQLAlchemy 的 WorkflowRun 仓储（``workflow_run`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> WorkflowRun | None:
        """按主键获取运行，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowRun, entity_id)
            return workflow_run_to_domain(row) if row is not None else None

    def add(self, entity: WorkflowRun) -> WorkflowRun:
        """新增运行并返回。"""
        with session_scope(self._session_factory) as session:
            row = workflow_run_to_orm(entity)
            session.add(row)
            session.flush()
            return workflow_run_to_domain(row)

    def list(self, scope: ScopeFilter | None = None, **filters: Any) -> builtins.list[WorkflowRun]:
        """按等值条件列出运行（``scope`` 叠加租户 / 组织 / 工作区过滤）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmWorkflowRun)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmWorkflowRun, field) == value)
            statement = apply_scope(statement, OrmWorkflowRun, scope)
            rows = session.execute(statement).scalars().all()
            return [workflow_run_to_domain(row) for row in rows]

    def list_by_version(self, workflow_version_id: str) -> builtins.list[WorkflowRun]:
        """列出引用某版本的全部运行（按 ``id`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmWorkflowRun)
                .where(OrmWorkflowRun.workflow_version_id == workflow_version_id)
                .order_by(OrmWorkflowRun.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [workflow_run_to_domain(row) for row in rows]

    def list_by_tenant(self, tenant_id: str) -> builtins.list[WorkflowRun]:
        """列出某租户下的全部运行（按 ``id`` 升序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmWorkflowRun)
                .where(OrmWorkflowRun.tenant_id == tenant_id)
                .order_by(OrmWorkflowRun.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [workflow_run_to_domain(row) for row in rows]

    def list_by_status(self, tenant_id: str, status: str) -> builtins.list[WorkflowRun]:
        """列出某租户下处于指定状态的运行（活跃 Run 上限判定用）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmWorkflowRun)
                .where(OrmWorkflowRun.tenant_id == tenant_id, OrmWorkflowRun.status == status)
                .order_by(OrmWorkflowRun.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [workflow_run_to_domain(row) for row in rows]

    def update(self, entity: WorkflowRun) -> WorkflowRun:
        """更新运行并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowRun, entity.id)
            if row is None:
                return workflow_run_to_domain(workflow_run_to_orm(entity))
            row.status = entity.status
            row.task_id = entity.task_id
            row.input = dict(entity.input) if entity.input is not None else None
            row.output = dict(entity.output) if entity.output is not None else None
            row.started_at = entity.started_at
            row.completed_at = entity.completed_at
            row.error = entity.error
            session.flush()
            return workflow_run_to_domain(row)

    def delete(self, entity: WorkflowRun) -> None:
        """删除运行。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowRun, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()


class SqlWorkflowNodeRunRepository:
    """基于 SQLAlchemy 的 WorkflowNodeRun 仓储（``workflow_node_run`` 表）。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, entity_id: str) -> WorkflowNodeRun | None:
        """按主键获取节点记录，不存在返回 ``None``。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowNodeRun, entity_id)
            return workflow_node_run_to_domain(row) if row is not None else None

    def add(self, entity: WorkflowNodeRun) -> WorkflowNodeRun:
        """新增节点记录并返回。"""
        with session_scope(self._session_factory) as session:
            row = workflow_node_run_to_orm(entity)
            session.add(row)
            session.flush()
            return workflow_node_run_to_domain(row)

    def list(
        self, scope: ScopeFilter | None = None, **filters: Any
    ) -> builtins.list[WorkflowNodeRun]:
        """按等值条件列出节点记录（``scope`` 叠加租户过滤；节点记录表无组织 / 工作区列）。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmWorkflowNodeRun)
            for field, value in filters.items():
                statement = statement.where(getattr(OrmWorkflowNodeRun, field) == value)
            statement = apply_scope(statement, OrmWorkflowNodeRun, scope)
            rows = session.execute(statement).scalars().all()
            return [workflow_node_run_to_domain(row) for row in rows]

    def list_by_run(self, workflow_run_id: str) -> builtins.list[WorkflowNodeRun]:
        """列出某运行下的全部节点记录（按 ``id`` 升序 = 执行顺序）。"""
        with session_scope(self._session_factory) as session:
            statement = (
                select(OrmWorkflowNodeRun)
                .where(OrmWorkflowNodeRun.workflow_run_id == workflow_run_id)
                .order_by(OrmWorkflowNodeRun.id.asc())
            )
            rows = session.execute(statement).scalars().all()
            return [workflow_node_run_to_domain(row) for row in rows]

    def get_by_node(
        self, workflow_run_id: str, node_key: str, attempt: int = 1
    ) -> WorkflowNodeRun | None:
        """按 ``(workflow_run_id, node_key, attempt)`` 获取节点记录。"""
        with session_scope(self._session_factory) as session:
            statement = select(OrmWorkflowNodeRun).where(
                OrmWorkflowNodeRun.workflow_run_id == workflow_run_id,
                OrmWorkflowNodeRun.node_key == node_key,
                OrmWorkflowNodeRun.attempt == attempt,
            )
            row = session.execute(statement).scalars().first()
            return workflow_node_run_to_domain(row) if row is not None else None

    def update(self, entity: WorkflowNodeRun) -> WorkflowNodeRun:
        """更新节点记录并返回。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowNodeRun, entity.id)
            if row is None:
                return workflow_node_run_to_domain(workflow_node_run_to_orm(entity))
            row.status = entity.status
            row.attempt = entity.attempt
            row.agent_run_id = entity.agent_run_id
            row.tool_call_id = entity.tool_call_id
            row.approval_id = entity.approval_id
            row.input = dict(entity.input) if entity.input is not None else None
            row.output = dict(entity.output) if entity.output is not None else None
            row.started_at = entity.started_at
            row.completed_at = entity.completed_at
            session.flush()
            return workflow_node_run_to_domain(row)

    def delete(self, entity: WorkflowNodeRun) -> None:
        """删除节点记录。"""
        with session_scope(self._session_factory) as session:
            row = session.get(OrmWorkflowNodeRun, entity.id)
            if row is not None:
                session.delete(row)
                session.flush()
