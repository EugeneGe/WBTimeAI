"""``astra_workflow`` 领域实体（设计 §2.5；W4 裁定 R3 §3.1 / §3.2）。

- :class:`Workflow`：Workflow **身份与生命周期**（聚合根；``(tenant_id, name)`` 唯一）；
- :class:`WorkflowVersion`：**不可变**版本快照（``frozen=True``；``definition`` 为
  **完整图快照**，发布即冻结——可重建性 ``I-P2-06`` 的基石）；
- :class:`WorkflowNode` / :class:`WorkflowEdge`：版本内图元素（**不可变**快照，``frozen``）；
- :class:`WorkflowRun`：一次运行（**固定引用** ``workflow_version_id``，六态状态机）；
- :class:`WorkflowNodeRun`：节点级执行记录（重放 == golden 快照的数据源）。

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from astra_domain import AggregateRoot, Entity

from .state import (
    WORKFLOW_NODE_RUN_STATUS_PENDING,
    WORKFLOW_RUN_STATUS_PENDING,
    WorkflowNodeRunStatus,
    WorkflowRunStatus,
    assert_node_run_transition,
    assert_workflow_run_transition,
)

__all__ = [
    # 状态 / 类型常量
    "WORKFLOW_STATUS_DRAFT",
    "WORKFLOW_STATUS_ACTIVE",
    "WORKFLOW_STATUS_ARCHIVED",
    "WORKFLOW_VERSION_STATUS_DRAFT",
    "WORKFLOW_VERSION_STATUS_PUBLISHED",
    "WORKFLOW_VERSION_STATUS_DEPRECATED",
    "NODE_TYPE_AGENT",
    "NODE_TYPE_TOOL",
    "NODE_TYPE_MCP",
    "NODE_TYPE_CONDITION",
    "NODE_TYPE_PARALLEL",
    "NODE_TYPE_LOOP",
    "NODE_TYPE_HUMAN_APPROVAL",
    "NODE_TYPE_END",
    "WORKFLOW_TRIGGER_USER",
    "WORKFLOW_TRIGGER_SCHEDULE",
    "WORKFLOW_TRIGGER_EVENT",
    "WORKFLOW_TRIGGER_API",
    "DEFINITION_KEY_NODES",
    "DEFINITION_KEY_EDGES",
    "DEFINITION_KEY_ENTRY",
    "DEFAULT_ATTEMPT",
    "APPROVAL_EXPIRED_ERROR",
    # 枚举
    "WorkflowStatus",
    "WorkflowVersionStatus",
    "WorkflowNodeType",
    "WorkflowTrigger",
    # 实体
    "Workflow",
    "WorkflowVersion",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowRun",
    "WorkflowNodeRun",
    # 快照辅助
    "build_definition",
]


# -- 常量（ASTRA 风格字面值） ------------------------------------------------

#: Workflow 生命周期状态。
WORKFLOW_STATUS_DRAFT = "DRAFT"
WORKFLOW_STATUS_ACTIVE = "ACTIVE"
WORKFLOW_STATUS_ARCHIVED = "ARCHIVED"

#: WorkflowVersion 状态（单向：``DRAFT → PUBLISHED → DEPRECATED``）。
WORKFLOW_VERSION_STATUS_DRAFT = "DRAFT"
WORKFLOW_VERSION_STATUS_PUBLISHED = "PUBLISHED"
WORKFLOW_VERSION_STATUS_DEPRECATED = "DEPRECATED"

#: 8 类节点类型（设计 §2.5 / W4 裁定 §5 T2-22，**冻结**）。
NODE_TYPE_AGENT = "AGENT"
NODE_TYPE_TOOL = "TOOL"
NODE_TYPE_MCP = "MCP"
NODE_TYPE_CONDITION = "CONDITION"
NODE_TYPE_PARALLEL = "PARALLEL"
NODE_TYPE_LOOP = "LOOP"
NODE_TYPE_HUMAN_APPROVAL = "HUMAN_APPROVAL"
NODE_TYPE_END = "END"

#: WorkflowRun 触发来源（设计 §2.5）。
WORKFLOW_TRIGGER_USER = "user"
WORKFLOW_TRIGGER_SCHEDULE = "schedule"
WORKFLOW_TRIGGER_EVENT = "event"
WORKFLOW_TRIGGER_API = "api"

#: ``workflow_version.definition``（完整图快照）的约定键。
DEFINITION_KEY_NODES = "nodes"
DEFINITION_KEY_EDGES = "edges"
DEFINITION_KEY_ENTRY = "entry"

#: 节点执行记录的默认尝试序号。
DEFAULT_ATTEMPT = 1

#: 审批到期后 Run 的终态错误码字面值（W4 裁定 §9-c：``FAILED`` + ``APPROVAL_EXPIRED``）。
APPROVAL_EXPIRED_ERROR = "APPROVAL_EXPIRED"

#: 允许的版本状态迁移（单向）。
_ALLOWED_VERSION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    WORKFLOW_VERSION_STATUS_DRAFT: (
        WORKFLOW_VERSION_STATUS_PUBLISHED,
        WORKFLOW_VERSION_STATUS_DEPRECATED,
    ),
    WORKFLOW_VERSION_STATUS_PUBLISHED: (WORKFLOW_VERSION_STATUS_DEPRECATED,),
    WORKFLOW_VERSION_STATUS_DEPRECATED: (),
}


class WorkflowStatus(StrEnum):
    """Workflow 生命周期状态（设计 §2.5）。"""

    DRAFT = WORKFLOW_STATUS_DRAFT
    ACTIVE = WORKFLOW_STATUS_ACTIVE
    ARCHIVED = WORKFLOW_STATUS_ARCHIVED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class WorkflowVersionStatus(StrEnum):
    """WorkflowVersion 状态（单向：``DRAFT → PUBLISHED → DEPRECATED``）。"""

    DRAFT = WORKFLOW_VERSION_STATUS_DRAFT
    PUBLISHED = WORKFLOW_VERSION_STATUS_PUBLISHED
    DEPRECATED = WORKFLOW_VERSION_STATUS_DEPRECATED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class WorkflowNodeType(StrEnum):
    """8 类节点类型（设计 §2.5；**冻结**）。"""

    AGENT = NODE_TYPE_AGENT
    TOOL = NODE_TYPE_TOOL
    MCP = NODE_TYPE_MCP
    CONDITION = NODE_TYPE_CONDITION
    PARALLEL = NODE_TYPE_PARALLEL
    LOOP = NODE_TYPE_LOOP
    HUMAN_APPROVAL = NODE_TYPE_HUMAN_APPROVAL
    END = NODE_TYPE_END

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class WorkflowTrigger(StrEnum):
    """WorkflowRun 触发来源。"""

    USER = WORKFLOW_TRIGGER_USER
    SCHEDULE = WORKFLOW_TRIGGER_SCHEDULE
    EVENT = WORKFLOW_TRIGGER_EVENT
    API = WORKFLOW_TRIGGER_API

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


# -- 实体 -------------------------------------------------------------------


@dataclass
class Workflow(AggregateRoot):
    """Workflow 聚合根（流程定义的身份与生命周期）。

    Attributes:
        name: 租户内唯一的流程名。
        description: 描述。
        workspace_id: 归属工作空间（可空）。
        status: 生命周期状态（``WorkflowStatus`` 字面值）。
        current_version_id: 当前生效版本标识（可空）。
        created_by: 创建者用户标识。
    """

    name: str = ""
    description: str | None = None
    workspace_id: str | None = None
    status: str = WORKFLOW_STATUS_DRAFT
    current_version_id: str | None = None
    created_by: str = ""


def build_definition(
    nodes: list[WorkflowNode],
    edges: list[WorkflowEdge],
    *,
    entry: str | None = None,
) -> dict[str, Any]:
    """由节点 / 连边实体构造 ``workflow_version.definition`` **完整图快照**。

    Args:
        nodes: 版本内全部节点（按传入顺序序列化）。
        edges: 版本内全部连边。
        entry: 入口 ``node_key``；缺省取首个节点（无节点时为 ``None``）。

    Returns:
        形如 ``{"nodes": [...], "edges": [...], "entry": ...}`` 的快照字典。
    """
    resolved_entry = entry if entry is not None else (nodes[0].node_key if nodes else None)
    return {
        DEFINITION_KEY_NODES: [
            {
                "key": node.node_key,
                "type": node.type,
                "config": dict(node.config or {}),
                "position": dict(node.position or {}),
            }
            for node in nodes
        ],
        DEFINITION_KEY_EDGES: [
            {
                "from": edge.from_node_key,
                "to": edge.to_node_key,
                "condition": edge.condition,
            }
            for edge in edges
        ],
        DEFINITION_KEY_ENTRY: resolved_entry,
    }


@dataclass(frozen=True)
class WorkflowVersion:
    """WorkflowVersion（**不可变**版本快照；发布即冻结）。

    🔴 ``frozen=True``：``definition`` 构造后**不可变**。需变更时经
       :meth:`with_status`（单向迁移）产生**新实例**（``dataclasses.replace``）。
    """

    id: str = field(default_factory=generate_id)
    workflow_id: str = ""
    version: str = ""
    definition: dict[str, Any] = field(default_factory=dict)
    status: str = WORKFLOW_VERSION_STATUS_DRAFT
    created_by: str = ""
    created_at: datetime = field(default_factory=utcnow)

    @property
    def is_published(self) -> bool:
        """是否已发布（发布即冻结）。"""
        return self.status == WORKFLOW_VERSION_STATUS_PUBLISHED

    def definition_nodes(self) -> list[dict[str, Any]]:
        """返回快照中的节点列表（每项含 ``key`` / ``type`` / ``config`` / ``position``）。"""
        return [dict(item) for item in (self.definition.get(DEFINITION_KEY_NODES) or [])]

    def definition_edges(self) -> list[dict[str, Any]]:
        """返回快照中的连边列表（每项含 ``from`` / ``to`` / ``condition``）。"""
        return [dict(item) for item in (self.definition.get(DEFINITION_KEY_EDGES) or [])]

    def entry_node_key(self) -> str | None:
        """返回快照声明的入口 ``node_key``；未声明时取首个节点。"""
        entry = self.definition.get(DEFINITION_KEY_ENTRY)
        if entry:
            return str(entry)
        nodes = self.definition_nodes()
        return str(nodes[0]["key"]) if nodes else None

    def with_status(self, status: str | WorkflowVersionStatus) -> WorkflowVersion:
        """返回状态迁移后的**新**实例（单向迁移，非法迁移 → ``CONFLICT``）。

        Args:
            status: 目标状态（``WorkflowVersionStatus`` 字面值 / 枚举）。

        Returns:
            迁移后的新 :class:`WorkflowVersion`。

        Raises:
            DomainError: 非法状态迁移（``CONFLICT``）。
        """
        from astra_core import DomainError, ErrorCode

        target = status.value if isinstance(status, WorkflowVersionStatus) else str(status)
        allowed = _ALLOWED_VERSION_TRANSITIONS.get(self.status, ())
        if target not in allowed:
            raise DomainError(
                f"WorkflowVersion 状态迁移非法：{self.status} → {target}",
                code=ErrorCode.CONFLICT,
                data={"reason": "invalid_status_transition", "from": self.status, "to": target},
            )
        return replace(self, status=target)

    def publish(self) -> WorkflowVersion:
        """发布（``DRAFT`` → ``PUBLISHED``；发布即冻结）。"""
        return self.with_status(WORKFLOW_VERSION_STATUS_PUBLISHED)

    def deprecate(self) -> WorkflowVersion:
        """弃用（``DRAFT`` / ``PUBLISHED`` → ``DEPRECATED``）。"""
        return self.with_status(WORKFLOW_VERSION_STATUS_DEPRECATED)


@dataclass(frozen=True)
class WorkflowNode:
    """WorkflowNode（版本内节点；``node_key`` 版本内唯一）。"""

    id: str = field(default_factory=generate_id)
    workflow_version_id: str = ""
    node_key: str = ""
    type: str = NODE_TYPE_AGENT
    config: dict[str, Any] = field(default_factory=dict)
    position: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class WorkflowEdge:
    """WorkflowEdge（版本内有向连边；``(from, to)`` 版本内唯一）。"""

    id: str = field(default_factory=generate_id)
    workflow_version_id: str = ""
    from_node_key: str = ""
    to_node_key: str = ""
    condition: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class WorkflowRun(AggregateRoot):
    """WorkflowRun：一次运行（**固定引用**不可变 ``workflow_version_id``，可重建）。

    Attributes:
        workflow_version_id: 引用的版本标识（**恒定**；``I-P2-06``）。
        trigger: 触发来源（``user`` / ``schedule`` / ``event`` / ``api``）。
        status: 运行状态（``WorkflowRunStatus`` 字面值）。
        task_id: 异步路径挂靠的 ``task.id``（可空；``QUEUED`` 形态）。
        input: 运行入参。
        output: 运行产出（终态写入）。
        started_at: 开始时间。
        completed_at: 结束时间（终态写入）。
        error: 失败原因（``FAILED`` 时写入）。
    """

    workflow_version_id: str = ""
    trigger: str = WORKFLOW_TRIGGER_USER
    status: str = WORKFLOW_RUN_STATUS_PENDING
    task_id: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    # -- 状态机（冻结，见 domain/state.py） ---------------------------------

    def _transition(self, target: str | WorkflowRunStatus) -> None:
        """执行状态迁移（非法 → ``DomainError(VALIDATION_ERROR)``）。"""
        assert_workflow_run_transition(self.status, target)
        self.status = target.value if isinstance(target, WorkflowRunStatus) else str(target)

    def start(self) -> WorkflowRun:
        """``PENDING → RUNNING``（写入 ``started_at``）。"""
        self._transition(WorkflowRunStatus.RUNNING)
        self.started_at = self.started_at or utcnow()
        return self

    def succeed(self, output: dict[str, Any] | None = None) -> WorkflowRun:
        """``RUNNING → SUCCEEDED``（写入 ``output`` / ``completed_at``）。"""
        self._transition(WorkflowRunStatus.SUCCEEDED)
        self.output = dict(output) if output is not None else self.output
        self.completed_at = utcnow()
        return self

    def fail(self, error: str | None = None) -> WorkflowRun:
        """``RUNNING`` / ``WAITING_APPROVAL → FAILED``（写入 ``error`` / ``completed_at``）。"""
        self._transition(WorkflowRunStatus.FAILED)
        self.error = error if error is not None else self.error
        self.completed_at = utcnow()
        return self

    def cancel(self) -> WorkflowRun:
        """``PENDING`` / ``RUNNING`` / ``WAITING_APPROVAL → CANCELLED``。"""
        self._transition(WorkflowRunStatus.CANCELLED)
        self.completed_at = utcnow()
        return self

    def wait_approval(self) -> WorkflowRun:
        """``RUNNING → WAITING_APPROVAL``（**非终态**，审批挂起）。"""
        self._transition(WorkflowRunStatus.WAITING_APPROVAL)
        return self

    def resume(self) -> WorkflowRun:
        """``WAITING_APPROVAL → RUNNING``（审批通过后续跑）。"""
        self._transition(WorkflowRunStatus.RUNNING)
        self.error = None
        return self

    @property
    def is_terminal(self) -> bool:
        """是否处于终态（不可再转移）。"""
        return self.status in {
            WorkflowRunStatus.SUCCEEDED.value,
            WorkflowRunStatus.FAILED.value,
            WorkflowRunStatus.CANCELLED.value,
        }


@dataclass
class WorkflowNodeRun(Entity):
    """WorkflowNodeRun：节点级执行记录（重放 == golden 快照的数据源）。

    Attributes:
        workflow_run_id: 归属的 WorkflowRun 标识。
        node_key: 节点在版本内的唯一键。
        status: 节点状态（``WorkflowNodeRunStatus`` 字面值）。
        attempt: 尝试序号（``(workflow_run_id, node_key, attempt)`` 唯一）。
        agent_run_id: ``AGENT`` 节点产出的独立 ``agent_run`` 标识（可空）。
        tool_call_id: ``TOOL`` / ``MCP`` 节点产出的 ``tool_call`` 标识（可空）。
        approval_id: ``HUMAN_APPROVAL`` 节点挂起的 ``approval`` 标识（可空）。
        input: 节点入参（变量解析后）。
        output: 节点产出（以 ``node_key`` 命名空间注入）。
        started_at: 开始时间。
        completed_at: 结束时间。
    """

    workflow_run_id: str = ""
    node_key: str = ""
    status: str = WORKFLOW_NODE_RUN_STATUS_PENDING
    attempt: int = DEFAULT_ATTEMPT
    agent_run_id: str | None = None
    tool_call_id: str | None = None
    approval_id: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def _transition(self, target: str | WorkflowNodeRunStatus) -> None:
        """执行状态迁移（非法 → ``DomainError(VALIDATION_ERROR)``）。"""
        assert_node_run_transition(self.status, target)
        self.status = target.value if isinstance(target, WorkflowNodeRunStatus) else str(target)

    def start(self) -> WorkflowNodeRun:
        """``PENDING → RUNNING``（写入 ``started_at``）。"""
        self._transition(WorkflowNodeRunStatus.RUNNING)
        self.started_at = self.started_at or utcnow()
        return self

    def succeed(self, output: dict[str, Any] | None = None) -> WorkflowNodeRun:
        """``RUNNING`` / ``WAITING_APPROVAL → SUCCEEDED``。"""
        self._transition(WorkflowNodeRunStatus.SUCCEEDED)
        self.output = dict(output) if output is not None else self.output
        self.completed_at = utcnow()
        return self

    def fail(self, output: dict[str, Any] | None = None) -> WorkflowNodeRun:
        """``PENDING`` / ``RUNNING`` / ``WAITING_APPROVAL → FAILED``。"""
        self._transition(WorkflowNodeRunStatus.FAILED)
        self.output = dict(output) if output is not None else self.output
        self.completed_at = utcnow()
        return self

    def skip(self) -> WorkflowNodeRun:
        """``PENDING`` / ``WAITING_APPROVAL → SKIPPED``（分支未选中 / 审批拒绝）。"""
        self._transition(WorkflowNodeRunStatus.SKIPPED)
        self.completed_at = utcnow()
        return self

    def wait_approval(self, approval_id: str | None = None) -> WorkflowNodeRun:
        """``PENDING`` / ``RUNNING → WAITING_APPROVAL``（挂起等待人工决议）。"""
        self._transition(WorkflowNodeRunStatus.WAITING_APPROVAL)
        if approval_id is not None:
            self.approval_id = approval_id
        return self

    def restart(self) -> WorkflowNodeRun:
        """``WAITING_APPROVAL → RUNNING``（审批通过后续跑本节点）。"""
        self._transition(WorkflowNodeRunStatus.RUNNING)
        return self

    @property
    def is_terminal(self) -> bool:
        """是否处于终态（不可再转移）。"""
        return self.status in {
            WorkflowNodeRunStatus.SUCCEEDED.value,
            WorkflowNodeRunStatus.FAILED.value,
            WorkflowNodeRunStatus.SKIPPED.value,
        }
