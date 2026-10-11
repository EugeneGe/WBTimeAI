"""``Parser`` 抽象 + 注册表（设计 §2.6；W5 裁定 B8 / §2.2）。

- :class:`ParsedDocument`：解析产物（``text`` + ``metadata``：标题路径 / 页码等）；
- :class:`Parser`：解析器 Protocol（``supports`` + ``parse``）；
- :class:`ParserRegistry`：按 ``mime`` / ``source_type`` 选路；缺依赖**明确报错**
  （``DomainError(DEPENDENCY_MISSING)``，**非静默**）；
- :func:`missing_dependency_error`：构造缺依赖异常（提示安装 ``astra-knowledge[parsers]``）。

🔴 本子模块**零 Web / ORM**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode

__all__ = [
    "ParsedDocument",
    "Parser",
    "ParserRegistry",
    "PARSER_EXTRA_NAME",
    "missing_dependency_error",
]

#: 可选解析依赖所属 extra 名（``astra-knowledge[parsers]``）。
PARSER_EXTRA_NAME = "parsers"


@dataclass
class ParsedDocument:
    """解析产物（文本 + 结构化元数据）。

    Attributes:
        text: 归一化后的纯文本。
        metadata: 附加元数据（``format`` / ``headings``（标题路径）/ ``page_count`` 等）。
    """

    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Parser(Protocol):
    """解析器接口（按 ``mime`` / ``source_type`` 选路，产出一份 :class:`ParsedDocument`）。"""

    #: 解析器名（如 ``pdf`` / ``markdown``）。
    name: str

    def supports(self, mime: str | None, source_type: str) -> bool:
        """是否支持给定 ``mime`` / ``source_type``。"""
        ...

    def parse(self, data: bytes, *, meta: dict[str, Any] | None = None) -> ParsedDocument:
        """解析字节内容为 :class:`ParsedDocument`。

        Raises:
            DomainError: 可选依赖缺失（``DEPENDENCY_MISSING``）或内容非法（``VALIDATION_ERROR``）。
        """
        ...


def missing_dependency_error(package: str, *, parser: str) -> DomainError:
    """构造「可选解析依赖缺失」异常（``DEPENDENCY_MISSING``，**非静默**）。"""
    return DomainError(
        f"解析器 '{parser}' 需要可选依赖 '{package}'：请安装 astra-knowledge"
        f"[{PARSER_EXTRA_NAME}]",
        code=ErrorCode.DEPENDENCY_MISSING,
        data={"parser": parser, "package": package, "extra": PARSER_EXTRA_NAME},
    )


class ParserRegistry:
    """解析器注册表（按 ``mime`` / ``source_type`` 选路）。"""

    def __init__(self, parsers: list[Parser] | None = None) -> None:
        self._parsers: list[Parser] = list(parsers or [])

    @property
    def parsers(self) -> list[Parser]:
        """已注册解析器（副本）。"""
        return list(self._parsers)

    def register(self, parser: Parser) -> None:
        """注册一个解析器（靠后注册者**不覆盖**前者：选路取首个支持者）。"""
        self._parsers.append(parser)

    def select(self, *, mime: str | None, source_type: str) -> Parser:
        """选择首个支持给定 ``mime`` / ``source_type`` 的解析器。

        Raises:
            DomainError: 无可用解析器（``VALIDATION_ERROR``）。
        """
        for parser in self._parsers:
            if parser.supports(mime, source_type):
                return parser
        raise DomainError(
            f"无可用解析器：mime={mime!r}, source_type={source_type!r}",
            code=ErrorCode.VALIDATION_ERROR,
            data={"reason": "no_parser", "mime": mime, "source_type": source_type},
        )

    def parse(
        self,
        data: bytes,
        *,
        mime: str | None,
        source_type: str,
        meta: dict[str, Any] | None = None,
    ) -> ParsedDocument:
        """选路并解析字节内容为 :class:`ParsedDocument`。

        Raises:
            DomainError: 无可用解析器（``VALIDATION_ERROR``）或依赖缺失
                （``DEPENDENCY_MISSING``）。
        """
        parser = self.select(mime=mime, source_type=source_type)
        return parser.parse(data, meta=meta or {})

    @classmethod
    def default(cls) -> ParserRegistry:
        """构造内置注册表（``md`` → ``html`` → ``pdf`` → ``docx`` → ``txt``）。

        ``txt`` **最后**注册：其 ``supports`` 兜底较宽，避免抢占其它格式。
        """
        from .docx import DocxParser
        from .html import HtmlParser
        from .markdown import MarkdownParser
        from .pdf import PdfParser
        from .text import TextParser

        return cls(
            [
                MarkdownParser(),
                HtmlParser(),
                PdfParser(),
                DocxParser(),
                TextParser(),
            ]
        )
