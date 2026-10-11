"""``model_gateway`` 参考实现：:class:`NoopModelGateway`（取首个候选）。

🔴 **NON-SECURE**：不做任何策略选路——**仅用于契约演示**；真实网关归 Phase 3–4。
"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode
from astra_domain import ExtensionContext, ModelRef
from astra_model import ChatMessage, ChatResult

__all__ = ["NoopModelGateway"]


class NoopModelGateway:
    """无策略网关：显式取候选列表首个（**NON-SECURE / 仅契约演示**）。"""

    def route(
        self, request: ChatMessage, candidates: list[ModelRef], ctx: ExtensionContext
    ) -> ModelRef:
        """返回首个候选；候选为空抛 ``DomainError(CONFIGURATION_ERROR)``。"""
        if not candidates:
            raise DomainError(
                "无可用模型候选（NoopModelGateway）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"candidates": 0},
            )
        return candidates[0]

    def on_result(self, ref: ModelRef, result: ChatResult | Exception) -> None:
        """空回调。"""
        return None
