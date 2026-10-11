"""``astra_workflow`` 执行引擎（**自研轻量编排**，核心不依赖 LangGraph）。

- :mod:`ports`：对外端口（``RuntimeBridge`` / ``ConcurrencyGuard`` / ``NodeRunRecorder`` /
  ``WorkflowEventSink``）——**零框架**，fake 可替换；
- :mod:`variables`：``node_key`` 命名空间变量上下文（**禁 ``eval``**）；
- :mod:`timeout`：超时预算 / 有界重试 / 指数退避；
- :mod:`scheduler`：拓扑调度 + :class:`WorkflowEngine`（T2-21）；
- :mod:`runtime_bridge`（T2-23）/ :mod:`concurrency`（T2-23）：**唯一** Runtime 耦合点与并发守卫。

🔴 ``engine/runtime_bridge.py`` 是**唯一** import ``astra_runtime`` / ``astra_tool`` 的模块
   （W4 裁定 WR-6）。
"""

from __future__ import annotations

from .ports import (
    BRIDGE_KEY_AGENT_RUN_ID,
    BRIDGE_KEY_TOOL_CALL_ID,
    ConcurrencyGuard,
    NodeRunRecorder,
    NullConcurrencyGuard,
    NullNodeRunRecorder,
    NullRuntimeBridge,
    NullWorkflowEventSink,
    RuntimeBridge,
    WorkflowEventSink,
    acquire_guard,
    split_bridge_result,
)
from .scheduler import NodeScheduler, WorkflowEngine, WorkflowGraph, build_graph
from .timeout import (
    DEFAULT_BACKOFF_BASE_MS,
    DEFAULT_BACKOFF_MAX_MS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_STEPS,
    RetryPolicy,
    TimeoutBudget,
    run_with_retry,
)
from .variables import INPUT_NAMESPACE, REF_PATTERN, VariableContext, resolve_reference

__all__ = [
    # -- 图 / 调度 / 引擎 ----------------------------------------------------
    "WorkflowGraph",
    "build_graph",
    "NodeScheduler",
    "WorkflowEngine",
    # -- 变量 ----------------------------------------------------------------
    "INPUT_NAMESPACE",
    "REF_PATTERN",
    "VariableContext",
    "resolve_reference",
    # -- 超时 / 重试 ---------------------------------------------------------
    "DEFAULT_MAX_STEPS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_BACKOFF_BASE_MS",
    "DEFAULT_BACKOFF_MAX_MS",
    "RetryPolicy",
    "TimeoutBudget",
    "run_with_retry",
    # -- 端口 ----------------------------------------------------------------
    "BRIDGE_KEY_AGENT_RUN_ID",
    "BRIDGE_KEY_TOOL_CALL_ID",
    "split_bridge_result",
    "RuntimeBridge",
    "NullRuntimeBridge",
    "ConcurrencyGuard",
    "NullConcurrencyGuard",
    "acquire_guard",
    "NodeRunRecorder",
    "NullNodeRunRecorder",
    "WorkflowEventSink",
    "NullWorkflowEventSink",
]
