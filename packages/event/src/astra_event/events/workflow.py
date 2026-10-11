"""Workflow 生命周期事件（Phase 2 · W3 / T2-16；设计 §2.11；裁定 §6.1）。

5 类事件，**继承** :class:`astra_core.events.DomainEvent`（事件基类唯一，C-02）：

- ``WorkflowStarted`` / ``WorkflowNodeStarted`` / ``WorkflowNodeCompleted`` /
  ``WorkflowCompleted`` / ``WorkflowFailed``。

类型字符串：

- ``workflow.started`` / ``workflow.node.started`` / ``workflow.node.completed`` /
  ``workflow.completed`` / ``workflow.failed``。

🔴 2a **先定义类型**，2b/2c 消费触发（Workflow 级回放 ``workflow_run`` / ``workflow_node_run``
   属 2b，2a 不建）；本模块**只定义事件类型**，``EventBus`` Protocol 保持不变（C-02）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from astra_core import DomainEvent

__all__ = [
    "WorkflowStarted",
    "WorkflowNodeStarted",
    "WorkflowNodeCompleted",
    "WorkflowCompleted",
    "WorkflowFailed",
]


@dataclass
class WorkflowStarted(DomainEvent):
    """Workflow 开始事件（``workflow.started``）。"""

    type: ClassVar[str] = "workflow.started"

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str,
        run_id: str,
        workflow_version_id: str | None = None,
    ) -> WorkflowStarted:
        """便捷构造。"""
        payload: dict[str, Any] = {"workflow_id": workflow_id, "run_id": run_id}
        if workflow_version_id is not None:
            payload["workflow_version_id"] = workflow_version_id
        return cls(payload=payload)


@dataclass
class WorkflowNodeStarted(DomainEvent):
    """Workflow 节点开始事件（``workflow.node.started``）。"""

    type: ClassVar[str] = "workflow.node.started"

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str,
        run_id: str,
        node_id: str,
        node_type: str | None = None,
    ) -> WorkflowNodeStarted:
        """便捷构造。"""
        payload: dict[str, Any] = {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "node_id": node_id,
        }
        if node_type is not None:
            payload["node_type"] = node_type
        return cls(payload=payload)


@dataclass
class WorkflowNodeCompleted(DomainEvent):
    """Workflow 节点完成事件（``workflow.node.completed``）。"""

    type: ClassVar[str] = "workflow.node.completed"

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str,
        run_id: str,
        node_id: str,
        status: str,
        duration_ms: int | None = None,
    ) -> WorkflowNodeCompleted:
        """便捷构造。"""
        payload: dict[str, Any] = {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "node_id": node_id,
            "status": status,
        }
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return cls(payload=payload)


@dataclass
class WorkflowCompleted(DomainEvent):
    """Workflow 成功结束事件（``workflow.completed``）。"""

    type: ClassVar[str] = "workflow.completed"

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str,
        run_id: str,
        duration_ms: int | None = None,
    ) -> WorkflowCompleted:
        """便捷构造。"""
        payload: dict[str, Any] = {"workflow_id": workflow_id, "run_id": run_id}
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return cls(payload=payload)


@dataclass
class WorkflowFailed(DomainEvent):
    """Workflow 失败结束事件（``workflow.failed``）。"""

    type: ClassVar[str] = "workflow.failed"

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str,
        run_id: str,
        error_type: str,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> WorkflowFailed:
        """便捷构造。"""
        payload: dict[str, Any] = {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "error_type": error_type,
        }
        if error is not None:
            payload["error"] = error
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return cls(payload=payload)
