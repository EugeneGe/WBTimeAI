"""ExtensionPoint ⑤ ``model_gateway``（路由策略）——签名冻结（W1b 裁定 §1.3⑤）。

在 Router **之上**做策略；与 ⑥ ``model_provider`` **正交**。

🔴 设计原文 ``request: ChatRequest`` → **以实测为准**改为
   :class:`astra_model.ChatMessage`（仓库无 ``ChatRequest``，裁定 §1.3⑤ 注 / F10）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from astra_domain import ExtensionContext, ModelRef
from astra_model import ChatMessage, ChatResult

__all__ = ["ModelGateway", "EXTENSION_POINT_VERSION"]

#: 扩展点版本（格式 ``<point>/vN``）。
EXTENSION_POINT_VERSION: str = "model_gateway/v1"


@runtime_checkable
class ModelGateway(Protocol):
    """模型网关扩展点（在候选之上选路 + 结果回调）。"""

    def route(
        self, request: ChatMessage, candidates: list[ModelRef], ctx: ExtensionContext
    ) -> ModelRef:
        """从候选中显式选出一个模型引用。"""
        ...

    def on_result(self, ref: ModelRef, result: ChatResult | Exception) -> None:
        """结果回调（成功或异常），用于观测 / 计数 / 熔断。"""
        ...
