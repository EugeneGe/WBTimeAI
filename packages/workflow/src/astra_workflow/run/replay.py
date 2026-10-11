"""``workflow_run`` 执行重放（W4 / T2-24；设计 §2.5；W4 裁定 §3.2 / §5 T2-24）。

**可重建（``I-P2-06``）不变量**：

- ``workflow_run.workflow_version_id`` **恒定**——固定引用**不可变**版本快照；
- ``workflow_version.definition`` 为**完整图快照**（节点 + 连边 + 入口）；
- 从 ``workflow_run`` + ``workflow_node_run``（+ 各 ``agent_run`` / ``tool_call`` /
  ``approval`` 关联记录）**可重放 == golden 快照**。

重放**只读**：不触发执行、不写库。供：

- ``GET /workflows/{id}/runs/{run_id}`` 的运行详情 / 审计视图；
- 回归测试断言「重放 == golden」（``tests/integration/workflow/test_workflow_replay.py``）。

🔴 关联记录（``agent_run`` / ``tool_call`` / ``approval``）经**注入的读取器**获取——
   本模块**不 import** ``astra_conversation`` / ``astra_security``（保分层，WR-6 同族）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode

from ..domain import (
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
    WorkflowNodeRun,
    WorkflowNodeRunRepository,
    WorkflowRun,
    WorkflowRunRepository,
    WorkflowVersionRepository,
)

__all__ = [
    "LINKED_KEY_AGENT_RUNS",
    "LINKED_KEY_TOOL_CALLS",
    "LINKED_KEY_APPROVALS",
    "LinkedRecordReader",
    "WorkflowNodeRunSnapshot",
    "WorkflowReplay",
    "ReplayService",
    "assert_replay_matches_golden",
]


#: ``linked`` 中 ``agent_run`` 关联记录的键。
LINKED_KEY_AGENT_RUNS = "agent_runs"
#: ``linked`` 中 ``tool_call`` 关联记录的键。
LINKED_KEY_TOOL_CALLS = "tool_calls"
#: ``linked`` 中 ``approval`` 关联记录的键。
LINKED_KEY_APPROVALS = "approvals"


@runtime_checkable
class LinkedRecordReader(Protocol):
    """关联记录读取器（``agent_run`` / ``tool_call`` / ``approval``）。

    由**组合根**注入具体实现（SQL 仓储）；缺省 ``None`` → 重放中对应关联为空，
    **不静默伪造**数据。
    """

    def get(self, record_id: str) -> Any | None:
        """按主键读取一条关联记录，不存在返回 ``None``。"""
        ...


@dataclass(frozen=True)
class WorkflowNodeRunSnapshot:
    """节点级执行记录快照（重放 == golden 的最小可断言单元）。

    Attributes:
        node_key: 节点在版本内的唯一键。
        status: 节点状态（``WorkflowNodeRunStatus`` 字面值）。
        attempt: 尝试序号。
        agent_run_id: ``AGENT`` 节点产出的独立 ``agent_run`` 标识（可空）。
        tool_call_id: ``TOOL`` / ``MCP`` 节点产出的 ``tool_call`` 标识（可空）。
        approval_id: ``HUMAN_APPROVAL`` 节点挂起的 ``approval`` 标识（可空）。
        input: 节点入参（变量解析后）。
        output: 节点产出（以 ``node_key`` 命名空间注入）。
    """

    node_key: str = ""
    status: str = ""
    attempt: int = 1
    agent_run_id: str | None = None
    tool_call_id: str | None = None
    approval_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_entity(cls, node_run: WorkflowNodeRun) -> WorkflowNodeRunSnapshot:
        """由节点执行记录实体构造快照。"""
        return cls(
            node_key=str(node_run.node_key or ""),
            status=str(node_run.status or ""),
            attempt=int(node_run.attempt or 1),
            agent_run_id=node_run.agent_run_id,
            tool_call_id=node_run.tool_call_id,
            approval_id=node_run.approval_id,
            input=dict(node_run.input or {}),
            output=dict(node_run.output or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典（供 golden 对比 / API 视图）。"""
        return {
            "node_key": self.node_key,
            "status": self.status,
            "attempt": self.attempt,
            "agent_run_id": self.agent_run_id,
            "tool_call_id": self.tool_call_id,
            "approval_id": self.approval_id,
            "input": dict(self.input),
            "output": dict(self.output),
        }


