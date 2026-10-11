"""Astra AI Worker 启动 + 消费循环（W1 / T2-02；设计 §2.9 / §2.16）。

``main()`` → ``run_worker(get_settings())``；``run_worker`` 经 **``build_providers``**
取 :class:`~astra_config.providers.Providers`（**唯一装配点**），注册 ``tasks/`` 处理器，
进入消费循环（``TaskQueue.dequeue() → dispatch → ack()``）。

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
    "消费的任务类型：agent.run / workflow.run / knowledge.index\n"
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


def run_worker(
    settings: Settings,
    *,
    poll_interval: float = 0.5,
    stop_when_empty: bool = False,
    max_messages: int | None = None,
    handlers: dict[str, Handler] | None = None,
) -> int:
    """启动 Worker 消费循环。

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
