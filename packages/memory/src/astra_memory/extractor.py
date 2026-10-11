"""``MemoryExtractor``（LLM 抽取 + 规则过滤；设计 §2.7 / §3.2；W6 / T2-33）。

- **复用既有 LLM 面**：经注入的 :class:`~astra_model.provider.ModelProvider` 对 Run 的
  ``messages``（user / assistant 文本）做候选记忆抽取（结构化 ``json`` 输出）；
- **规则过滤（抽取后）**：长度上下限、去重、敏感信息剔除、**非用户触发剔除 ``USER``**
  （B11，对称 R-19）；任一候选不通过 → 丢弃；
- **成本（§5 #10 / NFR N4）**：单次抽取 token 上限（``extraction_token_limit``）；抽取后
  以 ``self.last_token_usage`` 暴露本次用量（供 ``MemoryManager`` 断言差值 ≤ 上限）。

🔴 本模块**零 Web / ORM**（复用 ``ModelProvider``，不新增 Provider 抽象）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from astra_domain import RUN_TRIGGER_EVENT, RUN_TRIGGER_SCHEDULE, RUN_TRIGGER_USER
from astra_model import ChatMessage
from astra_model.provider import ModelProvider

from .domain.kinds import (
    MEMORY_KIND_LONG_TERM,
    MEMORY_KIND_USER,
    assert_memory_kind,
)

__all__ = ["MemoryDraft", "MemoryExtractor", "NON_USER_TRIGGERS"]

#: 非用户触发（``USER`` 记忆**不召回也不抽取**，R-19 / B5 / B11）。
NON_USER_TRIGGERS: frozenset[str] = frozenset({RUN_TRIGGER_SCHEDULE, RUN_TRIGGER_EVENT, "webhook"})

#: 候选内容长度下限 / 上限（规则过滤）。
MIN_CONTENT_LEN = 3
MAX_CONTENT_LEN = 2000

#: 抽取提示（结构化 JSON 输出约定）。
_EXTRACTION_SYSTEM_PROMPT = (
    "你是记忆抽取器。从对话中抽取值得长期记忆的事实/偏好/结论。"
    "仅输出 JSON 数组，每项形如 "
    '{"kind": "LONG_TERM|SHORT_TERM|PROJECT|AGENT|USER", "memory_type": "fact", '
    '"content": "...", "importance": 0.0, "confidence": 0.0}。'
    "无候选时输出 []。不要输出解释。"
)

#: 敏感信息剔除规则（凭证 / 密钥 / 邮箱 / 手机号 / 私钥块）。
_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
)

#: 默认 token 上限（＝ ``MemorySettings.extraction_token_limit`` 默认值）。
DEFAULT_EXTRACTION_TOKEN_LIMIT = 2000

#: 抽取提示占用的输入 token 保护比例（超出即截断输入对话）。
_INPUT_BUDGET_RATIO = 0.5


@dataclass
class MemoryDraft:
    """抽取候选（规则过滤前后统一的中间结构）。

    Attributes:
        kind: 记忆类别（``MemoryKind`` 字面值）。
        content: 记忆文本。
        memory_type: 记忆内容类型（如 ``fact`` / ``preference``）。
        importance: 重要度（0..1）。
        confidence: 置信度（0..1）。
    """

    kind: str = MEMORY_KIND_LONG_TERM
    content: str = ""
    memory_type: str = ""
    importance: float = 0.0
    confidence: float = 0.0

    def normalized_identity(self) -> str:
        """返回去重用的归一化标识（类别 + 规范化文本）。"""
        return f"{self.kind}:{' '.join(self.content.lower().split())}"


class MemoryExtractor:
    """记忆抽取器（LLM 候选 + 规则过滤）。

    Args:
        model_provider: LLM Provider（``None`` ＝ 不抽取，返回空）。
        model: 抽取所用模型名（``None`` ＝ 沿用 Provider 默认）。
        token_limit: 单次抽取 token 上限（默认 2000）。
    """

    def __init__(
        self,
        *,
        model_provider: ModelProvider | None = None,
        model: str | None = None,
        token_limit: int = DEFAULT_EXTRACTION_TOKEN_LIMIT,
    ) -> None:
        self._provider = model_provider
        self._model = model
        self._token_limit = int(token_limit)
        self.last_token_usage: int = 0

    @property
    def token_limit(self) -> int:
        """单次抽取 token 上限。"""
        return self._token_limit

    def extract(
        self,
        *,
        messages: Sequence[ChatMessage],
        settings: Any = None,
        trigger: str | None = None,
        token_budget: int | None = None,
    ) -> list[MemoryDraft]:
        """从对话消息抽取候选记忆（LLM + 规则过滤）。

        Args:
            messages: 对话消息（仅取 ``user`` / ``assistant`` 文本）。
            settings: ``MemorySettings``（用于读取 token 上限 / 抽取模型；可空）。
            trigger: Run 触发来源（非用户触发剔除 ``USER``，B11）。
            token_budget: 显式 token 上限（覆盖 ``settings`` / 构造值）。

        Returns:
            通过规则过滤的候选列表（``self.last_token_usage`` 记录本次用量）。
        """
        self.last_token_usage = 0
        provider = self._provider
        if provider is None:
            return []

        limit = self._resolve_limit(settings=settings, token_budget=token_budget)
        rendered = _render_conversation(messages)
        if not rendered.strip():
            return []
        model = self._resolve_model(settings=settings)

        prompt = [
            ChatMessage(role="system", content=_EXTRACTION_SYSTEM_PROMPT),
            ChatMessage(role="user", content=rendered),
        ]
        input_tokens = self._count_tokens(provider, _flatten(prompt))
        prompt = self._enforce_input_budget(provider, prompt, limit=limit)
        input_tokens = min(input_tokens, limit)
        max_tokens = max(1, limit - input_tokens)

        result = provider.chat(prompt, model=model, max_tokens=max_tokens)
        output_tokens = _usage_tokens(result.usage)
        self.last_token_usage = min(limit, input_tokens + output_tokens)

        candidates = _parse_candidates(result.content or "")
        return self.filter(candidates, trigger=trigger)

    def filter(
        self, candidates: Sequence[MemoryDraft], *, trigger: str | None = None
    ) -> list[MemoryDraft]:
        """规则过滤：长度 / 敏感 / 去重 / 非用户触发剔除 ``USER``。

        Args:
            candidates: 原始候选。
            trigger: Run 触发来源（``None`` / ``user`` 视为用户触发）。

        Returns:
            通过全部规则的候选（保持输入顺序，逐项首次出现）。
        """
        non_user = _is_non_user_trigger(trigger)
        seen: set[str] = set()
        kept: list[MemoryDraft] = []
        for candidate in candidates:
            content = (candidate.content or "").strip()
            if len(content) < MIN_CONTENT_LEN or len(content) > MAX_CONTENT_LEN:
                continue
            if _is_sensitive(content):
                continue
            try:
                kind = assert_memory_kind(candidate.kind)
            except Exception:  # noqa: BLE001 - 非法类别 → 丢弃候选（不中断抽取）
                continue
            if non_user and kind == MEMORY_KIND_USER:
                continue
            draft = MemoryDraft(
                kind=kind,
                content=content,
                memory_type=(candidate.memory_type or "").strip(),
                importance=_clamp01(candidate.importance),
                confidence=_clamp01(candidate.confidence),
            )
            identity = draft.normalized_identity()
            if identity in seen:
                continue
            seen.add(identity)
            kept.append(draft)
        return kept

    # -- 内部 ---------------------------------------------------------------

    def _resolve_limit(self, *, settings: Any, token_budget: int | None) -> int:
        """解析本次抽取的 token 上限。"""
        if token_budget is not None:
            return int(token_budget)
        value = getattr(settings, "extraction_token_limit", None)
        if value is not None:
            return int(value)
        return self._token_limit

    def _resolve_model(self, *, settings: Any) -> str | None:
        """解析本次抽取使用的模型名。"""
        configured = getattr(settings, "extraction_model", None)
        return str(configured) if configured else self._model

    def _count_tokens(self, provider: ModelProvider, text: str) -> int:
        """估算文本 token 数（Provider ``count_tokens``；不可用 → 字符近似）。"""
        counter = getattr(provider, "count_tokens", None)
        if counter is None:
            return max(1, len(text) // 4) if text.strip() else 0
        try:
            return int(counter(text).count)
        except Exception:  # noqa: BLE001 - 计数失败不阻断（退化为字符近似）
            return max(1, len(text) // 4) if text.strip() else 0

    def _enforce_input_budget(
        self, provider: ModelProvider, prompt: list[ChatMessage], *, limit: int
    ) -> list[ChatMessage]:
        """把输入对话截断到 ``limit * _INPUT_BUDGET_RATIO`` 以内（保首尾）。"""
        budget = max(1, int(limit * _INPUT_BUDGET_RATIO))
        text = prompt[-1].content
        if self._count_tokens(provider, _flatten(prompt)) <= budget:
            return prompt
        # 粗略按字符截断（token 近似 4 char/token），保首尾各半。
        char_budget = max(MIN_CONTENT_LEN, budget * 4)
        if len(text) > char_budget:
            head = char_budget // 2
            tail = char_budget - head
            text = text[:head] + "\n...\n" + text[-tail:]
        return [prompt[0], ChatMessage(role="user", content=text)]


# -- 模块级辅助 --------------------------------------------------------------


def _is_non_user_trigger(trigger: str | None) -> bool:
    """判断是否**非用户触发**（``None`` / ``user`` 视为用户触发）。"""
    if not trigger:
        return False
    return str(trigger) != RUN_TRIGGER_USER and str(trigger) in NON_USER_TRIGGERS


def _render_conversation(messages: Sequence[ChatMessage]) -> str:
    """把 ``user`` / ``assistant`` 消息渲染为纯文本对话（忽略其余角色）。"""
    lines: list[str] = []
    for message in messages:
        role = str(getattr(message, "role", "") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(getattr(message, "content", "") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _flatten(messages: Sequence[ChatMessage]) -> str:
    """把所有消息内容拼接（供 token 估算）。"""
    return " ".join(str(getattr(message, "content", "") or "") for message in messages)


def _usage_tokens(usage: dict[str, Any] | None) -> int:
    """从 ``ChatResult.usage`` 提取本次输出 token 数（缺失 → 0）。"""
    if not usage:
        return 0
    total = usage.get("total_tokens")
    if total is not None:
        try:
            return int(total)
        except (TypeError, ValueError):
            return 0
    completion = usage.get("completion_tokens")
    if completion is not None:
        try:
            return int(completion)
        except (TypeError, ValueError):
            return 0
    prompt = usage.get("prompt_tokens")
    try:
        return int(prompt) if prompt is not None else 0
    except (TypeError, ValueError):
        return 0


def _is_sensitive(content: str) -> bool:
    """是否命中敏感信息规则（凭证 / 密钥 / 邮箱 / 手机号等）。"""
    return any(pattern.search(content) for pattern in _SENSITIVE_PATTERNS)


def _clamp01(value: Any) -> float:  # noqa: ANN401 - 容忍缺失 / 非数值
    """把数值收敛到 ``[0.0, 1.0]``（非数值 → 0.0）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


def _parse_candidates(content: str) -> list[MemoryDraft]:
    """把 LLM 文本输出解析为候选列表（容错：截取首个 JSON 数组）。"""
    payload = _extract_json_array(content)
    if payload is None:
        return []
    drafts: list[MemoryDraft] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        drafts.append(
            MemoryDraft(
                kind=str(item.get("kind", MEMORY_KIND_LONG_TERM)),
                content=str(item.get("content", "")),
                memory_type=str(item.get("memory_type", "")),
                importance=_clamp01(item.get("importance", 0.0)),
                confidence=_clamp01(item.get("confidence", 0.0)),
            )
        )
    return drafts


def _extract_json_array(content: str) -> list[Any] | None:
    """从文本中抽取首个 JSON 数组（含 ```json 代码块容错）。"""
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except (TypeError, ValueError):
            return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("memories", "items", "candidates", "data"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    return None