@dataclass(frozen=True)
class WorkflowReplay:
    """一次运行的**完整重放快照**（``I-P2-06``）。

    Attributes:
        run_id: 运行标识。
        workflow_id: 所属 Workflow 标识（经固定版本回读）。
        workflow_version_id: 固定引用的版本标识（**恒定**）。
        status: 运行终态 / 挂起态。
        trigger: 触发来源。
        input: 运行入参。
        output: 运行产出。
        error: 失败原因。
        nodes: 节点级记录快照（按执行顺序）。
        linked: 关联记录（``agent_runs`` / ``tool_calls`` / ``approvals``）。
        task_id: 异步路径挂靠的 task 标识（可空）。
        started_at: 开始时间（ISO-8601；可空）。
        completed_at: 结束时间（ISO-8601；可空）。
    """

    run_id: str = ""
    workflow_id: str = ""
    workflow_version_id: str = ""
    status: str = ""
    trigger: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    nodes: tuple[WorkflowNodeRunSnapshot, ...] = ()
    linked: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @property
    def suspended(self) -> bool:
        """是否处于审批挂起（**非终态**）。"""
        return self.status == WORKFLOW_RUN_STATUS_WAITING_APPROVAL

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化字典（供 golden 对比 / API 视图）。"""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version_id": self.workflow_version_id,
            "status": self.status,
            "trigger": self.trigger,
            "input": dict(self.input),
            "output": dict(self.output) if self.output is not None else None,
            "error": self.error,
            "nodes": [node.to_dict() for node in self.nodes],
            "linked": dict(self.linked),
            "task_id": self.task_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


def _iso(value: Any) -> str | None:
    """把 ``datetime`` 归一化为 ISO-8601 字符串（``None`` 直通）。"""
    if value is None:
        return None
    return value.isoformat()


class ReplayService:
    """运行重放服务（**只读**；``workflow_run`` + ``workflow_node_run`` + 关联记录）。

    重放结果（:class:`WorkflowReplay`）应**逐字段等于** golden 快照——这是
    ``I-P2-06``（可重建）的可断言形式。

    Args:
        runs: 运行记录仓储。
        node_runs: 节点级执行记录仓储。
        versions: 版本仓储（回读 ``workflow_id`` 与不可变快照；可空）。
        agent_run_reader: ``agent_run`` 关联记录读取器（可空）。
        tool_call_reader: ``tool_call`` 关联记录读取器（可空）。
        approval_reader: ``approval`` 关联记录读取器（可空）。
    """

    def __init__(
        self,
        runs: WorkflowRunRepository,
        node_runs: WorkflowNodeRunRepository,
        *,
        versions: WorkflowVersionRepository | None = None,
        agent_run_reader: LinkedRecordReader | None = None,
        tool_call_reader: LinkedRecordReader | None = None,
        approval_reader: LinkedRecordReader | None = None,
    ) -> None:
        """装配重放服务（全部依赖由**组合根**注入）。"""
        self._runs = runs
        self._node_runs = node_runs
        self._versions = versions
        self._agent_run_reader = agent_run_reader
        self._tool_call_reader = tool_call_reader
        self._approval_reader = approval_reader

    def replay(self, run_id: str) -> WorkflowReplay:
        """重放一次运行，返回**完整快照**。

        Args:
            run_id: 目标运行标识。

        Returns:
            :class:`WorkflowReplay`。

        Raises:
            DomainError: 运行不存在（``NOT_FOUND``）。
        """
        run = self._runs.get(run_id)
        if run is None:
            raise DomainError(
                f"WorkflowRun 不存在，无法重放：{run_id}",
                code=ErrorCode.NOT_FOUND,
                data={"reason": "workflow_run_not_found", "workflow_run_id": run_id},
            )
        return self.build_replay(run)

    def build_replay(self, run: WorkflowRun) -> WorkflowReplay:
        """由运行实体构造重放快照（供 Application 复用，避免二次读库）。

        Args:
            run: 运行实体。

        Returns:
            :class:`WorkflowReplay`。
        """
        node_runs: list[WorkflowNodeRun] = list(self._node_runs.list_by_run(run.id))
        snapshots = tuple(WorkflowNodeRunSnapshot.from_entity(item) for item in node_runs)
        return WorkflowReplay(
            run_id=str(run.id or ""),
            workflow_id=self._resolve_workflow_id(run),
            workflow_version_id=str(run.workflow_version_id or ""),
            status=str(run.status or ""),
            trigger=str(run.trigger or ""),
            input=dict(run.input or {}),
            output=dict(run.output) if run.output is not None else None,
            error=run.error,
            nodes=snapshots,
            linked=self._collect_linked(node_runs),
            task_id=run.task_id,
            started_at=_iso(run.started_at),
            completed_at=_iso(run.completed_at),
        )

    # -- 内部 ---------------------------------------------------------------

    def _resolve_workflow_id(self, run: WorkflowRun) -> str:
        """经**固定引用**的版本回读 ``workflow_id``（不可得 → 空串，**不伪造**）。"""
        if self._versions is None:
            return ""
        version = self._versions.get(str(run.workflow_version_id or ""))
        if version is None:
            return ""
        return str(getattr(version, "workflow_id", "") or "")

    def _collect_linked(self, node_runs: list[WorkflowNodeRun]) -> dict[str, Any]:
        """收集各节点的关联记录（``agent_run`` / ``tool_call`` / ``approval``）。

        读取器未注入时对应键为空字典——**不静默伪造**关联内容。
        """
        agent_runs: dict[str, Any] = {}
        tool_calls: dict[str, Any] = {}
        approvals: dict[str, Any] = {}
        for node_run in node_runs:
            self._collect_one(node_run.agent_run_id, self._agent_run_reader, agent_runs)
            self._collect_one(node_run.tool_call_id, self._tool_call_reader, tool_calls)
            self._collect_one(node_run.approval_id, self._approval_reader, approvals)
        return {
            LINKED_KEY_AGENT_RUNS: agent_runs,
            LINKED_KEY_TOOL_CALLS: tool_calls,
            LINKED_KEY_APPROVALS: approvals,
        }

    @staticmethod
    def _collect_one(
        record_id: str | None,
        reader: LinkedRecordReader | None,
        sink: dict[str, Any],
    ) -> None:
        """读取单条关联记录并写入 ``sink``（``id`` 为空 / 读取器缺失 → 跳过）。"""
        if not record_id or reader is None:
            return
        record = reader.get(str(record_id))
        if record is None:
            return
        sink[str(record_id)] = _serialize(record)


def _serialize(record: Any) -> Any:
    """归一化关联记录为可 JSON 序列化结构。

    归一化顺序：``Mapping`` 直通 → ``to_dict()`` → ``asdict``（dataclass）
    → 兜底 ``id`` / ``status`` 摘要（**不伪造**字段）。
    """
    if isinstance(record, Mapping):
        return dict(record)
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return {
        "id": str(getattr(record, "id", "") or ""),
        "status": str(getattr(record, "status", "") or ""),
    }


def assert_replay_matches_golden(
    replay: WorkflowReplay,
    golden: Mapping[str, Any],
    *,
    context: str = "workflow_run",
) -> WorkflowReplay:
    """断言「重放 == golden 快照」（``I-P2-06`` 可重建性闸门）。

    Args:
        replay: 待断言的重放快照。
        golden: golden 快照（``to_dict()`` 产物的同构结构）。
        context: 断言上下文（用于错误信息定位）。

    Returns:
        原样返回 ``replay``（便于链式使用）。

    Raises:
        DomainError: 任一字段不等（``VALIDATION_ERROR``），``data.diff`` 列出差异。
    """
    actual = replay.to_dict()
    diff = _diff_mapping(actual, dict(golden))
    if diff:
        raise DomainError(
            f"{context} 重放与 golden 快照不一致（{len(diff)} 处差异）",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "replay_mismatch", "context": context, "diff": diff},
        )
    return replay


def _diff_mapping(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> list[dict[str, Any]]:
    """对比两个映射，返回差异列表（路径 / 期望 / 实际）。"""
    diff: list[dict[str, Any]] = []
    for key in sorted(set(actual) | set(expected)):
        left = actual.get(key)
        right = expected.get(key)
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            diff.extend(
                {
                    "path": f"{key}.{item['path']}",
                    "expected": item["expected"],
                    "actual": item["actual"],
                }
                for item in _diff_mapping(left, right)
            )
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                diff.append(
                    {
                        "path": str(key),
                        "expected": f"len={len(right)}",
                        "actual": f"len={len(left)}",
                    }
                )
                continue
            for index, (item_left, item_right) in enumerate(zip(left, right, strict=False)):
                if item_left != item_right:
                    diff.append(
                        {
                            "path": f"{key}[{index}]",
                            "expected": item_right,
                            "actual": item_left,
                        }
                    )
        elif left != right:
            diff.append({"path": str(key), "expected": right, "actual": left})
    return diff
