"""``html`` 解析器（可选依赖 ``beautifulsoup4``，函数级延迟导入；W5 裁定 B8）。

缺失依赖 → :class:`~astra_core.DomainError` ``DEPENDENCY_MISSING``（**非静默**）。
"""

from __future__ import annotations

from typing import Any

from .base import ParsedDocument, missing_dependency_error

__all__ = ["HtmlParser"]

#: 视为 HTML 的 MIME 集合。
_HTML_MIMES = frozenset({"text/html", "application/xhtml+xml"})

#: 标题标签（``h1``..``h6``）。
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


class HtmlParser:
    """HTML 解析器（``html.parser``，**不引** ``lxml``）。"""

    name = "html"

    def supports(self, mime: str | None, source_type: str) -> bool:
        """支持 ``text/html`` / ``application/xhtml+xml``。"""
        return (mime or "") in _HTML_MIMES

    def parse(self, data: bytes, *, meta: dict[str, Any] | None = None) -> ParsedDocument:
        """解析 HTML，去除脚本 / 样式，提取标题路径与正文。

        Raises:
            DomainError: 缺少 ``beautifulsoup4``（``DEPENDENCY_MISSING``）。
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - 取决于是否安装 extra
            raise missing_dependency_error("beautifulsoup4", parser=self.name) from exc

        soup = BeautifulSoup(data, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        headings = [node.get_text(strip=True) for node in soup.find_all(_HEADING_TAGS)]
        text = soup.get_text("\n", strip=True)
        metadata: dict[str, Any] = {"format": "html", "headings": headings}
        metadata.update(meta or {})
        return ParsedDocument(text=text, metadata=metadata)
