"""Astra AI 任务基座（``astra_task``）。

- ``states``：``TaskStatus`` 状态机
- ``models``：``Task`` 领域模型
- ``queue``：``TaskQueue`` Protocol + ``InProcessTaskQueue``（+ ``RedisTaskQueue``，Team）
- ``executor``：``BackgroundExecutor`` Protocol + ``InProcessBackgroundExecutor`` +
  ``WorkerProcessExecutor``（W1 / T2-02）
- ``scheduler``：``Scheduler`` Protocol + ``LocalScheduler``
- ``placeholder``：server 占位
- ``factory``：``create_inprocess_task_queue`` / ``create_local_scheduler``

⚠️ task 基座**不依赖 ``astra_database``**（任务落库推迟 W3+）。
🔴 ``RedisTaskQueue`` 的 ``arq`` / ``redis`` 为**函数级延迟导入**（模块级不 import），
   社区零新运行时依赖（W1 裁定 §3.6）。
"""

from __future__ import annotations

from .agents import (
    AGENT_TYPE_TO_TRIGGER,
    EVENT_AGENT,
    SCHEDULED_AGENT,
    UNLOCKED_AGENT_TYPES,
    ScheduledAgentUnlocker,
)
from .execution_record import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_LEASE_SECONDS,
    EXECUTION_STATUS_WORKER_INTERRUPTED,
    ExecutionRecorder,
    TaskExecutionRecord,
)
from .executor import (
    BackgroundExecutor,
    InProcessBackgroundExecutor,
    WorkerProcessExecutor,
)
from .factory import create_inprocess_task_queue, create_local_scheduler
from .maintenance import (
    AUDIT_LOG_TABLE,
    RETENTION_TARGET_TABLES,
    RETENTION_TASK_TYPE,
    RetentionPolicy,
)
from .models import Task
from .placeholder import (
    UnsupportedBackgroundExecutor,
    UnsupportedScheduler,
    UnsupportedTaskQueue,
)
from .queue import InProcessTaskQueue, TaskQueue
from .queue.redis import RedisTaskQueue, redis_available
from .scheduler import LocalScheduler, Scheduler
from .scheduler.idempotency import IdempotencyKey, idempotency_key
from .scheduler.runner import SchedulerTick
from .scheduler.triggers import (
    TARGET_TYPE_AGENT,
    TARGET_TYPE_WORKFLOW,
    TARGET_TYPES,
    TRIGGER_CRON,
    TRIGGER_EVENT,
    TRIGGER_MANUAL,
    TRIGGER_WEBHOOK,
    TRIGGERS,
    CronTrigger,
    EventTrigger,
    ManualTrigger,
    ScheduleSpec,
    Trigger,
    WebhookTrigger,
    resolve_trigger,
)
from .states import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    TaskStatus,
    assert_transition,
    can_transition,
)

__all__ = [
    "TaskStatus",
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATUSES",
    "can_transition",
    "assert_transition",
    "Task",
    "TaskQueue",
    "InProcessTaskQueue",
    "RedisTaskQueue",
    "redis_available",
    "BackgroundExecutor",
    "InProcessBackgroundExecutor",
    "WorkerProcessExecutor",
    "Scheduler",
    "LocalScheduler",
    "UnsupportedTaskQueue",
    "UnsupportedScheduler",
    "UnsupportedBackgroundExecutor",
    "create_inprocess_task_queue",
    "create_local_scheduler",
    # -- W7 / T2-39：调度增强（触发 / 幂等 / 记录 / 解锁） ---------------------
    "ScheduleSpec",
    "Trigger",
    "CronTrigger",
    "EventTrigger",
    "WebhookTrigger",
    "ManualTrigger",
    "resolve_trigger",
    "TRIGGER_CRON",
    "TRIGGER_EVENT",
    "TRIGGER_WEBHOOK",
    "TRIGGER_MANUAL",
    "TRIGGERS",
    "TARGET_TYPE_AGENT",
    "TARGET_TYPE_WORKFLOW",
    "TARGET_TYPES",
    "IdempotencyKey",
    "idempotency_key",
    "SchedulerTick",
    "TaskExecutionRecord",
    "ExecutionRecorder",
    # -- R3 / T2-59：Claim / heartbeat / lease / interrupted（执行态常量） --------
    "EXECUTION_STATUS_WORKER_INTERRUPTED",
    "DEFAULT_HEARTBEAT_SECONDS",
    "DEFAULT_LEASE_SECONDS",
    "SCHEDULED_AGENT",
    "EVENT_AGENT",
    "AGENT_TYPE_TO_TRIGGER",
    "UNLOCKED_AGENT_TYPES",
    "ScheduledAgentUnlocker",
    # -- W9 / T2-48：数据保留与清理（纯 VO + 任务类型常量；零 ORM） -------------
    "RETENTION_TASK_TYPE",
    "RETENTION_TARGET_TABLES",
    "AUDIT_LOG_TABLE",
    "RetentionPolicy",
]
