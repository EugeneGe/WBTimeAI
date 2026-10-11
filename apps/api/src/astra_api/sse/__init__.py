"""SSE 子包（W6 / T1-28；设计 §2.9）。

- ``encoder``：领域事件 ``type`` → SSE 通道 + 帧编码（**纯字符串映射**）；
- ``stream``：SSE 流生成器（回放 + 实时订阅 + 心跳 + 续传 + 断连取消）。

🔴 落在 ``astra_api/sse/``（**非** ``routers/``）——实时事件订阅与 Runtime 回调
   不落 Router，确保 Router 保持「薄」（N-8 / 裁定 §9）。
"""

from __future__ import annotations

from .encoder import (
    SSE_CHANNEL_BY_DOMAIN_TYPE,
    channel_for,
    encode_data_frame,
    encode_heartbeat,
)
from .stream import StreamDeps, stream_run

__all__ = [
    "SSE_CHANNEL_BY_DOMAIN_TYPE",
    "channel_for",
    "encode_data_frame",
    "encode_heartbeat",
    "StreamDeps",
    "stream_run",
]
