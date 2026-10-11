"""``project.clone`` 处理器（R2 / T2-58；设计 §2.8.1）。

接线（仿 ``workflow.run`` 范式）：``project.clone`` → Application ``ProjectService.clone``
（**同步沙箱克隆**路径），由**组合根**装配后经 ``HandlerContext.services["project_service"]``
注入；未注入时抛 ``NotImplementedYetError``（**非静默**，避免「入队即成功」假象）。

🔴 **Git 仅经 Sandbox**（C-4）：本处理器**不**启动宿主 Git Shell——克隆一律经注入的
   ``ProjectService``（其内部再经 ``GitService`` → ``SandboxProvider``）。
🔴 执行体 / 队列**正交**（R-23）：本模块**不 import** 具体队列 / ORM / Runtime。

消息线格式（与 ``make_message`` 一致）：:

    {"handler": "project.clone",
     "payload": {"project_id": ..., "tenant_id": ..., "base_ref": ...},
     "task_id": ...}
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode, NotImplementedYetError

from astra_worker import HandlerContext

__all__ = ["HANDLER_KEY", "handle_project_clone"]

#: 处理器键（``task.type`` 为 ``String(100)`` → 取值 ``project.clone`` **免迁移**）。
HANDLER_KEY = "project.clone"


def handle_project_clone(message: dict[str, Any], ctx: HandlerContext) -> dict[str, Any]:
    """处理 ``project.clone``：经 Application ``ProjectService.clone`` 克隆项目仓库。

    Args:
        message: Worker 消息（``payload.project_id`` / ``payload.tenant_id`` 必填）。
        ctx: 处理器上下文（``services["project_service"]`` 由组合根注入）。

    Returns:
        ``{"project_id": ..., "task_id": ..., "cloned": ...}``。

    Raises:
        DomainError: 缺少 ``project_id`` / ``tenant_id``（``VALIDATION_ERROR``）。
        NotImplementedYetError: 未注入 ``project_service``（组合根未装配；**非静默**）。
    """
    payload = dict(message.get("payload") or {})
    project_id = str(payload.get("project_id") or message.get("project_id") or "")
    tenant_id = str(payload.get("tenant_id") or message.get("tenant_id") or "")
    if not project_id or not tenant_id:
        raise DomainError(
            "project.clone 缺少 project_id / tenant_id",
            code=ErrorCode.VALIDATION_ERROR,
            data={"handler": HANDLER_KEY},
        )

    service = ctx.services.get("project_service")
    if service is None:
        raise NotImplementedYetError(
            "project.clone 需 ProjectService（由组合根装配并经 "
            "ctx.services['project_service'] 注入）",
            data={"handler": HANDLER_KEY, "project_id": project_id},
        )

    base_ref = payload.get("base_ref")
    outcome = service.clone(tenant_id=tenant_id, project_id=project_id, base_ref=base_ref)
    result = getattr(outcome, "result", None)
    return {
        "project_id": project_id,
        "task_id": getattr(outcome, "task_id", None),
        "cloned": result is None or bool(getattr(result, "ok", False)),
    }
