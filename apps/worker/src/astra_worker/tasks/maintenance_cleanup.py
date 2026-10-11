"""``maintenance.cleanup`` 处理器（W9 / T2-48；设计 §2.19 / 裁定 §2.4）。

接线（仿 ``knowledge.index``，F8）：``maintenance.cleanup`` → **组合根**装配的
:class:`~astra_database.maintenance.cleanup.RetentionCleaner`（或等价 ``run()`` 回调），
经 ``HandlerContext.services["retention_cleanup"]`` 注入；未注入时抛
:class:`~astra_core.NotImplementedYetError`（**不静默**）。

🔴 本处理器**只做接线**：策略解析 / SQL 清理 / VACUUM 尾巴均由注入实现承担
（``astra_database.maintenance``）。重试计数落 ``task.payload["attempt"]``，
供 ``TaskQueue`` 重试语义承接。
"""

from __future__ import annotations

from typing import Any

from astra_core import NotImplementedYetError
from astra_task.maintenance.cleanup import RETENTION_TASK_TYPE

from astra_worker import HandlerContext

__all__ = ["HANDLER_KEY", "handle_maintenance_cleanup"]

#: 处理器键（＝任务类型 ``maintenance.cleanup``）。
HANDLER_KEY = RETENTION_TASK_TYPE


def handle_maintenance_cleanup(message: dict[str, Any], ctx: HandlerContext) -> dict[str, Any]:
    """处理 ``maintenance.cleanup``：经注入的保留清理器执行一轮分批清理。

    Args:
        message: Worker 消息（``payload.attempt`` 为重试计数；``payload.vacuum`` 可选开关）。
        ctx: 处理器上下文（``services["retention_cleanup"]`` ＝ ``RetentionCleaner`` 或
            可调用 ``run()`` 的实现）。

    Returns:
        ``{"task": "maintenance.cleanup", "attempt": ..., "report": {…}}``。

    Raises:
        NotImplementedYetError: 未注入 ``retention_cleanup``（组合根装配归后续接线）。
    """
    payload = dict(message.get("payload") or {})

    runner = ctx.services.get("retention_cleanup")
    if runner is None:
        raise NotImplementedYetError(
            "maintenance.cleanup 需 RetentionCleaner（由组合根装配并经 "
            "ctx.services['retention_cleanup'] 注入）。",
            data={"handler": HANDLER_KEY},
        )

    # 重试计数（B9）：进入即 +1，并回写 message 供 TaskQueue 重试语义承接。
    attempt = int(payload.get("attempt") or 0) + 1
    payload["attempt"] = attempt
    message["payload"] = payload

    result = runner.run() if hasattr(runner, "run") else runner()
    report = result.as_dict() if hasattr(result, "as_dict") else dict(result)
    return {"task": HANDLER_KEY, "attempt": attempt, "report": report}
