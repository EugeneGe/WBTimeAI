"""脚本化 :class:`~astra_model.ModelProvider` 替身（W8 / T1-36）。

用途：为 Phase 1 全链路 e2e 提供**确定性、可复现**的模型响应序列——`chat` / `stream`
按**预设脚本**逐次产出内容，用尽后**重复最后一条**（与
``tests/unit/runtime_stubs.StubModelProvider`` 语义一致，便于驱动多轮 ReAct 循环）。

与 ``astra_model.stub.StubModelProvider``（纯回显）的区别：本替身接受**脚本序列**，
因此可编排「先产工具调用、再产最终答复」的多轮交互，使 SSE 帧序列可逐帧断言。

脚本条目约定（与 Runtime ``ModelExecutor.parse_tool_calls`` 对齐）：

- 普通文本 → 视为**最终答复**（结束 ReAct 循环）；
- ``{"tool_calls": [{"name": ..., "arguments": {...}}, ...]}`` JSON 串 → 触发**工具调用**。
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

from astra_model import ChatResult, TokenCount

__all__ = ["ScriptedModelProvider", "tool_call_content"]


def tool_call_content(name: str, arguments: dict[str, Any] | None = None) -> str:
    """构造模型「工具调用」文本（与 Runtime 解析约定一致的 JSON 结构）。

    Args:
        name: 目标工具名。
        arguments: 工具入参（缺省为空 dict）。

    Returns:
        形如 ``{"tool_calls": [{"name": ..., "arguments": {...}}]}`` 的 JSON 字符串。
    """
    return json.dumps({"tool_calls": [{"name": name, "arguments": dict(arguments or {})}]})


class ScriptedModelProvider:
    """确定性脚本 Provider：按序返回脚本内容，用尽后重复末条。

    Attributes:
        calls: 已消耗的脚本条目数（``chat`` / ``stream`` 合并计数）。
        seen_messages: 每次调用收到的消息快照（供断言上下文组装）。
    """

    def __init__(
        self,
        script: Sequence[str],
        *,
        model: str = "scripted-1",
        name: str = "scripted",
    ) -> None:
        self.name = name
        self._script: list[str] = [str(item) for item in script]
        self._model = model
        self.calls = 0
        self.seen_messages: list[list[Any]] = []

    # -- ModelProvider 契约 -------------------------------------------------

    def chat(self, messages: Sequence[Any], **options: Any) -> ChatResult:
        """返回脚本中的下一条内容（用尽后重复末条）。"""
        self.seen_messages.append(list(messages))
        return ChatResult(content=self._next(), model=self._model, finish_reason="stop")

    def stream(self, messages: Sequence[Any], **options: Any) -> Iterator[str]:
        """流式：整体产出脚本中的下一条内容（确定性、单块）。"""
        yield self._next()

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Any]:
        """返回空嵌入（e2e 不涉及向量检索）。"""
        return []

    def count_tokens(self, text: str, **options: Any) -> TokenCount:
        """粗糙 token 估算（与既有桩件一致）。"""
        return TokenCount(count=max(1, len(text) // 4), model=self._model)

    # -- 内部 ---------------------------------------------------------------

    def _next(self) -> str:
        """取脚本中的下一条；脚本为空时返回空串。"""
        if not self._script:
            self.calls += 1
            return ""
        index = min(self.calls, len(self._script) - 1)
        self.calls += 1
        return self._script[index]
