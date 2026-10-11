"""``RedisTaskQueue``（Team / Arq）——W1 / T2-02。

与 :class:`~astra_task.queue.InProcessTaskQueue` **接口不变**（``enqueue`` / ``dequeue`` /
``ack`` / ``size``）；差异仅在**承载介质**（Redis 列表）与**持久化 at-least-once** 语义。

🔴 依赖策略（W1 裁定 §3.6）：``arq`` / ``redis`` 一律**函数级延迟导入**（**模块级绝不
   import**），保证社区无 Redis 亦可运行（对齐 ``I-P2-21``）；两者仅声明于
   ``astra-task[redis]`` 可选 extra，**社区零新运行时依赖**。
"""

from __future__ import annotations

import json
from typing import Any, Generic, TypeVar

__all__ = ["RedisTaskQueue", "redis_available"]

T = TypeVar("T")

#: 默认队列名（Redis 列表键）。
_DEFAULT_QUEUE_NAME = "astra:tasks"


def redis_available() -> bool:
    """探测 ``astra-task[redis]`` 可选 extra 是否可导入（``redis`` + ``arq``）。

    🔴 **函数级延迟导入**（模块级不 import）：社区未装 extra 时返回 ``False``，
    调用方据此**回落占位**（非静默降级）。

    Returns:
        ``True`` 表示 ``redis`` 与 ``arq`` 均可导入。
    """
    try:  # 函数级延迟导入：模块级绝不 import 第三方（I-P2-21）
        import arq  # noqa: F401
        import redis  # noqa: F401
    except ImportError:
        return False
    return True


def _encode(item: Any) -> str:
    """序列化队列元素为 Redis 字符串（JSON）。"""
    return json.dumps(item)


def _decode(raw: str | bytes) -> Any:
    """反序列化 Redis 字符串为队列元素。"""
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    return json.loads(text)


class RedisTaskQueue(Generic[T]):
    """Redis 任务队列（Team；Arq 承载）。

    以 Redis 列表实现 at-least-once：``enqueue`` → ``RPUSH``；``dequeue`` →
    ``LPOP`` + 入 ``<queue>:processing`` 在途列表；``ack`` → 从在途列表 ``LREM``；
    ``size`` → ``LLEN``。

    Attributes:
        redis_url: Redis 连接串（如 ``redis://host:6379/0``）。
        queue_name: 队列名（Redis 列表键）。

    Note:
        ``T`` 须为 **JSON 可序列化** 的对象（Worker 消息为 ``dict``）。
        本类**不**在构造期建立连接（懒连接），仅在首次操作时延迟导入 ``redis``。
    """

    def __init__(self, *, redis_url: str, queue_name: str = _DEFAULT_QUEUE_NAME) -> None:
        """构造 Redis 任务队列（不建立连接）。

        Args:
            redis_url: Redis 连接串。
            queue_name: 队列名（默认 ``astra:tasks``）。
        """
        self._redis_url = redis_url
        self._queue_name = queue_name
        self._processing_name = f"{queue_name}:processing"
        self._client: Any | None = None

    @property
    def redis_url(self) -> str:
        """Redis 连接串（只读）。"""
        return self._redis_url

    @property
    def queue_name(self) -> str:
        """队列名（只读）。"""
        return self._queue_name

    def _get_client(self) -> Any:
        """返回同步 Redis 客户端（**懒创建**；函数级延迟导入 ``redis``）。"""
        if self._client is None:
            import redis  # 函数级延迟导入

            self._client = redis.Redis.from_url(self._redis_url)
        return self._client

    def arq_redis_settings(self) -> Any:
        """返回 Arq 的 ``RedisSettings``（供 ``apps/worker`` 以 ``arq.worker.Worker`` 承载）。

        🔴 **函数级延迟导入** ``arq``。

        Returns:
            ``arq.connections.RedisSettings``。
        """
        from arq.connections import RedisSettings  # 函数级延迟导入

        return RedisSettings.from_dsn(self._redis_url)

    def enqueue(self, item: T) -> None:
        """入队（``RPUSH``）。"""
        self._get_client().rpush(self._queue_name, _encode(item))

    def dequeue(self) -> T | None:
        """出队（``LPOP``）并把元素移入在途列表；空队列返回 ``None``。"""
        raw = self._get_client().lpop(self._queue_name)
        if raw is None:
            return None
        self._get_client().rpush(self._processing_name, raw)
        return _decode(raw)

    def ack(self, item: T) -> None:
        """确认完成（从在途列表 ``LREM`` 移除首个匹配项；幂等）。"""
        self._get_client().lrem(self._processing_name, 1, _encode(item))

    def size(self) -> int:
        """待处理元素数量（``LLEN``）。"""
        return int(self._get_client().llen(self._queue_name))
