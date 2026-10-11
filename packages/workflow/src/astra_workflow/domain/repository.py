"""``astra_workflow`` 仓储接口（**仅 Protocol**，零 ORM；设计 §2.5 / W4 裁定 R3）。

- :class:`WorkflowRepository`：Workflow 聚合（``(tenant_id, name)`` 唯一）；
- :class:`WorkflowVersionRepository`：**不可变**版本快照（``(workflow_id, version)`` 唯一）；
- :class:`WorkflowRunRepository`：运行记录（**固定引用**版本，可重建）；
- :class:`WorkflowNodeRunRepository`：节点级执行记录（重放数据源）。

SQLAlchemy 实现落本包 ``repositories/``（能力包显式允许的 ORM 落点）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import Repository

from .entities import Workflow, WorkflowNodeRun, WorkflowRun, WorkflowVersion

__all__ = [
    "WorkflowRepository",
    "WorkflowVersionRepository",
    "WorkflowRunRepository",
    "WorkflowNodeRunRepository",
]


@runtime_checkable
class WorkflowRepository(Repository[Workflow], Protocol):
    """Workflow 仓储接口（多租户隔离；``(tenant_id, name)`` 唯一）。"""

    def get_by_name(self, tenant_id: str, name: str) -> Workflow | None:
        """按 ``(tenant_id, name)`` 获取 Workflow，不存在返回 ``None``。"""
        ...

    def list_by_tenant(self, tenant_id: str) -> list[Workflow]:
        """列出某租户下的全部 Workflow。"""
        ...


@runtime_checkable
class WorkflowVersionRepository(Repository[WorkflowVersion], Protocol):
    """WorkflowVersion 仓储接口（不可变版本快照；``(workflow_id, version)`` 唯一）。"""

    def list_by_workflow(self, workflow_id: str) -> list[WorkflowVersion]:
        """列出某 Workflow 的全部版本（按创建顺序）。"""
        ...

    def get_by_version(self, workflow_id: str, version: str) -> WorkflowVersion | None:
        """按 ``(workflow_id, version)`` 获取版本，不存在返回 ``None``。"""
        ...


@runtime_checkable
class WorkflowRunRepository(Repository[WorkflowRun], Protocol):
    """WorkflowRun 仓储接口（固定引用版本，可重建 ``I-P2-06``）。"""

    def list_by_version(self, workflow_version_id: str) -> list[WorkflowRun]:
        """列出引用某版本的全部运行。"""
        ...

    def list_by_tenant(self, tenant_id: str) -> list[WorkflowRun]:
        """列出某租户下的全部运行。"""
        ...

    def list_by_status(self, tenant_id: str, status: str) -> list[WorkflowRun]:
        """列出某租户下处于指定状态的运行（活跃 Run 上限判定用）。"""
        ...


@runtime_checkable
class WorkflowNodeRunRepository(Repository[WorkflowNodeRun], Protocol):
    """WorkflowNodeRun 仓储接口（节点级执行记录）。"""

    def list_by_run(self, workflow_run_id: str) -> list[WorkflowNodeRun]:
        """列出某运行下的全部节点记录（按执行顺序）。"""
        ...

    def get_by_node(
        self, workflow_run_id: str, node_key: str, attempt: int = 1
    ) -> WorkflowNodeRun | None:
        """按 ``(workflow_run_id, node_key, attempt)`` 获取节点记录。"""
        ...
