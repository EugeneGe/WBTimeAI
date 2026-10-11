"""``astra_workflow`` 状态机（设计 §2.5；W4 裁定 R3 §3.2，**冻结**）。

- :class:`WorkflowRunStatus`：Run 六态
  ``PENDING|RUNNING|SUCCEEDED|FAILED|CANCELLED|WAITING_APPROVAL``；
  ``WAITING_APPROVAL`` 为**非终态**（审批挂起）；
- :class:`WorkflowNodeRunStatus`：节点级六态
  ``PENDING|RUNNING|SUCCEEDED|FAILED|SKIPPED|WAITING_APPROVAL``；
- :func:`can_transition` / :func:`assert_transition`：非法迁移抛
  ``DomainError(VALIDATION_ERROR)``（仿 ``astra_task.states``）。

```
PENDING ──start()──▶ RUNNING ──succeed(output)──▶ SUCCEEDED
   │                   │  ├──fail(error)────────▶ FAILED
   │                   │  ├──cancel()───────────▶ CANCELLED
   │                   │  └──wait_approval()────▶ WAITING_APPROVAL
   └──cancel()────────▶ CANCELLED                    │
                                          resume() ───┘──▶ RUNNING
```

🔴 本子模块**零 Web / ORM**（受 ``test_layering.py::
   test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖）。
"""

from __future__ import annotations

from enum import StrEnum

from astra_core import DomainError, ErrorCode

__all__ = [
    # 常量
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
    # 枚举
    "WorkflowRunStatus",
    "WorkflowNodeRunStatus",
    # 迁移表 / 判定
    "WORKFLOW_RUN_TRANSITIONS",
    "WORKFLOW_NODE_RUN_TRANSITIONS",
    "WORKFLOW_RUN_TERMINAL_STATUSES",
    "WORKFLOW_NODE_RUN_TERMINAL_STATUSES",
    "can_transition_workflow_run",
    "assert_workflow_run_transition",
    "can_transition_node_run",
    "assert_node_run_transition",
]


# -- 常量 -------------------------------------------------------------------

#: WorkflowRun 状态。
WORKFLOW_RUN_STATUS_PENDING = "PENDING"
WORKFLOW_RUN_STATUS_RUNNING = "RUNNING"
WORKFLOW_RUN_STATUS_SUCCEEDED = "SUCCEEDED"
WORKFLOW_RUN_STATUS_FAILED = "FAILED"
WORKFLOW_RUN_STATUS_CANCELLED = "CANCELLED"
WORKFLOW_RUN_STATUS_WAITING_APPROVAL = "WAITING_APPROVAL"

#: WorkflowNodeRun 状态。
WORKFLOW_NODE_RUN_STATUS_PENDING = "PENDING"
WORKFLOW_NODE_RUN_STATUS_RUNNING = "RUNNING"
WORKFLOW_NODE_RUN_STATUS_SUCCEEDED = "SUCCEEDED"
WORKFLOW_NODE_RUN_STATUS_FAILED = "FAILED"
WORKFLOW_NODE_RUN_STATUS_SKIPPED = "SKIPPED"
WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL = "WAITING_APPROVAL"


class WorkflowRunStatus(StrEnum):
    """WorkflowRun 状态（设计 §2.5，**冻结**）。"""

    PENDING = WORKFLOW_RUN_STATUS_PENDING
    RUNNING = WORKFLOW_RUN_STATUS_RUNNING
    SUCCEEDED = WORKFLOW_RUN_STATUS_SUCCEEDED
    FAILED = WORKFLOW_RUN_STATUS_FAILED
    CANCELLED = WORKFLOW_RUN_STATUS_CANCELLED
    WAITING_APPROVAL = WORKFLOW_RUN_STATUS_WAITING_APPROVAL

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


class WorkflowNodeRunStatus(StrEnum):
    """WorkflowNodeRun 状态（设计 §2.5，**冻结**）。"""

    PENDING = WORKFLOW_NODE_RUN_STATUS_PENDING
    RUNNING = WORKFLOW_NODE_RUN_STATUS_RUNNING
    SUCCEEDED = WORKFLOW_NODE_RUN_STATUS_SUCCEEDED
    FAILED = WORKFLOW_NODE_RUN_STATUS_FAILED
    SKIPPED = WORKFLOW_NODE_RUN_STATUS_SKIPPED
    WAITING_APPROVAL = WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)


