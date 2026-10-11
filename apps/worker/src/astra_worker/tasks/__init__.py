"""Worker 任务处理器（W1 / T2-02；设计 §2.9 / §2.16）。

注册三类任务处理器（**只做接线**，重型逻辑归后续波次）：

- ``agent.run`` → Application ``ExecuteAgent``（``tasks/agent_run.py``）；
- ``workflow.run`` → Workflow 引擎（**接线占位**，实现归 **T2-24**）；
- ``knowledge.index`` → Knowledge 索引（**接线占位**，实现归 **T2-31**）。

🔴 ``HANDLERS`` 为处理器注册表（``handler_key → Callable[[message, ctx], dict]``）；
   ``main.run_worker`` 依此 dispatch（``dequeue → dispatch → ack``）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from astra_worker import HandlerContext

from .agent_run import HANDLER_KEY as AGENT_RUN_KEY
from .agent_run import handle_agent_run
from .knowledge_index import HANDLER_KEY as KNOWLEDGE_INDEX_KEY
from .knowledge_index import handle_knowledge_index
from .maintenance_cleanup import HANDLER_KEY as MAINTENANCE_CLEANUP_KEY
from .maintenance_cleanup import handle_maintenance_cleanup
from .workflow_run import HANDLER_KEY as WORKFLOW_RUN_KEY
from .workflow_run import handle_workflow_run

__all__ = [
    "Handler",
    "HANDLERS",
    "make_message",
    "AGENT_RUN_KEY",
    "WORKFLOW_RUN_KEY",
    "KNOWLEDGE_INDEX_KEY",
    "MAINTENANCE_CLEANUP_KEY",
]

#: 处理器签名：``(message, ctx) -> result dict``。
Handler = Callable[[dict[str, Any], HandlerContext], dict[str, Any]]

#: 处理器注册表（``handler_key → Handler``）。
HANDLERS: dict[str, Handler] = {
    AGENT_RUN_KEY: handle_agent_run,
    WORKFLOW_RUN_KEY: handle_workflow_run,
    KNOWLEDGE_INDEX_KEY: handle_knowledge_index,
    MAINTENANCE_CLEANUP_KEY: handle_maintenance_cleanup,
}


def make_message(
    handler: str, payload: dict[str, Any] | None = None, **meta: Any
) -> dict[str, Any]:
    """构造一条 Worker 消息（与 ``WorkerProcessExecutor.submit`` 的线格式一致）。

    Args:
        handler: 处理器键（如 ``agent.run``）。
        payload: 载荷。
        **meta: 附加元信息（如 ``task_id`` / ``tenant_id`` / ``workspace_id``）。

    Returns:
        ``{"handler": handler, "payload": payload, **meta}``。
    """
    return {"handler": handler, "payload": dict(payload or {}), **meta}
