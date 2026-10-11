"""``md`` 解析器（**标准库**，零额外依赖；W5 裁定 B8 / §2.2）。

提取标题路径（``^#{1,6}\\s``）到 ``metadata["headings"]``（不引 ``markdown-it-py``，避免超范围）。
"""

from __future__ import annotations

import re
from typing import Any

from .base import ParsedDocument

__all__ = ["MarkdownParser"]

#: 视为 Markdown 的 MIME 集合。
_MARKDOWN_MIMES = frozenset({"text/markdown", "text/x-markdown"})

#: ATX 标题（``# H1`` … ``###### H6``）。
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", re.MULTILINE)


class MarkdownParser:
    """Markdown 解析器（标题路径提取，正文保持原文）。"""

    name = "markdown"

    def supports(self, mime: str | None, source_type: str) -> bool:
        """支持 ``text/markdown`` / ``text/x-markdown``。"""
        return (mime or "") in _MARKDOWN_MIMES

    def parse(self, data: bytes, *, meta: dict[str, Any] | None = None) -> ParsedDocument:
        """把字节解码为 Markdown，并提取标题路径到 ``metadata["headings"]``。"""
        text = data.decode("utf-8", errors="replace")
        headings = [match.group(2) for match in _HEADING_RE.finditer(text)]
        metadata: dict[str, Any] = {"format": "markdown", "headings": headings}
        metadata.update(meta or {})
        return ParsedDocument(text=text, metadata=metadata)
