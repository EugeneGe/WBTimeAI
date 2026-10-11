"""``txt`` 解析器（**标准库**，零额外依赖；W5 裁定 B8 / §2.2）。"""

from __future__ import annotations

from typing import Any

from .base import ParsedDocument

__all__ = ["TextParser"]

#: 视为纯文本的 MIME 集合。
_TEXT_MIMES = frozenset({"text/plain", "text/x-text"})


class TextParser:
    """纯文本解析器（UTF-8 解码，容忍非法字节）。"""

    name = "text"

    def supports(self, mime: str | None, source_type: str) -> bool:
        """支持 ``text/plain``，或源类型为 ``text``（裸文本）。"""
        return source_type == "text" or (mime or "") in _TEXT_MIMES

    def parse(self, data: bytes, *, meta: dict[str, Any] | None = None) -> ParsedDocument:
        """把字节按 UTF-8 解码为文本（非法字节以 ``replace`` 容错）。"""
        text = data.decode("utf-8", errors="replace")
        metadata: dict[str, Any] = {"format": "txt"}
        metadata.update(meta or {})
        return ParsedDocument(text=text, metadata=metadata)
