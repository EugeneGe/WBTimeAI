"""Astra AI Workflow 能力包（``astra_workflow``；设计 §2.5）。

- 领域实体 / 状态机 / 仓储接口：``astra_workflow.domain``（``Workflow`` /
  ``WorkflowVersion`` / ``WorkflowNode`` / ``WorkflowEdge`` / ``WorkflowRun`` /
  ``WorkflowNodeRun``；**零 Web / ORM**）；
- SQL 仓储：``astra_workflow.repositories``（能力包 ORM 落点）；
- 执行引擎 / 8 类节点 / 运行形态：``engine`` / ``nodes`` / ``run``（**T2-21 起**）；
- 组合工厂：``factory``（``build_workflow_repositories`` / ``build_workflow_engine``）。

包性质：**能力包**（仅禁 Web；SQL 仓储留本包 ``repositories/``）——W4 裁定 R3/R6。
"""

from __future__ import annotations

from .domain import (
    APPROVAL_EXPIRED_ERROR,
    DEFAULT_ATTEMPT,
    DEFINITION_KEY_EDGES,
    DEFINITION_KEY_ENTRY,
    DEFINITION_KEY_NODES,
    NODE_TYPE_AGENT,
    NODE_TYPE_CONDITION,
    NODE_TYPE_END,
    NODE_TYPE_HUMAN_APPROVAL,
    NODE_TYPE_LOOP,
    NODE_TYPE_MCP,
    NODE_TYPE_PARALLEL,
    NODE_TYPE_TOOL,
    WORKFLOW_NODE_RUN_STATUS_FAILED,
    WORKFLOW_NODE_RUN_STATUS_PENDING,
    WORKFLOW_NODE_RUN_STATUS_RUNNING,
    WORKFLOW_NODE_RUN_STATUS_SKIPPED,
    WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
    WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_NODE_RUN_TERMINAL_STATUSES,
    WORKFLOW_NODE_RUN_TRANSITIONS,
    WORKFLOW_RUN_STATUS_CANCELLED,
    WORKFLOW_RUN_STATUS_FAILED,
    WORKFLOW_RUN_STATUS_PENDING,
    WORKFLOW_RUN_STATUS_RUNNING,
    WORKFLOW_RUN_STATUS_SUCCEEDED,
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
    WORKFLOW_RUN_TERMINAL_STATUSES,
    WORKFLOW_RUN_TRANSITIONS,
    WORKFLOW_STATUS_ACTIVE,
    WORKFLOW_STATUS_ARCHIVED,
    WORKFLOW_STATUS_DRAFT,
    WORKFLOW_TRIGGER_API,
    WORKFLOW_TRIGGER_EVENT,
    WORKFLOW_TRIGGER_SCHEDULE,
    WORKFLOW_TRIGGER_USER,
    WORKFLOW_VERSION_STATUS_DEPRECATED,
    WORKFLOW_VERSION_STATUS_DRAFT,
    WORKFLOW_VERSION_STATUS_PUBLISHED,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowNodeRunRepository,
    WorkflowNodeRunStatus,
    WorkflowNodeType,
    WorkflowRepository,
    WorkflowRun,
    WorkflowRunRepository,
    WorkflowRunStatus,
    WorkflowStatus,
    WorkflowTrigger,
    WorkflowVersion,
    WorkflowVersionRepository,
    WorkflowVersionStatus,
    assert_node_run_transition,
    assert_workflow_run_transition,
    build_definition,
    can_transition_node_run,
    can_transition_workflow_run,
)
from .factory import WorkflowRepositories, build_workflow_repositories
from .repositories import (
    SqlWorkflowNodeRunRepository,
    SqlWorkflowRepository,
    SqlWorkflowRunRepository,
    SqlWorkflowVersionRepository,
)

__all__ = [
    # -- 常量：Workflow / Version 状态 ---------------------------------------
    "WORKFLOW_STATUS_DRAFT",
    "WORKFLOW_STATUS_ACTIVE",
    "WORKFLOW_STATUS_ARCHIVED",
    "WORKFLOW_VERSION_STATUS_DRAFT",
    "WORKFLOW_VERSION_STATUS_PUBLISHED",
    "WORKFLOW_VERSION_STATUS_DEPRECATED",
    # -- 常量：节点类型（8 类） ----------------------------------------------
    "NODE_TYPE_AGENT",
    "NODE_TYPE_TOOL",
    "NODE_TYPE_MCP",
    "NODE_TYPE_CONDITION",
    "NODE_TYPE_PARALLEL",
    "NODE_TYPE_LOOP",
    "NODE_TYPE_HUMAN_APPROVAL",
    "NODE_TYPE_END",
    # -- 常量：触发来源 ------------------------------------------------------
    "WORKFLOW_TRIGGER_USER",
    "WORKFLOW_TRIGGER_SCHEDULE",
    "WORKFLOW_TRIGGER_EVENT",
    "WORKFLOW_TRIGGER_API",
    # -- 常量：Run / NodeRun 状态 --------------------------------------------
    "WORKFLOW_RUN_STATUS_PENDING",
    "WORKFLOW_RUN_STATUS_RUNNING",
    "WORKFLOW_RUN_STATUS_SUCCEEDED",
    "WORKFLOW_RUN_STATUS_FAILED",
    "WORKFLOW_RUN_STATUS_CANCELLED",
    "WORKFLOW_RUN_STATUS_WAITING_APPROVAL",
    "WORKFLOW_NODE_RUN_STATUS_PENDING",
    "WORKFLOW_NODE_RUN_STATUS_RUNNING",
    "WORKFLOW_NODE_RUN_STATUS_SUCCEEDED",
    "WORKFLOW_NODE_RUN_STATUS_FAILED",
    "WORKFLOW_NODE_RUN_STATUS_SKIPPED",
    "WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL",
    # -- 常量：其它 ----------------------------------------------------------
    "DEFINITION_KEY_NODES",
    "DEFINITION_KEY_EDGES",
    "DEFINITION_KEY_ENTRY",
    "DEFAULT_ATTEMPT",
    "APPROVAL_EXPIRED_ERROR",
    # -- 枚举 ----------------------------------------------------------------
    "WorkflowStatus",
    "WorkflowVersionStatus",
    "WorkflowNodeType",
    "WorkflowTrigger",
    "WorkflowRunStatus",
    "WorkflowNodeRunStatus",
    # -- 状态机 --------------------------------------------------------------
    "WORKFLOW_RUN_TRANSITIONS",
    "WORKFLOW_NODE_RUN_TRANSITIONS",
    "WORKFLOW_RUN_TERMINAL_STATUSES",
    "WORKFLOW_NODE_RUN_TERMINAL_STATUSES",
    "can_transition_workflow_run",
    "assert_workflow_run_transition",
    "can_transition_node_run",
    "assert_node_run_transition",
    # -- 实体 ----------------------------------------------------------------
    "Workflow",
    "WorkflowVersion",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowRun",
    "WorkflowNodeRun",
    "build_definition",
    # -- 仓储接口 ------------------------------------------------------------
    "WorkflowRepository",
    "WorkflowVersionRepository",
    "WorkflowRunRepository",
    "WorkflowNodeRunRepository",
    # -- SQL 仓储 ------------------------------------------------------------
    "SqlWorkflowRepository",
    "SqlWorkflowVersionRepository",
    "SqlWorkflowRunRepository",
    "SqlWorkflowNodeRunRepository",
    # -- 装配 ----------------------------------------------------------------
    "WorkflowRepositories",
    "build_workflow_repositories",
]
