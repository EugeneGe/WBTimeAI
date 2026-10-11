"""``StubModelProvider``（确定性回显，供契约测试 / Phase 0 默认）。"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from typing import Any

from .types import ChatMessage, ChatResult, Embedding, TokenCount

__all__ = ["StubModelProvider"]


class StubModelProvider:
    """确定性模型 Provider。

    行为确定、无外部依赖：

    - ``chat``：回显最后一条用户消息（前缀 ``[stub]``）；
    - ``stream``：按空白切分逐块产出；
    - ``embeddings``：基于 SHA-256 的确定性伪向量（维度可配）；
    - ``count_tokens``：按空白切分计数（``max(1, len(split))``）。
    """

    def __init__(self, *, name: str = "stub", dimension: int = 8) -> None:
        self.name = name
        self.dimension = dimension

    def chat(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        """回显最后一条消息。"""
        last = messages[-1].content if messages else ""
        return ChatResult(
            content=f"[stub] {last}",
            model=self.name,
            finish_reason="stop",
            usage={"prompt_tokens": self.count_tokens(_flatten(messages)).count},
        )

    def stream(self, messages: Sequence[ChatMessage], **options: Any) -> Iterator[str]:
        """按空白切分逐块产出回显内容。"""
        text = self.chat(messages, **options).content
        for token in text.split(" "):
            yield token + " "

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Embedding]:
        """基于 SHA-256 的确定性伪向量。"""
        return [
            Embedding(vector=self._vector(text), model=self.name, index=index)
            for index, text in enumerate(texts)
        ]

    def count_tokens(self, text: str, **options: Any) -> TokenCount:
        """粗略 token 计数（按空白切分）。"""
        stripped = text.strip()
        count = len(stripped.split()) if stripped else 0
        return TokenCount(count=count, model=self.name)

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dimension)]


def _flatten(messages: Sequence[ChatMessage]) -> str:
    return " ".join(message.content for message in messages)
