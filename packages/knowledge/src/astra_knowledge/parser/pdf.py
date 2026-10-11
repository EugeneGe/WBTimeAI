"""``pdf`` 解析器（可选依赖 ``pypdf``，函数级延迟导入；W5 裁定 B8）。

缺失依赖 → :class:`~astra_core.DomainError` ``DEPENDENCY_MISSING``（**非静默**）。
"""

from __future__ import annotations

import io
from typing import Any

from .base import ParsedDocument, missing_dependency_error

__all__ = ["PdfParser"]

#: 视为 PDF 的 MIME 集合。
_PDF_MIMES = frozenset({"application/pdf"})


class PdfParser:
    """PDF 解析器（逐页抽取文本，记录页数）。"""

    name = "pdf"

    def supports(self, mime: str | None, source_type: str) -> bool:
        """支持 ``application/pdf``。"""
        return (mime or "") in _PDF_MIMES

    def parse(self, data: bytes, *, meta: dict[str, Any] | None = None) -> ParsedDocument:
        """逐页抽取文本，合并为 ``text`` 并记录 ``page_count``。

        Raises:
            DomainError: 缺少 ``pypdf``（``DEPENDENCY_MISSING``）。
        """
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - 取决于是否安装 extra
            raise missing_dependency_error("pypdf", parser=self.name) from exc

        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages)
        metadata: dict[str, Any] = {"format": "pdf", "page_count": len(pages)}
        metadata.update(meta or {})
        return ParsedDocument(text=text, metadata=metadata)
