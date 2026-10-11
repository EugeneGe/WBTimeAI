"""模型 Provider DTO（ChatMessage / ChatResult / Embedding / TokenCount / ModelInfo）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["ChatMessage", "ChatResult", "Embedding", "TokenCount", "ModelInfo"]

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ChatMessage:
    """对话消息。

    Attributes:
        role: 角色（``system`` / ``user`` / ``assistant`` / ``tool``）。
        content: 文本内容。
        name: 可选发送者名。
        metadata: 附加元数据。
    """

    role: Role
    content: str
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResult:
    """对话结果。

    Attributes:
        content: 生成文本。
        model: 模型名。
        finish_reason: 结束原因（如 ``stop`` / ``length``）。
        usage: 用量（token 统计等）。
    """

    content: str
    model: str = ""
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class Embedding:
    """嵌入向量。

    Attributes:
        vector: 向量。
        model: 模型名。
        index: 在批次中的序号。
    """

    vector: list[float]
    model: str = ""
    index: int = 0


@dataclass
class TokenCount:
    """Token 计数。

    Attributes:
        count: token 数。
        model: 模型名。
    """

    count: int
    model: str = ""


@dataclass
class ModelInfo:
    """模型信息。

    Attributes:
        name: 模型名。
        provider: Provider 名。
        context_window: 上下文窗口大小。
        metadata: 附加元数据。
    """

    name: str
    provider: str = ""
    context_window: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
