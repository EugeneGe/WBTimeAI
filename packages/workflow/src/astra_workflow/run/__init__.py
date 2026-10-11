"""``astra_workflow.run``——运行形态 / 可重建（W4 / T2-24；设计 §2.5 / §2.9 / §2.16）。

两种**执行体**（与队列**正交**，R-23）：

- :mod:`inline`：``INLINE`` —— **同步**驱动引擎至终态 / 挂起，产出 SSE 流所需的
  四个执行侧回调（``execute`` / ``list_events`` / ``cancel`` / ``run_status``）；
- :mod:`queued`：``QUEUED`` —— 预建 ``task(PENDING, type=workflow.run)`` 并入队，
  Worker 侧出队后同步执行（``ctx.services["workflow_run_executor"]`` 范式，F17）。

**可重建（``I-P2-06``）**：:mod:`replay` 由 ``workflow_run`` + ``workflow_node_run``
（+ 各 ``agent_run`` / ``tool_call`` / ``approval``）构造重放快照，断言
**重放 == golden**。

🔴 **SSE 不在本包**（能力包禁 Web）：流核心 ``apps/api/src/astra_api/sse/stream.py``
由**组合根**用 :class:`StreamDeps` 复用；``encoder.py`` 不改，``workflow.*`` /
``approval.*`` 通道已随 T2-16 冻结（F14 / R9）。
"""

from __future__ import annotations

from .inline import (
    DEFAULT_ERROR_TYPE,
    EXECUTION_MODE_INLINE,
    EventBusWorkflowEventSink,
    InlineRunner,
    RepositoryNodeRunRecorder,
)
from .queued import (
    EXECUTION_MODE_QUEUED,
    WORKFLOW_TASK_TYPE,
    QueuedRunner,
    TaskLike,
    TaskQueueLike,
    TaskRepositoryLike,
)
from .replay import (
    LINKED_KEY_AGENT_RUNS,
    LINKED_KEY_APPROVALS,
    LINKED_KEY_TOOL_CALLS,
    LinkedRecordReader,
    ReplayService,
    WorkflowNodeRunSnapshot,
    WorkflowReplay,
    assert_replay_matches_golden,
)

__all__ = [
    # -- 运行形态常量 ---------------------------------------------------------
    "EXECUTION_MODE_INLINE",
    "EXECUTION_MODE_QUEUED",
    "WORKFLOW_TASK_TYPE",
    # -- INLINE ---------------------------------------------------------------
    "InlineRunner",
    "RepositoryNodeRunRecorder",
    "EventBusWorkflowEventSink",
    "DEFAULT_ERROR_TYPE",
    # -- QUEUED ---------------------------------------------------------------
    "QueuedRunner",
    "TaskLike",
    "TaskRepositoryLike",
    "TaskQueueLike",
    # -- 可重建（I-P2-06） --------------------------------------------------
    "ReplayService",
    "WorkflowReplay",
    "WorkflowNodeRunSnapshot",
    "LinkedRecordReader",
    "LINKED_KEY_AGENT_RUNS",
    "LINKED_KEY_TOOL_CALLS",
    "LINKED_KEY_APPROVALS",
    "assert_replay_matches_golden",
]
