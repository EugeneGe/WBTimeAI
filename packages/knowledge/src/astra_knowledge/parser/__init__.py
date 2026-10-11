"""``astra_knowledge`` Parser 子模块（设计 §2.6；W5 / T2-28）。

- :class:`ParserRegistry` / :class:`Parser` / :class:`ParsedDocument`（``base``）；
- 内置解析器：``txt`` / ``md``（标准库），``html`` / ``pdf`` / ``docx``（可选 extra
  ``astra-knowledge[parsers]``，函数级延迟导入）。

🔴 本子模块**零 Web / ORM**。
"""

from __future__ import annotations

from .base import (
    PARSER_EXTRA_NAME,
    ParsedDocument,
    Parser,
    ParserRegistry,
    missing_dependency_error,
)
from .docx import DocxParser
from .html import HtmlParser
from .markdown import MarkdownParser
from .pdf import PdfParser
from .text import TextParser

__all__ = [
    "ParsedDocument",
    "Parser",
    "ParserRegistry",
    "PARSER_EXTRA_NAME",
    "missing_dependency_error",
    "TextParser",
    "MarkdownParser",
    "HtmlParser",
    "PdfParser",
    "DocxParser",
]
