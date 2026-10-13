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

🔴 **R5 补全轮执行期限额（F8b / F8c；N10）**：在**运行执行体之前**追加两个**强制点**：

   - **F8b 并发受限**：:meth:`LeaseManager.claim` 返回 ``claimed=False`` 且
     ``reason="concurrency_limited"``（活跃执行数达 ``max_concurrent_executions``）→ 返回
     ``status="concurrency_limited"`` + ``skipped=True``（**非静默**，不运行执行体）；
   - **F8c deadline 快速失败**：``payload.deadline_at``（ISO8601，提交面写入）已过期 →
     **不运行**执行体，经 :meth:`LeaseManager.fail` 落稳定失败终态，返回
     ``status="deadline_exceeded"`` + ``skipped=True``（**非静默**）。

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

import logging
from datetime import UTC, datetime
from typing import Any

from astra_common.time import ensure_utc, utcnow
from astra_core import DomainError, ErrorCode, NotImplementedYetError

from astra_worker import HandlerContext
from astra_worker.recovery import REASON_CONCURRENCY_LIMITED

__all__ = [
    "HANDLER_KEY",
    "STATUS_ALREADY_CLAIMED",
    "STATUS_CONCURRENCY_LIMITED",
    "STATUS_DEADLINE_EXCEEDED",
    "STATUS_STANDBY",
    "STATUS_WORKER_INTERRUPTED",
    "STATUS_RESOURCE_LIMIT_EXCEEDED",
    "ExecutionInterrupted",
    "handle_remote_agent_run",
]

_logger = logging.getLogger("astra_worker.tasks.remote_agent_run")

#: 处理器键（``task.type`` 为 ``String(100)`` → 取值 ``remote.agent_run`` **免迁移**）。
HANDLER_KEY = "remote.agent_run"

#: 重复投递（已由他者领取）时的返回状态（**非静默**：显式区分「跳过」与「已执行」）。
STATUS_ALREADY_CLAIMED = "already_claimed"

#: 并发受限（活跃执行数达上限）时的返回状态（R5 补全轮 F8b；**非静默**）。
STATUS_CONCURRENCY_LIMITED = "concurrency_limited"

#: deadline 已过期（运行前快速失败）时的返回状态（R5 补全轮 F8c；**非静默**）。
STATUS_DEADLINE_EXCEEDED = "deadline_exceeded"

#: 并发受限后**自动留守 + 已择机重派**时的返回状态（A-1；**非静默**：本回合未运行）。
STATUS_STANDBY = "standby"

#: 执行中**强制打断**（超时长 / 显式中断）后的返回状态（A-2；**不**伪装成功）。
STATUS_WORKER_INTERRUPTED = "WORKER_INTERRUPTED"

#: workspace 磁盘占用**超限终止**时的返回状态（A-3；**非静默**）。
STATUS_RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"


class ExecutionInterrupted(Exception):
    """执行体**强制打断**信号（A-2）。

    执行体（组合根注入的 runner）在**运行中**检测到强制打断（自身超时 / 收到取消）时**抛**本
    异常；处理器据此以 ``WORKER_INTERRUPTED`` / ``CANCELLED`` 收尾（**不**伪装成功），
    **不**落 ``FAILED``。

    Attributes:
        reason: 中断原因（``deadline_exceeded`` = 超时长；``cancelled`` = 显式取消；其它自定义）。
    """

    def __init__(self, reason: str = "interrupted") -> None:
        """构造。

        Args:
            reason: 中断原因标识（缺省 ``interrupted``）。
        """
        super().__init__(reason)
        self.reason = reason


