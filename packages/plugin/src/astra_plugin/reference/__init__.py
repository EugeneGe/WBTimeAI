"""``astra_plugin.reference`` —— 8 个 ExtensionPoint 的开源**参考实现**。

🔴 **零三方依赖 / 零 ``astra_security`` / 零 ORM**（裁定 §1.3 / R2）。
   非 ``Noop`` 的参考实现均标注 **NON-SECURE / 仅契约演示**；生产实现归 Phase 3–4。
"""

from __future__ import annotations

from .audit_sink import FallbackAuditSink, NoopAuditSink
from .auth_provider import AllowAllAuthProvider
from .connector import NoopConnector
from .model_gateway import NoopModelGateway
from .model_provider import EchoModelProviderFactory
from .policy_engine import NoopPolicyEngine
from .secret_provider import LocalSecretProvider
from .ui_extension import EmptyUIExtension

__all__ = [
    "AllowAllAuthProvider",
    "NoopPolicyEngine",
    "NoopAuditSink",
    "FallbackAuditSink",
    "LocalSecretProvider",
    "NoopModelGateway",
    "EchoModelProviderFactory",
    "NoopConnector",
    "EmptyUIExtension",
]
