"""ExtensionPoint ⑦ ``connector``（外部系统连接器）——签名冻结（W1b 裁定 §1.3⑦）。

🔴 出网一律走 ``EgressPolicy``（设计 §2.18）；本契约只声明动作与执行接口。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from astra_domain import (
    AuthorizeParams,
    ConnectorActionSpec,
    ConnectorHealth,
    ConnectorResult,
    CredentialRef,
    ExtensionContext,
)

__all__ = ["Connector", "EXTENSION_POINT_VERSION"]

#: 扩展点版本（格式 ``<point>/vN``）。
EXTENSION_POINT_VERSION: str = "connector/v1"


@runtime_checkable
class Connector(Protocol):
    """外部系统 Connector 扩展点。"""

    def id(self) -> str:
        """Connector 唯一标识。"""
        ...

    def actions(self) -> list[ConnectorActionSpec]:
        """声明可执行动作清单。"""
        ...

    def authorize(self, params: AuthorizeParams, ctx: ExtensionContext) -> CredentialRef:
        """授权并返回凭证引用（**不含明文**）。"""
        ...

    def execute(
        self, action: str, params: dict[str, Any], ctx: ExtensionContext
    ) -> ConnectorResult:
        """执行动作（出网须过 ``EgressPolicy``）。"""
        ...

    def health(self) -> ConnectorHealth:
        """报告 Connector 健康状态。"""
        ...