#: WorkflowRun 合法状态迁移表（当前 → 允许的下一状态集合）。
WORKFLOW_RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    WORKFLOW_RUN_STATUS_PENDING: frozenset(
        {WORKFLOW_RUN_STATUS_RUNNING, WORKFLOW_RUN_STATUS_CANCELLED}
    ),
    WORKFLOW_RUN_STATUS_RUNNING: frozenset(
        {
            WORKFLOW_RUN_STATUS_SUCCEEDED,
            WORKFLOW_RUN_STATUS_FAILED,
            WORKFLOW_RUN_STATUS_CANCELLED,
            WORKFLOW_RUN_STATUS_WAITING_APPROVAL,
        }
    ),
    WORKFLOW_RUN_STATUS_WAITING_APPROVAL: frozenset(
        {
            WORKFLOW_RUN_STATUS_RUNNING,
            WORKFLOW_RUN_STATUS_FAILED,
            WORKFLOW_RUN_STATUS_CANCELLED,
        }
    ),
    WORKFLOW_RUN_STATUS_SUCCEEDED: frozenset(),
    WORKFLOW_RUN_STATUS_FAILED: frozenset(),
    WORKFLOW_RUN_STATUS_CANCELLED: frozenset(),
}

#: WorkflowNodeRun 合法状态迁移表。
WORKFLOW_NODE_RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    WORKFLOW_NODE_RUN_STATUS_PENDING: frozenset(
        {
            WORKFLOW_NODE_RUN_STATUS_RUNNING,
            WORKFLOW_NODE_RUN_STATUS_FAILED,
            WORKFLOW_NODE_RUN_STATUS_SKIPPED,
            WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
        }
    ),
    WORKFLOW_NODE_RUN_STATUS_RUNNING: frozenset(
        {
            WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
            WORKFLOW_NODE_RUN_STATUS_FAILED,
            WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL,
        }
    ),
    WORKFLOW_NODE_RUN_STATUS_WAITING_APPROVAL: frozenset(
        {
            WORKFLOW_NODE_RUN_STATUS_RUNNING,
            WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
            WORKFLOW_NODE_RUN_STATUS_FAILED,
            WORKFLOW_NODE_RUN_STATUS_SKIPPED,
        }
    ),
    WORKFLOW_NODE_RUN_STATUS_SUCCEEDED: frozenset(),
    WORKFLOW_NODE_RUN_STATUS_FAILED: frozenset(),
    WORKFLOW_NODE_RUN_STATUS_SKIPPED: frozenset(),
}

#: WorkflowRun 终态集合（不可再转移）。
WORKFLOW_RUN_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        WORKFLOW_RUN_STATUS_SUCCEEDED,
        WORKFLOW_RUN_STATUS_FAILED,
        WORKFLOW_RUN_STATUS_CANCELLED,
    }
)

#: WorkflowNodeRun 终态集合（不可再转移）。
WORKFLOW_NODE_RUN_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        WORKFLOW_NODE_RUN_STATUS_SUCCEEDED,
        WORKFLOW_NODE_RUN_STATUS_FAILED,
        WORKFLOW_NODE_RUN_STATUS_SKIPPED,
    }
)


def _normalize(status: str | StrEnum) -> str:
    """将枚举 / 字符串统一为字面值。"""
    return status.value if isinstance(status, StrEnum) else str(status)


def can_transition_workflow_run(
    current: str | WorkflowRunStatus, target: str | WorkflowRunStatus
) -> bool:
    """判断 WorkflowRun 的 ``current → target`` 是否合法。"""
    return _normalize(target) in WORKFLOW_RUN_TRANSITIONS.get(_normalize(current), frozenset())


def assert_workflow_run_transition(
    current: str | WorkflowRunStatus, target: str | WorkflowRunStatus
) -> None:
    """断言 WorkflowRun 状态迁移合法，否则抛 :class:`DomainError`。

    Raises:
        DomainError: 非法迁移（``VALIDATION_ERROR``）。
    """
    if not can_transition_workflow_run(current, target):
        raise DomainError(
            f"非法 WorkflowRun 状态迁移：{_normalize(current)} → {_normalize(target)}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"from": _normalize(current), "to": _normalize(target)},
        )


def can_transition_node_run(
    current: str | WorkflowNodeRunStatus, target: str | WorkflowNodeRunStatus
) -> bool:
    """判断 WorkflowNodeRun 的 ``current → target`` 是否合法。"""
    return _normalize(target) in WORKFLOW_NODE_RUN_TRANSITIONS.get(_normalize(current), frozenset())


def assert_node_run_transition(
    current: str | WorkflowNodeRunStatus, target: str | WorkflowNodeRunStatus
) -> None:
    """断言 WorkflowNodeRun 状态迁移合法，否则抛 :class:`DomainError`。

    Raises:
        DomainError: 非法迁移（``VALIDATION_ERROR``）。
    """
    if not can_transition_node_run(current, target):
        raise DomainError(
            f"非法 WorkflowNodeRun 状态迁移：{_normalize(current)} → {_normalize(target)}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"from": _normalize(current), "to": _normalize(target)},
        )
