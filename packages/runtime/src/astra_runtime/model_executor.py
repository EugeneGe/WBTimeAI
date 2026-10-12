"""``ModelExecutor``（经 ``ModelRouter`` → ``ModelProvider.chat()``；设计 §2.3 / §2.7）。

Runtime **不绑定任何模型 SDK**（设计 §2.8）：仅消费 :class:`~astra_model.ModelProvider`
抽象接口与 :class:`~astra_model.ModelRouter` 显式路由。

工具调用解析：Phase 1 采用「模型输出文本内 JSON 结构」约定——若 assistant 文本为
``{"tool_calls": [{"name": ..., "arguments": {...}}, ...]}`` 则解析为工具调用请求。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from astra_domain.constants import DEFAULT_MODEL_TIMEOUT_MS
from astra_model import ChatMessage, ChatResult, ModelRouter

__all__ = ["ToolCallRequest", "ModelExecutor"]


@dataclass
class ToolCallRequest:
    """一次工具调用请求（模型产出）。"""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


class ModelExecutor:
    """模型执行器（显式路由 → Provider.chat）。"""

    def __init__(
        self, *, model_router: ModelRouter, timeout_ms: int = DEFAULT_MODEL_TIMEOUT_MS
    ) -> None:
        self._router = model_router
        self._timeout_ms = timeout_ms

    @property
    def timeout_ms(self) -> int:
        """单次模型调用超时（毫秒）。"""
        return self._timeout_ms

    def complete(
        self,
        model_config: Any,
        messages: list[ChatMessage],
        *,
        tenant_id: str | None = None,
        run_id: str | None = None,
        **options: Any,
    ) -> ChatResult:
        """执行一次对话补全（经显式路由解析 Provider + 模型 + 参数）。

        M1 · 加性扩展（向后兼容，非改签名）：``tenant_id`` / ``run_id`` 作为**可选关键字**
        形参，**只**透传给 :meth:`ModelRouter.resolve` 供执行期「原型 + 租户 endpoint + 解密
        凭证」合流；🔴 **绝不**混入 provider 的 ``params``（否则会被当作采样参数发出去）。
        ``tenant_id`` 缺省（``None``）→ 与 Phase 1 行为逐字节一致。

        Args:
            model_config: ``agent_version.model_config``（或等价字典）。
            messages: 已组装的对话消息。
            tenant_id: 租户标识（可选；缺省 ＝ Phase 1 行为，不绑定）。
            run_id: 关联 Run 标识（可选；透传绑定 / 审计）。
            **options: 采样参数（覆盖 ``resolved.params``）。

        Raises:
            DomainError: ``model_config`` 缺失 / 非法、Provider 未注册、或执行期绑定失败
                （``CONFIGURATION_ERROR``，由 :class:`ModelRouter` 抛出）。
        """
        resolved = self._router.resolve(
            model_config,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        params: dict[str, Any] = dict(resolved.params)
        params.update(options)
        return resolved.provider.chat(messages, **params)

    @staticmethod
    def parse_tool_calls(content: str) -> list[ToolCallRequest]:
        """从 assistant 文本解析工具调用请求（无则返回空列表）。"""
        if not content:
            return []
        text = content.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return []
        if not isinstance(payload, dict):
            return []
        raw_calls = payload.get("tool_calls")
        if not isinstance(raw_calls, list):
            return []
        requests: list[ToolCallRequest] = []
        for item in raw_calls:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            arguments = item.get("arguments")
            requests.append(
                ToolCallRequest(
                    name=str(name),
                    arguments=dict(arguments) if isinstance(arguments, dict) else {},
                )
            )
        return requests
