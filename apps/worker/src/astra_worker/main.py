"""Astra AI Worker 启动 + 消费循环（W1 / T2-02；设计 §2.9 / §2.16）。

``main()`` → ``run_worker(get_settings())``；``run_worker`` 经 **``build_providers``**
取 :class:`~astra_config.providers.Providers`（**唯一装配点**），注册 ``tasks/`` 处理器，
进入消费循环（``TaskQueue.dequeue() → dispatch → ack()``）。

🔴 **T2-59 启动恢复接线（R5 补正）**：``run_worker`` 在**消费循环开始前**触发
   :meth:`astra_worker.recovery.LeaseManager.recover_on_startup`——
   ① 过期 ``RUNNING`` → ``WORKER_INTERRUPTED``（**不**伪装成功 / **不**静默重放）；
   ② 持久 ``PENDING`` 任务经**注入 dispatch** 重投（``queue.enqueue``）。
   缺 ``providers.database``（如测试桩）→ **跳过并记 WARNING**（非静默；不阻断启动）。

🔴 本进程**不判断 ``ASTRA_MODE``**（唯一分流点在 ``build_providers``）；执行体 / 队列**正交**：
   仅按注入的 ``providers.task_queue`` 消费（社区 ``InProcess``、Team ``Redis``）。
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any

from astra_config import Settings, build_providers, get_settings

from astra_worker import HandlerContext
from astra_worker.tasks import HANDLERS

__all__ = ["USAGE", "run_worker", "main"]

_logger = logging.getLogger("astra_worker")

#: 命令行用法（``astra-worker --help``）。
USAGE = (
    "Astra AI Worker（后台任务消费者）\n"
    "\n"
    "用法：\n"
    "  astra-worker            以当前配置（ASTRA_*）启动并消费队列\n"
    "  astra-worker --help     显示本帮助\n"
    "\n"
    "消费的任务类型：agent.run / workflow.run / knowledge.index / maintenance.cleanup / "
    "project.clone / remote.agent_run\n"
    "装配与分流：仅经 astra_config.providers.build_providers（不判断 ASTRA_MODE）。\n"
)

#: 处理器签名（与 ``astra_worker.tasks.Handler`` 一致）。
Handler = Callable[[dict[str, Any], HandlerContext], dict[str, Any]]


def _dispatch(
    message: dict[str, Any],
    registry: dict[str, Handler],
    ctx: HandlerContext,
) -> dict[str, Any]:
    """分发单条消息；未知处理器 / 处理器异常**不静默**（记 WARNING / 返回失败结果）。"""
    handler_key = str(message.get("handler") or message.get("type") or "")
    handler = registry.get(handler_key)
    if handler is None:
        _logger.warning("worker.unknown_handler", extra={"handler": handler_key})
        return {"ok": False, "handler": handler_key, "error": f"未知处理器：{handler_key}"}
    try:
        result = handler(message, ctx)
    except Exception as exc:  # noqa: BLE001 - 单任务失败不终止 Worker（非静默：记日志）
        _logger.exception("worker.handler_failed", extra={"handler": handler_key})
        return {"ok": False, "handler": handler_key, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "handler": handler_key, "result": result}


def _build_lease_manager(providers: Any, settings: Settings) -> Any | None:
    """按 ``Providers`` 装配 :class:`LeaseManager`（T2-59 补正）。

    ``database.session_factory`` 不可用（测试桩 / 极简 Providers）→ ``None``（调用方据此
    **跳过**启动恢复并记 WARNING，**非静默**）。执行限期额（F8）经 ``settings.remote_execution``
    注入（可空；缺省 = 不启用，向后兼容）。
    """
    database = getattr(providers, "database", None)
    session_factory = getattr(database, "session_factory", None)
    if not callable(session_factory):
        return None
    from astra_database import SqlTaskExecutionRepository
    from astra_task import ExecutionRecorder

    from astra_worker.recovery import LeaseManager

    limits = getattr(settings, "remote_execution", None)
    return LeaseManager(
        ExecutionRecorder(SqlTaskExecutionRepository(session_factory)),
        max_concurrent_executions=getattr(limits, "max_concurrent_executions", None),
        max_artifact_count=getattr(limits, "max_artifact_count", None),
        max_artifact_bytes=getattr(limits, "max_artifact_bytes", None),
        max_disk_bytes=getattr(limits, "max_disk_bytes", None),
        disk_enforce=bool(getattr(limits, "disk_enforce", True)),
        disk_high_watermark_ratio=getattr(limits, "disk_high_watermark_ratio", None),
    )


def _dir_size_bytes(root: str) -> int:
    """**尽力而为**统计目录占用字节数（A-3；目录不存在 / 无权限 → 已统计部分）。

    仅统计常规文件，错误逐项忽略（探测失败**不**中断执行；超限判定仍以统计数据为准）。
    空路径 → ``0``（避免误遍历当前目录）。
    """
    import os

    if not root:
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda _err: None):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total


def _recover_on_startup(providers: Any, *, queue: Any, lease_manager: Any | None) -> None:
    """启动恢复 sweep（T2-59 补正；**消费循环开始前**调用一次）。

    ① 过期 ``RUNNING`` → ``WORKER_INTERRUPTED``；② 持久 ``PENDING`` 经**注入 dispatch** 重投。
    缺 ``lease_manager``（无 database Provider）→ 记 WARNING 并跳过（非静默，不阻断启动）。
    """
    if lease_manager is None:
        _logger.warning("worker.recovery_skipped", extra={"reason": "no_database_provider"})
        return
    from astra_database import SqlTaskRepository

    from astra_worker.tasks import make_message

    task_repository = SqlTaskRepository(providers.database.session_factory)

    def _dispatch(task: Any) -> None:
        """把持久 ``PENDING`` 任务重新投递到队列（**经注入 dispatch**，非直连）。"""
        queue.enqueue(
            make_message(
                str(getattr(task, "type", "") or ""),
                dict(getattr(task, "payload", None) or {}),
                task_id=str(getattr(task, "task_id", "") or ""),
            )
        )

    report = lease_manager.recover_on_startup(task_repository=task_repository, dispatch=_dispatch)
    _logger.info(
        "worker.recovery_done",
        extra={
            "interrupted": len(report.interrupted),
            "redelivered": len(report.redelivered),
        },
    )


def run_worker(
    settings: Settings,
    *,
    poll_interval: float = 0.5,
    stop_when_empty: bool = False,
    max_messages: int | None = None,
    handlers: dict[str, Handler] | None = None,
) -> int:
    """启动 Worker 消费循环。

    启动顺序（T2-59 补正）：装配 Providers → 装配租约管理器（注入 handler）→ **启动恢复
    sweep**（过期 ``RUNNING`` → ``WORKER_INTERRUPTED``；持久 ``PENDING`` 重投）→ 消费循环。

    Args:
        settings: 生效配置（经 ``build_providers`` 装配 Providers）。
        poll_interval: 队列空闲时的轮询间隔（秒）。
        stop_when_empty: 队列空即退出（测试 / 一次性消费）。
        max_messages: 最多消费的消息数（``None`` = 不限制）。
        handlers: 覆盖 / 补充处理器（测试可注入桩处理器）。

    Returns:
        已消费（dequeue + dispatch + ack）的消息数。
    """
    providers = build_providers(settings)
    ctx = HandlerContext(providers=providers)
    registry: dict[str, Handler] = dict(HANDLERS)
    if handlers:
        registry.update(handlers)

    queue = providers.task_queue
    if queue is None:
        raise RuntimeError("Providers.task_queue 未装配，无法启动 Worker")

    # T2-59 补正：装配租约管理器（供 remote.agent_run handler 使用）并在**消费循环前**
    # 触发**启动恢复 sweep**（过期 RUNNING → WORKER_INTERRUPTED + PENDING 重投）。
    lease_manager = _build_lease_manager(providers, settings)
    if lease_manager is not None:
        ctx.services["lease_manager"] = lease_manager

    # A 组（V0.4.1）约定注入（均可缺省 = 不启用；契约见 remote_agent_run 处理器 docstring）：
    #   - A-1 留守重派：``redispatch`` 回调 + 有界次数上限；
    #   - A-2 中段打断：``max_duration_seconds``（运行中超时长 → WORKER_INTERRUPTED）；
    #   - A-3 磁盘统计：``workspace_disk_usage``（尽力而为统计 workspace 占用字节）。
    limits = getattr(settings, "remote_execution", None)
    ctx.services["max_redispatch_attempts"] = getattr(limits, "max_redispatch_attempts", None)
    ctx.services["max_duration_seconds"] = getattr(limits, "max_duration_seconds", None)

    def _redispatch(queued_message: dict[str, Any]) -> None:
        """A-1：把留守消息**重新入队**（择机重派；节奏由队列 / 消费循环决定）。"""
        queue.enqueue(queued_message)

    ctx.services["redispatch"] = _redispatch
    ctx.services["workspace_disk_usage"] = lambda _payload: _dir_size_bytes(
        str(getattr(settings, "workspace_root", "") or "")
    )

    _recover_on_startup(providers, queue=queue, lease_manager=lease_manager)

    processed = 0
    _logger.info("worker.started", extra={"handlers": sorted(registry)})
    try:
        while True:
            if max_messages is not None and processed >= max_messages:
                break
            message = queue.dequeue()
            if message is None:
                if stop_when_empty or max_messages is not None:
                    break
                import time

                time.sleep(poll_interval)
                continue
            result = _dispatch(message, registry, ctx)
            queue.ack(message)
            processed += 1
            _logger.info("worker.processed", extra={"result": result})
    except KeyboardInterrupt:  # pragma: no cover - 交互式中断
        _logger.info("worker.interrupted")
    finally:
        _logger.info("worker.stopped", extra={"processed": processed})
    return processed


def main() -> None:
    """Worker 入口（``[project.scripts] astra-worker`` / ``python -m astra_worker.main``）。"""
    argv = sys.argv[1:]
    if any(arg in ("-h", "--help") for arg in argv):
        print(USAGE)
        return
    run_worker(get_settings())


if __name__ == "__main__":  # pragma: no cover - 进程入口（等价 console script）
    main()
