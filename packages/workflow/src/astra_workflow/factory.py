"""``astra_workflow`` 组合工厂（W4 裁定 R3 §3.1）。

- :func:`build_workflow_repositories`：由 ``session_factory`` 装配 Workflow 组四个 SQL 仓储
  （供**组合根**注入 ``WorkflowService``）；
- :func:`build_workflow_engine`：装配自研轻量编排引擎（T2-21 起）。

🔴 本模块为能力包**显式允许的 ORM 落点**（``test_layering.py`` 中的
   ``test_phase2_domain_submodules_have_no_orm_or_web`` 对 ``factory.py`` 放行）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from .domain import (
    WorkflowNodeRunRepository,
    WorkflowRepository,
    WorkflowRunRepository,
    WorkflowVersionRepository,
)
from .engine import (
    ConcurrencyGuard,
    NodeRunRecorder,
    RuntimeBridge,
    WorkflowEngine,
    WorkflowEventSink,
)
from .engine.timeout import DEFAULT_MAX_STEPS
from .nodes import NodeExecutor, NodeRegistry
from .repositories import (
    SqlWorkflowNodeRunRepository,
    SqlWorkflowRepository,
    SqlWorkflowRunRepository,
    SqlWorkflowVersionRepository,
)

__all__ = [
    "WorkflowRepositories",
    "build_workflow_repositories",
    "build_workflow_engine",
]


@dataclass
class WorkflowRepositories:
    """Workflow 组仓储集合（组合根持有一份，注入 Application 服务）。"""

    workflows: WorkflowRepository
    versions: WorkflowVersionRepository
    runs: WorkflowRunRepository
    node_runs: WorkflowNodeRunRepository


def build_workflow_repositories(
    session_factory: sessionmaker[Session],
) -> WorkflowRepositories:
    """装配 Workflow 组四个 SQL 仓储。

    Args:
        session_factory: SQLAlchemy 会话工厂（由组合根提供）。

    Returns:
        已装配的 :class:`WorkflowRepositories`。
    """
    return WorkflowRepositories(
        workflows=SqlWorkflowRepository(session_factory),
        versions=SqlWorkflowVersionRepository(session_factory),
        runs=SqlWorkflowRunRepository(session_factory),
        node_runs=SqlWorkflowNodeRunRepository(session_factory),
    )


def build_workflow_engine(
    executors: Mapping[str, NodeExecutor] | NodeRegistry,
    *,
    versions: WorkflowVersionRepository | None = None,
    recorder: NodeRunRecorder | None = None,
    sink: WorkflowEventSink | None = None,
    bridge: RuntimeBridge | None = None,
    concurrency: ConcurrencyGuard | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    run_timeout_ms: int | None = None,
) -> WorkflowEngine:
    """装配 :class:`WorkflowEngine`（供**组合根**注入 Application 服务）。

    Args:
        executors: ``node_type → NodeExecutor`` 映射或 :class:`NodeRegistry`。
        versions: 版本仓储（``resume`` 回读不可变快照用）。
        recorder: 节点记录持久化端口。
        sink: 领域事件出口。
        bridge: Runtime 桥接（**唯一** Runtime 耦合点，由 ``runtime_bridge`` 提供）。
        concurrency: 并发守卫（``PARALLEL`` 上限）。
        max_steps: 单次运行最大节点步数（有界）。
        run_timeout_ms: Run 级时间预算（``None`` = 不限）。

    Returns:
        已装配的 :class:`WorkflowEngine`。
    """
    registry = executors.as_mapping() if isinstance(executors, NodeRegistry) else dict(executors)
    return WorkflowEngine(
        registry,
        versions=versions,
        recorder=recorder,
        sink=sink,
        bridge=bridge,
        concurrency=concurrency,
        max_steps=max_steps,
        run_timeout_ms=run_timeout_ms,
    )
