"""``FixedChunker``：固定长度 + 重叠分块（设计 §2.6 / §5 #7 首批 ``fixed``；W5 / T2-28）。

保留 Parser 产出的标题路径 / 页码到每块 ``metadata``（来自 :class:`ParsedDocument`）。
参数取自 ``kb.chunk_config={strategy, size, overlap}``（默认 ``fixed/800/100``）。

🔴 本子模块**零 Web / ORM**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainError, ErrorCode

from ..parser import ParsedDocument

__all__ = ["ChunkDraft", "FixedChunker"]

#: 默认分块大小（字符 / 近似 token）。
DEFAULT_CHUNK_SIZE = 800

#: 默认分块重叠。
DEFAULT_CHUNK_OVERLAP = 100


@dataclass
class ChunkDraft:
    """分块草稿（落库前；不依赖 ORM）。

    Attributes:
        ordinal: 块序号（文档内唯一；断点续跑锚）。
        content: 块文本。
        token_count: token 数（近似；可空）。
        metadata: 附加元数据（标题路径 / 页码 / 格式等）。
    """

    ordinal: int
    content: str
    token_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class FixedChunker:
    """固定长度 + 重叠滑窗分块器。

    Args:
        size: 窗口大小（字符数，> 0）。
        overlap: 相邻窗口重叠（字符数，``0 <= overlap < size``）。

    Raises:
        DomainError: ``size`` / ``overlap`` 非法（``VALIDATION_ERROR``）。
    """

    def __init__(
        self, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP
    ) -> None:
        _validate(size, overlap)
        self._size = size
        self._overlap = overlap

    @property
    def size(self) -> int:
        """窗口大小。"""
        return self._size

    @property
    def overlap(self) -> int:
        """窗口重叠。"""
        return self._overlap

    def chunk(
        self,
        parsed: ParsedDocument,
        *,
        size: int | None = None,
        overlap: int | None = None,
    ) -> list[ChunkDraft]:
        """把 :class:`ParsedDocument` 切为 :class:`ChunkDraft` 列表。

        Args:
            parsed: 解析产物（``text`` + ``metadata``）。
            size: 覆盖窗口大小（``None`` = 用构造期值）。
            overlap: 覆盖重叠（``None`` = 用构造期值）。

        Returns:
            分块草稿列表（``metadata`` 含原始标题路径 / 页码等）。
        """
        window = self._size if size is None else size
        gap = self._overlap if overlap is None else overlap
        _validate(window, gap)

        text = parsed.text or ""
        if not text.strip():
            return []

        base_metadata = dict(parsed.metadata)
        step = window - gap
        drafts: list[ChunkDraft] = []
        ordinal = 0
        start = 0
        length = len(text)
        while start < length:
            piece = text[start : start + window]
            drafts.append(
                ChunkDraft(
                    ordinal=ordinal,
                    content=piece,
                    token_count=len(piece.split()) or None,
                    metadata=dict(base_metadata),
                )
            )
            ordinal += 1
            if start + window >= length:
                break
            start += step
        return drafts


def _validate(size: int, overlap: int) -> None:
    """校验分块参数（``size > 0`` 且 ``0 <= overlap < size``）。"""
    if size <= 0:
        raise DomainError(
            f"分块 size 必须为正：{size}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "invalid_chunk_size", "size": size},
        )
    if overlap < 0 or overlap >= size:
        raise DomainError(
            f"分块 overlap 非法（需 0 <= overlap < size）：overlap={overlap}, size={size}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "invalid_chunk_overlap", "overlap": overlap, "size": size},
        )
