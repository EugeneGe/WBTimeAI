"""``astra_knowledge`` Chunker 子模块（设计 §2.6；W5 / T2-28）。

- :class:`FixedChunker`：固定长度 + 重叠分块（默认 ``size=800`` / ``overlap=100``）。

🔴 本子模块**零 Web / ORM**。
"""

from __future__ import annotations

from .fixed import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    ChunkDraft,
    FixedChunker,
)

__all__ = [
    "ChunkDraft",
    "FixedChunker",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
]