def handle_remote_agent_run(message: dict[str, Any], ctx: HandlerContext) -> dict[str, Any]:
    """处理 ``remote.agent_run``：领取租约 → 在独立 Attempt Sandbox 内运行版本并保存结果引用。

    Args:
        message: Worker 消息（``payload.execution_id`` 必填；接租约时 ``payload.task_id`` 亦必需）。
        ctx: 处理器上下文（``services["lease_manager"]`` / ``services["remote_agent_run"]``
            由组合根注入）。

    Returns:
        ``{"execution_id": ..., "status": ..., "result_commit": ...,
           "environment_digest": ...}``；**未运行**执行体时含 ``"skipped": True`` 且 ``status`` 为
        稳定非静默状态：``already_claimed``（重复投递）/ ``concurrency_limited``（并发受限 F8b）/
        ``deadline_exceeded``（deadline 过期 F8c）。

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
            # 未领取（**非静默**，不重复执行、不产生并发 Attempt）：
            #   - 重复投递（Redis 重投）→ 已领取 → 跳过（``already_claimed``，非静默）；
            #   - 并发受限（R5 补全轮 F8b / A-1）→ 自动留守 + 有界择机重派
            #     （``_standby_response``）。
            if outcome.reason == REASON_CONCURRENCY_LIMITED:
                return _standby_response(message, payload, execution_id, task_id, ctx)
            return {
                "execution_id": execution_id,
                "task_id": task_id,
                "status": outcome.reason,
                "skipped": True,
            }
        record = outcome.record

    # ②b 执行中强制打断（A-2）：运行**前**若已收到显式中断 / 取消信号 → **不运行**执行体，
    #     以 ``WORKER_INTERRUPTED`` / ``CANCELLED`` 收尾（**不**伪装成功）。
    interrupt_reason = _interrupt_reason(ctx, payload)
    if interrupt_reason is not None:
        if lease_manager is not None and record is not None:
            _finalize_interrupt(lease_manager, record, interrupt_reason)
        return {
            "execution_id": execution_id,
            "task_id": payload.get("task_id") or message.get("task_id"),
            "status": _interrupt_status(interrupt_reason),
            "skipped": True,
            "interrupted": True,
        }

    # ②c deadline 快速失败（R5 补全轮 F8c；在**运行执行体之前**）：
    #     ``payload.deadline_at``（ISO8601，由提交面写入）已过期 → **不运行**执行体，
    #     经租约落**稳定失败终态**（``deadline_exceeded``，**非静默**）。
    if _deadline_exceeded(payload):
        if lease_manager is not None and record is not None:
            lease_manager.fail(record, error=STATUS_DEADLINE_EXCEEDED)
        return {
            "execution_id": execution_id,
            "task_id": payload.get("task_id") or message.get("task_id"),
            "status": STATUS_DEADLINE_EXCEEDED,
            "skipped": True,
        }

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
    except ExecutionInterrupted as exc:
        # A-2：执行体在**运行中**检测到强制打断（自身超时 / 收到取消）→ 终态
        # ``WORKER_INTERRUPTED`` / ``CANCELLED``（**不**伪装成功，**不**落 FAILED）。
        if lease_manager is not None and record is not None:
            _finalize_interrupt(lease_manager, record, exc.reason)
        return {
            "execution_id": execution_id,
            "task_id": payload.get("task_id") or message.get("task_id"),
            "status": _interrupt_status(exc.reason),
            "skipped": True,
            "interrupted": True,
        }
    except Exception as exc:  # noqa: BLE001 - 落 FAILED 后原样抛出（非静默）
        if lease_manager is not None and record is not None:
            lease_manager.fail(record, error=f"{type(exc).__name__}: {exc}")
        raise

    # ③b 执行中时长上限（A-2）：运行已超 ``max_duration_seconds`` → 以 ``WORKER_INTERRUPTED``
    #     收尾（**丢弃结果、不伪装成功**）；未超（含未启用）→ 正常落终态（零回归）。
    max_duration = _max_duration_seconds(ctx)
    if max_duration is not None and record is not None and _exceeded_duration(record, max_duration):
        if lease_manager is not None:
            lease_manager.interrupt(record, reason="deadline_exceeded")
        return {
            "execution_id": execution_id,
            "task_id": payload.get("task_id") or message.get("task_id"),
            "status": STATUS_WORKER_INTERRUPTED,
            "skipped": True,
            "interrupted": True,
        }

    # ③c 磁盘占用强制 + 水位告警（A-3；落 SUCCESS 终态**之前**）：超 ``max_disk_bytes`` →
    #     ``enforce_disk`` 抛 ``RESOURCE_LIMIT_EXCEEDED``（拒绝伪装成功，**非静默**）。
    used_bytes = _workspace_usage(ctx, payload)
    if used_bytes is not None and lease_manager is not None and record is not None:
        lease_manager.enforce_disk(record, used_bytes=used_bytes)

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


def _deadline_exceeded(payload: dict[str, Any]) -> bool:
    """``payload.deadline_at`` 是否已过期（R5 补全轮 F8c）。

    缺 ``deadline_at``（未启用提交面 deadline）/ 无法解析 → **不**判过期（``False``，向后兼容）。
    ``deadline_at`` 无时区 → 按 UTC 归一（由 ``astra_common.time.utcnow`` 生成的带 tz 值为准）。
    """
    raw = payload.get("deadline_at")
    if not raw:
        return False
    try:
        deadline = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return utcnow() >= deadline


# -- A-1：并发受限「自动留守 + 有界择机重派」 --------------------------------


def _standby_response(
    message: dict[str, Any],
    payload: dict[str, Any],
    execution_id: str,
    task_id: str,
    ctx: HandlerContext,
) -> dict[str, Any]:
    """并发受限 → 自动留守 + **有界**择机重派（A-1；**非静默**）。

    约定（组合根注入，均可缺省 = 不启用）：

    - ``ctx.services["redispatch"]``：重派回调 ``Callable[[dict], Any]``（把消息**重新入队**，
      具体延迟 / 退避策略由该回调决定；处理器**不**直连队列，保持执行体 / 队列正交 R-23）；
    - ``ctx.services["max_redispatch_attempts"]``：重派次数上限（**有界**，防无限循环）。

    行为：

    - 已注入回调且未达上限 → 以 ``payload.redispatch_count + 1`` 重派，返回 ``standby`` +
      ``skipped``（**本回合未运行**；并发位释放后该重投消息进入 ``RUNNING``）；
    - 未启用重派 / 达上限 → 保持既有 ``concurrency_limited``（**非静默**）；达上限记
      ``worker.redispatch_exhausted`` WARNING 留证。

    Returns:
        含 ``status``（``standby`` / ``concurrency_limited``）与 ``redispatch_count`` 的返回物。
    """
    count = _redispatch_count(payload)
    limit = ctx.services.get("max_redispatch_attempts")
    redispatch = ctx.services.get("redispatch")
    if redispatch is not None and limit is not None and count < int(limit):
        new_message = _with_redispatch_count(message, count + 1)
        try:
            redispatch(new_message)
        except (
            Exception
        ) as exc:  # noqa: BLE001 - 重派失败**非静默**（记日志并回落 concurrency_limited）
            _logger.warning(
                "worker.standby_redispatch_failed",
                extra={
                    "handler": HANDLER_KEY,
                    "execution_id": execution_id,
                    "task_id": task_id,
                    "redispatch_count": count,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return {
                "execution_id": execution_id,
                "task_id": task_id,
                "status": STATUS_CONCURRENCY_LIMITED,
                "skipped": True,
                "redispatch_count": count,
            }
        _logger.info(
            "worker.standby_redispatch",
            extra={
                "handler": HANDLER_KEY,
                "execution_id": execution_id,
                "task_id": task_id,
                "redispatch_count": count + 1,
                "limit": int(limit),
            },
        )
        return {
            "execution_id": execution_id,
            "task_id": task_id,
            "status": STATUS_STANDBY,
            "skipped": True,
            "redispatch_count": count + 1,
        }
    if limit is not None and count >= int(limit):
        _logger.warning(
            "worker.redispatch_exhausted",
            extra={
                "handler": HANDLER_KEY,
                "execution_id": execution_id,
                "task_id": task_id,
                "redispatch_count": count,
                "limit": int(limit),
            },
        )
    return {
        "execution_id": execution_id,
        "task_id": task_id,
        "status": STATUS_CONCURRENCY_LIMITED,
        "skipped": True,
        "redispatch_count": count,
    }


def _with_redispatch_count(message: dict[str, Any], count: int) -> dict[str, Any]:
    """复制消息并写入 ``payload.redispatch_count``（**不**改原消息）。"""
    new_message = dict(message)
    new_payload = dict(new_message.get("payload") or {})
    new_payload["redispatch_count"] = count
    new_message["payload"] = new_payload
    return new_message


def _redispatch_count(payload: dict[str, Any]) -> int:
    """解析 ``payload.redispatch_count``（缺省 / 非法 → ``0``）。"""
    try:
        return int(payload.get("redispatch_count") or 0)
    except (TypeError, ValueError):
        return 0


# -- A-2：执行中强制打断 ------------------------------------------------------


def _interrupt_reason(ctx: HandlerContext, payload: dict[str, Any]) -> str | None:
    """读取注入的**显式中断信号**（A-2；缺省 = 无信号）。

    ``ctx.services["interrupt_signal"]``：``Callable[[dict], bool | str]``——
    返回真值即中断（``True`` → 原因 ``interrupted``；非空字符串 → 该字符串为原因，如
    ``cancelled`` / ``deadline_exceeded``）；探测异常 / 空值 → ``None``（不中断，向后兼容）。
    """
    signal = ctx.services.get("interrupt_signal")
    if not callable(signal):
        return None
    result = signal(payload)
    if not result:
        return None
    return result if isinstance(result, str) else "interrupted"


def _interrupt_status(reason: str) -> str:
    """中断原因 → 返回状态（``cancelled`` → ``cancelled``；其余 → ``WORKER_INTERRUPTED``）。"""
    return "cancelled" if reason == "cancelled" else STATUS_WORKER_INTERRUPTED


def _finalize_interrupt(lease_manager: Any, record: Any, reason: str) -> None:
    """按原因落中断 / 取消终态（A-2；取消 → ``CANCELLED``，否则 → ``WORKER_INTERRUPTED``）。"""
    if reason == "cancelled":
        lease_manager.cancel(record, reason=reason)
    else:
        lease_manager.interrupt(record, reason=reason)


def _max_duration_seconds(ctx: HandlerContext) -> int | None:
    """读取注入的单次执行时长上限（A-2；缺省 / 非法 → ``None`` = 不启用）。"""
    value = ctx.services.get("max_duration_seconds")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _exceeded_duration(record: Any, max_seconds: int) -> bool:
    """执行记录自 ``started_at`` 起已耗时是否**超过** ``max_seconds``（A-2）。"""
    started_at = getattr(record, "started_at", None)
    if started_at is None:
        return False
    elapsed = (utcnow() - ensure_utc(started_at)).total_seconds()
    return elapsed > max_seconds


# -- A-3：磁盘占用统计 --------------------------------------------------------


def _workspace_usage(ctx: HandlerContext, payload: dict[str, Any]) -> int | None:
    """经注入的统计回调取 workspace 占用字节数（A-3；缺省 → ``None`` = 不统计）。

    ``ctx.services["workspace_disk_usage"]``：``Callable[[dict], int]``（组合根实现实际统计，
    处理器**不**直连文件系统 / 宿主路径）。探测异常**向上传播**（非静默，H-7）。
    """
    probe = ctx.services.get("workspace_disk_usage")
    if not callable(probe):
        return None
    return int(probe(payload))
