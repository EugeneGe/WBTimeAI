"""``remote.agent_run`` 处理器（R2 / T2-58；R3 / T2-59 接 Lease；设计 §2.8.1 / §2.9.1）。

接线（仿 ``agent.run`` / ``workflow.run`` 范式）：``remote.agent_run`` 在**独立 Attempt
Sandbox** 内运行选定 Agent / Workflow 版本并保存结果引用（``result_commit`` /
``environment_digest`` / Diff / Artifact），由**组合根**装配后经
``HandlerContext.services`` 注入。

🔴 **R3 / T2-59 远程执行接线（C-6 单写者链后段）**：当组合根注入了 ``lease_manager``
   （:class:`astra_worker.recovery.LeaseManager`）时，处理器按**租约**执行：

   1. :meth:`LeaseManager.claim` **原子领取** ``(task_id, attempt)``；**重复投递**命中唯一约束
      → 返回 ``status="already_claimed"`` + ``skipped=True``（**非静默**，不重复执行）；
   2. 运行执行体后 :meth:`LeaseManager.heartbeat` 续租、:meth:`LeaseManager.finish` 落终态与
      结果引用（``result_commit`` / ``environment_digest`` / ``artifact_refs``）；
   3. 执行体抛错 → :meth:`LeaseManager.fail` 落 ``FAILED``（**非静默**）后**原样抛出**。

   未注入 ``lease_manager`` 时**退化为 T2-58 行为**（直接运行执行体，向后兼容）。

🔴 **Git 仅经 Sandbox**（C-4）：本处理器**不**启动宿主 Git Shell；供给 / 提交经注入的执行体
   （其内部再经 ``GitService`` → ``SandboxProvider``）。
🔴 执行体 / 队列**正交**（R-23）：本模块**不 import** 具体队列 / ORM / Runtime / 能力包实现；
   租约经 ``ctx.services`` 注入，**不**直连仓储。

消息线格式（与 ``make_message`` 一致）：:

    {"handler": "remote.agent_run",
     "payload": {"execution_id": ..., "task_id": ..., "attempt": ...,
                 "agent_version_id"|"workflow_version_id": ..., "base_ref": ...,
                 "checkout_ref": ..., "environment_digest": ..., "project_id": ...},
     "task_id": ...}
"""

from __future__ import annotations

from typing import Any

from astra_core import DomainError, ErrorCode, NotImplementedYetError

from astra_worker import HandlerContext

__all__ = ["HANDLER_KEY", "STATUS_ALREADY_CLAIMED", "handle_remote_agent_run"]

#: 处理器键（``task.type`` 为 ``String(100)`` → 取值 ``remote.agent_run`` **免迁移**）。
HANDLER_KEY = "remote.agent_run"

#: 重复投递（已由他者领取）时的返回状态（**非静默**：显式区分「跳过」与「已执行」）。
STATUS_ALREADY_CLAIMED = "already_claimed"


def handle_remote_agent_run(message: dict[str, Any], ctx: HandlerContext) -> dict[str, Any]:
    """处理 ``remote.agent_run``：领取租约 → 在独立 Attempt Sandbox 内运行版本并保存结果引用。

    Args:
        message: Worker 消息（``payload.execution_id`` 必填；接租约时 ``payload.task_id`` 亦必需）。
        ctx: 处理器上下文（``services["lease_manager"]`` / ``services["remote_agent_run"]``
            由组合根注入）。

    Returns:
        ``{"execution_id": ..., "status": ..., "result_commit": ...,
           "environment_digest": ...}``；重复投递时含 ``"skipped": True`` 且
        ``status="already_claimed"``。

    Raises:
        DomainError: 缺少 ``execution_id``（``VALIDATION_ERROR``）；接租约但缺 ``task_id``。
        NotImplementedYetError: 未注入 ``remote_agent_run`` 执行体（组合根未装配；**非静默**）。
    """
    payload = dict(message.get("payload") or {})
    execution_id = str(payload.get("execution_id") or message.get("execution_id") or "")
    if not execution_id:
        raise DomainError(
            "remote.agent_run 缺少 execution_id",
            code=ErrorCode.VALIDATION_ERROR,
            data={"handler": HANDLER_KEY},
        )

    # ① 租约领取（仅当组合根注入了 lease_manager；否则退化为 T2-58 行为）。
    lease_manager = ctx.services.get("lease_manager")
    record = None
    if lease_manager is not None:
        task_id = str(payload.get("task_id") or message.get("task_id") or "")
        if not task_id:
            raise DomainError(
                "remote.agent_run 接租约时缺少 task_id（原子 Claim 必需）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"handler": HANDLER_KEY, "execution_id": execution_id},
            )
        attempt = int(payload.get("attempt") or 1)
        worker_id = payload.get("worker_id") or message.get("worker_id")
        outcome = lease_manager.claim(
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            project_id=payload.get("project_id"),
            checkout_ref=payload.get("checkout_ref"),
            base_commit=payload.get("base_commit"),
            environment_digest=payload.get("environment_digest"),
        )
        if not outcome.claimed:
            # 重复投递（Redis 重投）→ 已领取 → 跳过（**非静默**；不重复执行、不产生并发 Attempt）。
            return {
                "execution_id": execution_id,
                "task_id": task_id,
                "status": STATUS_ALREADY_CLAIMED,
                "skipped": True,
            }
        record = outcome.record

    # ② 执行体（组合根注入；未注入 → 非静默失败）。
    runner = ctx.services.get("remote_agent_run")
    if runner is None:
        raise NotImplementedYetError(
            "remote.agent_run 需远程 Attempt 执行体（由组合根装配并经 "
            "ctx.services['remote_agent_run'] 注入）",
            data={"handler": HANDLER_KEY, "execution_id": execution_id},
        )

    # ③ 运行 + 续租 + 落终态。
    try:
        result = runner(payload)
    except Exception as exc:  # noqa: BLE001 - 落 FAILED 后原样抛出（非静默）
        if lease_manager is not None and record is not None:
            lease_manager.fail(record, error=f"{type(exc).__name__}: {exc}")
        raise

    status = str(_field(result, "status") or "")
    if lease_manager is not None and record is not None:
        # 执行记录以**执行成败**落终态（SUCCESS）；执行体的自带 ``status`` 仅作**返回值**
        # 透传给调用方（其词表不在 ``TaskStatus`` 内，不作执行记录状态）。
        lease_manager.heartbeat(record)
        lease_manager.finish(
            record,
            result_commit=_field(result, "result_commit"),
            environment_digest=_field(result, "environment_digest"),
            artifact_refs=_field(result, "artifact_refs"),
        )

    return {
        "execution_id": execution_id,
        "status": status,
        "result_commit": _field(result, "result_commit"),
        "environment_digest": _field(result, "environment_digest"),
    }


def _field(outcome: Any, name: str) -> Any:
    """从执行体返回物取字段（兼容 ``dict`` 与对象两种返回）。"""
    if isinstance(outcome, dict):
        return outcome.get(name)
    return getattr(outcome, name, None)
