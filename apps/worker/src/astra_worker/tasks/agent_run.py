"""``agent.run`` 处理器（W1 / T2-02；设计 §2.9）。

接线：``agent.run`` → Application ``ExecuteAgent``（:class:`ExecuteAgentCommand` /
:class:`ExecuteAgentHandler`）。

🔴 W1 **仅接线**：``AgentRunService`` 需多依赖 DI（Runtime 等），由**组合根**装配后经
   ``HandlerContext.services["execute_agent"]`` 注入；未注入时抛
   ``NotImplementedYetError``（**非静默**），完整装配归运行波次。
"""

from __future__ import annotations

from typing import Any

from astra_application import ExecuteAgentCommand
from astra_core import DomainError, ErrorCode, NotImplementedYetError

from astra_worker import HandlerContext

__all__ = ["HANDLER_KEY", "handle_agent_run"]

#: 处理器键。
HANDLER_KEY = "agent.run"


def handle_agent_run(message: dict[str, Any], ctx: HandlerContext) -> dict[str, Any]:
    """处理 ``agent.run``：经 Application ``ExecuteAgent`` 执行一次 Run。

    Args:
        message: Worker 消息（``payload.run_id`` 必填）。
        ctx: 处理器上下文（``services["execute_agent"]`` 可注入用例处理器）。

    Returns:
        ``{"run_id": ..., "status": ...}``。

    Raises:
        DomainError: 缺少 ``run_id``（``VALIDATION_ERROR``）。
        NotImplementedYetError: 未注入 ``execute_agent``（运行时装配归后续波次）。
    """
    payload = dict(message.get("payload") or {})
    run_id = str(payload.get("run_id") or message.get("run_id") or "")
    if not run_id:
        raise DomainError(
            "agent.run 缺少 run_id",
            code=ErrorCode.VALIDATION_ERROR,
            data={"handler": HANDLER_KEY},
        )

    executor = ctx.services.get("execute_agent")
    if executor is None:
        raise NotImplementedYetError(
            "agent.run 需 AgentRunService（由组合根装配并经 ctx.services['execute_agent'] 注入）；"
            "W1 仅接线，运行时装配归后续波次。",
            data={"handler": HANDLER_KEY, "run_id": run_id},
        )

    result = executor(ExecuteAgentCommand(run_id=run_id))
    return {"run_id": run_id, "status": str(getattr(result, "status", ""))}
