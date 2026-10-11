"""``ModelProvider`` Protocol（``chat`` / ``stream`` / ``embeddings`` / ``count_tokens``）。

目的（设计 §2.8）：**Agent Runtime 从第一天起不绑定任何模型 SDK**。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, Protocol, runtime_checkable

from .types import ChatMessage, ChatResult, Embedding, TokenCount

__all__ = ["ModelProvider"]


@runtime_checkable
class ModelProvider(Protocol):
    """模型 Provider 接口。"""

    def chat(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        """执行一次对话补全。"""
        ...

    def stream(self, messages: Sequence[ChatMessage], **options: Any) -> Iterator[str]:
        """流式会话：逐块产出文本。"""
        ...

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Embedding]:
        """计算文本嵌入。"""
        ...

    def count_tokens(self, text: str, **options: Any) -> TokenCount:
        """统计文本 token 数。"""
        ...
