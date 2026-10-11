"""``knowledge.index`` 处理器（W5 / T2-31；设计 §2.6 / §2.9）。

接线（仿 ``agent.run`` F14）：``knowledge.index`` → :class:`~astra_knowledge.KnowledgeIndexTask`
（``run(document_id) -> DocumentStatus``），由**组合根**装配后经
``HandlerContext.services["knowledge_index"]`` 注入；未注入时抛 ``NotImplementedYetError``。

重试计数（B9）：落 ``task.payload["attempt"]``——每次进入 **+1** 并**回写 message**，
供 ``TaskQueue`` 重试语义承接（``task_execution`` 表归 T2-37 / ``C2-23``）。

🔴 执行体 / 队列**正交**（R-23）：大文件解析在本处理器内（Worker /
   ``InProcessBackgroundExecutor``）执行，**不阻塞 API**（I-P2-21）。
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode, NotImplementedYetError

from astra_worker import HandlerContext

__all__ = ["HANDLER_KEY", "handle_knowledge_index"]

#: 处理器键。
HANDLER_KEY = "knowledge.index"


def handle_knowledge_index(message: dict[str, Any], ctx: HandlerContext) -> dict[str, Any]:
    """处理 ``knowledge.index``：经注入的索引任务驱动 ``document`` 状态机。

    Args:
        message: Worker 消息（``payload.document_id`` 必填；``payload.attempt`` 重试计数）。
        ctx: 处理器上下文（``services["knowledge_index"]`` 可注入索引任务 ``run`` 回调）。

    Returns:
        ``{"document_id": ..., "status": ..., "attempt": ...}``。

    Raises:
        DomainError: 缺少 ``document_id``（``VALIDATION_ERROR``）。
        NotImplementedYetError: 未注入 ``knowledge_index``（组合根装配归后续接线）。
    """
    payload = dict(message.get("payload") or {})
    document_id = str(payload.get("document_id") or message.get("document_id") or "")
    if not document_id:
        raise DomainError(
            "knowledge.index 缺少 document_id",
            code=ErrorCode.VALIDATION_ERROR,
            data={"handler": HANDLER_KEY},
        )

    runner = ctx.services.get("knowledge_index")
    if runner is None:
        raise NotImplementedYetError(
            "knowledge.index 需 KnowledgeIndexTask（由组合根装配并经 "
            "ctx.services['knowledge_index'] 注入）。",
            data={"handler": HANDLER_KEY, "document_id": document_id},
        )

    # 重试计数（B9）：进入即 +1，并回写 message 供 TaskQueue 重试语义承接。
    attempt = int(payload.get("attempt") or 0) + 1
    payload["attempt"] = attempt
    message["payload"] = payload

    result = runner(document_id)
    return {
        "document_id": document_id,
        "status": str(getattr(result, "value", result)),
        "attempt": attempt,
    }
