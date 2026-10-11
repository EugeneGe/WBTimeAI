"""``workflow.run`` 处理器（W1 / T2-02 接线；**实现归 W4 / T2-24**）。

接线：``workflow.run`` → Application ``WorkflowService.execute``（经
``ctx.services["workflow_run_executor"]`` 注入，同 ``agent.run`` 的
``execute_agent`` 范式，F17）。

🔴 **执行体与队列正交**（R-23 / F6）：本模块**只**负责「消息 → 执行回调」，
队列实现（``InProcessTaskQueue`` / ``RedisTaskQueue``）由 ``build_providers``
**唯一分流点**装配；本模块**不 import 任何具体队列 / ORM / Runtime**——
重活经 Application 层完成（Router / Worker 均不直调 ORM / Runtime，F8/WR-8）。

消息线格式（与 ``make_message`` / ``WorkerProcessExecutor.submit`` 一致）：:

    {"handler": "workflow.run", "payload": {"workflow_run_id": ...}, "task_id": ...}
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode, NotImplementedYetError

from astra_worker import HandlerContext

__all__ = ["HANDLER_KEY", "handle_workflow_run"]

#: 处理器键（``task.type`` ＝ ``String(100)`` → 取值 ``workflow.run`` **免迁移**，F18）。
HANDLER_KEY = "workflow.run"


def handle_workflow_run(message: dict[str, Any], ctx: HandlerContext) -> dict[str, Any]:
    """处理 ``workflow.run``：经 Application ``WorkflowService.execute`` 执行一次运行。

    Args:
        message: Worker 消息（``payload.workflow_run_id`` 必填）。
        ctx: 处理器上下文（``services["workflow_run_executor"]`` 由组合根注入）。

    Returns:
        ``{"run_id": ..., "status": ..., "task_id": ...}``。

    Raises:
        DomainError: 缺少 ``workflow_run_id``（``VALIDATION_ERROR``）。
        NotImplementedYetError: 未注入 ``workflow_run_executor``（组合根未装配；
            **非静默**，避免「入队即成功」假象）。
    """
    payload = dict(message.get("payload") or {})
    run_id = str(payload.get("workflow_run_id") or message.get("workflow_run_id") or "")
    if not run_id:
        raise DomainError(
            "workflow.run 缺少 workflow_run_id",
            code=ErrorCode.VALIDATION_ERROR,
            data={"handler": HANDLER_KEY},
        )

    executor = ctx.services.get("workflow_run_executor")
    if executor is None:
        raise NotImplementedYetError(
            "workflow.run 需 WorkflowService.execute（由组合根装配并经 "
            "ctx.services['workflow_run_executor'] 注入）",
            data={"handler": HANDLER_KEY, "workflow_run_id": run_id},
        )

    result = executor(run_id)
    return {
        "run_id": run_id,
        "status": str(getattr(result, "status", "") or ""),
        "task_id": getattr(result, "task_id", None),
    }
