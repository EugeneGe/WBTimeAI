"""``remote.agent_run`` 处理器（R2 / T2-58；设计 §2.8.1 / §2.9.1）。

接线（仿 ``agent.run`` / ``workflow.run`` 范式）：``remote.agent_run`` 在**独立 Attempt
Sandbox** 内运行选定 Agent / Workflow 版本并保存结果引用（``result_commit`` /
``environment_digest`` / Diff / Artifact），由**组合根**装配后经
``HandlerContext.services["remote_agent_run"]`` 注入；未注入时抛 ``NotImplementedYetError``
（**非静默**）。**远程执行的完整接线（Claim / Lease / 独立 Attempt 执行）归 T2-59**（C-6）。

🔴 **Git 仅经 Sandbox**（C-4）：本处理器**不**启动宿主 Git Shell；供给 / 提交经注入的执行体
   （其内部再经 ``GitService`` → ``SandboxProvider``）。
🔴 执行体 / 队列**正交**（R-23）：本模块**不 import** 具体队列 / ORM / Runtime / 能力包实现。

消息线格式（与 ``make_message`` 一致）：:

    {"handler": "remote.agent_run",
     "payload": {"execution_id": ..., "task_id": ..., "attempt": ...,
                 "agent_version_id"|"workflow_version_id": ..., "base_ref": ...,
                 "checkout_ref": ..., "environment_digest": ...},
     "task_id": ...}
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode, NotImplementedYetError

from astra_worker import HandlerContext

__all__ = ["HANDLER_KEY", "handle_remote_agent_run"]

#: 处理器键（``task.type`` 为 ``String(100)`` → 取值 ``remote.agent_run`` **免迁移**）。
HANDLER_KEY = "remote.agent_run"


def handle_remote_agent_run(message: dict[str, Any], ctx: HandlerContext) -> dict[str, Any]:
    """处理 ``remote.agent_run``：在独立 Attempt Sandbox 内运行选定版本并保存结果引用。

    Args:
        message: Worker 消息（``payload.execution_id`` 必填）。
        ctx: 处理器上下文（``services["remote_agent_run"]`` 由组合根注入执行体）。

    Returns:
        ``{"execution_id": ..., "status": ..., "result_commit": ...,
           "environment_digest": ...}``。

    Raises:
        DomainError: 缺少 ``execution_id``（``VALIDATION_ERROR``）。
        NotImplementedYetError: 未注入 ``remote_agent_run``（组合根未装配；**非静默**）。
    """
    payload = dict(message.get("payload") or {})
    execution_id = str(payload.get("execution_id") or message.get("execution_id") or "")
    if not execution_id:
        raise DomainError(
            "remote.agent_run 缺少 execution_id",
            code=ErrorCode.VALIDATION_ERROR,
            data={"handler": HANDLER_KEY},
        )

    runner = ctx.services.get("remote_agent_run")
    if runner is None:
        raise NotImplementedYetError(
            "remote.agent_run 需远程 Attempt 执行体（由组合根装配并经 "
            "ctx.services['remote_agent_run'] 注入）；完整接线归 T2-59。",
            data={"handler": HANDLER_KEY, "execution_id": execution_id},
        )

    outcome = runner(payload)
    return {
        "execution_id": execution_id,
        "status": str(_field(outcome, "status") or ""),
        "result_commit": _field(outcome, "result_commit"),
        "environment_digest": _field(outcome, "environment_digest"),
    }


def _field(outcome: Any, name: str) -> Any:
    """从执行体返回物取字段（兼容 ``dict`` 与对象两种返回）。"""
    if isinstance(outcome, dict):
        return outcome.get(name)
    return getattr(outcome, name, None)
