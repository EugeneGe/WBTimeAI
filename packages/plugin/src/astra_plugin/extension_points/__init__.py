"""8 个 ExtensionPoint 契约统一导出（W1b 架构裁定 §1.1 / §1.3）。

- 8 个 ``Protocol``（``@runtime_checkable``）+ 各自 ``EXTENSION_POINT_VERSION``；
- :data:`SUPPORTED_EXTENSION_POINTS`：``点 → 核心支持版本`` 映射；
- :func:`is_compatible_point`：插件声明版本与核心支持版本的**同 MAJOR 兼容判定**。

兼容规则（冻结，裁定 §1.1-6）：``"<point>/vN"`` 在**同一 MAJOR（N）**内向后兼容；
声明版本与核心支持版本 **MAJOR 不一致 → 不兼容**（注册时应拒绝，
``DomainError(CONFIGURATION_ERROR)``）。
"""

from __future__ import annotations

import re
from typing import Final

from .audit_sink import EXTENSION_POINT_VERSION as _AUDIT_SINK_VERSION
from .audit_sink import AuditSink
from .auth_provider import EXTENSION_POINT_VERSION as _AUTH_PROVIDER_VERSION
from .auth_provider import AuthProvider
from .connector import EXTENSION_POINT_VERSION as _CONNECTOR_VERSION
from .connector import Connector
from .model_gateway import EXTENSION_POINT_VERSION as _MODEL_GATEWAY_VERSION
from .model_gateway import ModelGateway
from .model_provider import EXTENSION_POINT_VERSION as _MODEL_PROVIDER_VERSION
from .model_provider import ModelProviderFactory, register_provider_factory
from .policy_engine import EXTENSION_POINT_VERSION as _POLICY_ENGINE_VERSION
from .policy_engine import PolicyEngine
from .secret_provider import EXTENSION_POINT_VERSION as _SECRET_PROVIDER_VERSION
from .secret_provider import SecretProvider
from .ui_extension import EXTENSION_POINT_VERSION as _UI_EXTENSION_VERSION
from .ui_extension import UIExtension

__all__ = [
    "AuthProvider",
    "PolicyEngine",
    "AuditSink",
    "SecretProvider",
    "ModelGateway",
    "ModelProviderFactory",
    "Connector",
    "UIExtension",
    "register_provider_factory",
    "SUPPORTED_EXTENSION_POINTS",
    "is_compatible_point",
]

#: 核心支持的扩展点版本映射（点 → ``"<point>/vN"``；首个冻结版本均为 ``v1``）。
SUPPORTED_EXTENSION_POINTS: Final[dict[str, str]] = {
    "auth_provider": _AUTH_PROVIDER_VERSION,
    "policy_engine": _POLICY_ENGINE_VERSION,
    "audit_sink": _AUDIT_SINK_VERSION,
    "secret_provider": _SECRET_PROVIDER_VERSION,
    "model_gateway": _MODEL_GATEWAY_VERSION,
    "model_provider": _MODEL_PROVIDER_VERSION,
    "connector": _CONNECTOR_VERSION,
    "ui_extension": _UI_EXTENSION_VERSION,
}

_VERSION_RE = re.compile(r"^(?P<point>[a-z_]+)/v(?P<major>\d+)$")


def _parse_version(declared: str) -> tuple[str, int] | None:
    """解析 ``"<point>/vN"``；非法格式返回 ``None``。"""
    match = _VERSION_RE.match(declared)
    if match is None:
        return None
    return match.group("point"), int(match.group("major"))


def is_compatible_point(point: str, declared: str) -> bool:
    """判定 ``declared`` 版本与核心支持的 ``point`` 版本是否兼容（同 MAJOR）。

    Args:
        point: 扩展点键（如 ``"auth_provider"``）。
        declared: 插件声明版本（如 ``"auth_provider/v1"``）。

    Returns:
        ``True`` 表示同 MAJOR 兼容；否则 ``False``（含点未知 / 格式非法 /
        MAJOR 不一致）。
    """
    supported = SUPPORTED_EXTENSION_POINTS.get(point)
    if supported is None:
        return False
    parsed_declared = _parse_version(declared)
    parsed_supported = _parse_version(supported)
    if parsed_declared is None or parsed_supported is None:
        return False
    declared_point, declared_major = parsed_declared
    supported_point, supported_major = parsed_supported
    return declared_point == supported_point == point and declared_major == supported_major
