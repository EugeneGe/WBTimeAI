"""``connector`` 参考实现：:class:`NoopConnector`（动作空、执行拒绝）。

🔴 **NON-SECURE**：不执行任何外部动作——**仅用于契约演示**；真实 Connector 归 Phase 3–4。
"""

from __future__ import annotations

from typing import Any

from astra_domain import (
    AuthorizeParams,
    ConnectorActionSpec,
    ConnectorHealth,
    ConnectorResult,
    CredentialRef,
    ExtensionContext,
)

__all__ = ["NoopConnector"]


class NoopConnector:
    """空 Connector（**NON-SECURE / 仅契约演示**）。"""

    def id(self) -> str:
        """标识 ``noop``。"""
        return "noop"

    def actions(self) -> list[ConnectorActionSpec]:
        """无动作。"""
        return []

    def authorize(self, params: AuthorizeParams, ctx: ExtensionContext) -> CredentialRef:
        """返回占位凭证引用（不含明文）。"""
        return CredentialRef(credential_id="noop")

    def execute(
        self, action: str, params: dict[str, Any], ctx: ExtensionContext
    ) -> ConnectorResult:
        """不执行任何动作，返回失败结果。"""
        return ConnectorResult(ok=False, output=None, error="noop connector 不执行动作")

    def health(self) -> ConnectorHealth:
        """恒健康。"""
        return ConnectorHealth(ok=True, message="noop")
