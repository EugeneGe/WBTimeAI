"""MCP 授权（凭据 → 请求头桥接；设计 §2.4；W2 / T2-11；裁定 R2 / C-07）。

:class:`MCPAuthorization` 把 Server 的凭据（``mcp_server.credential_id``，**仅引用**）经
**注入的** :class:`~astra_domain.CredentialDecoder` 解密为**内存明文**，装配为 HTTP
``Authorization`` 头。

🔴 **不 import ``astra_security``**（R2）：明文唯一经**域 Protocol** ``CredentialDecoder``
   取得，adapter 由 ``astra_security`` 提供、**组合根注入**（F16 先例）。
🔴 **明文仅内存**：``Authorization`` 头**绝不落库 / 落日志 / 回显**（C-07）；本模块**不打日志**。
"""

from __future__ import annotations

from collections.abc import Mapping

from astra_domain import CredentialDecoder

from .domain import MCPServer

__all__ = ["MCPAuthorization"]


class MCPAuthorization:
    """MCP 凭据桥接（凭据 → ``Authorization`` 请求头；明文仅内存）。

    Args:
        credential_decoder: 凭证解码领域 Protocol（DI 注入；adapter 由 ``astra_security`` 提供）。
        scheme: 鉴权 scheme（默认 ``Bearer``）。
    """

    def __init__(self, *, credential_decoder: CredentialDecoder, scheme: str = "Bearer") -> None:
        self._decoder = credential_decoder
        self._scheme = scheme

    def headers_for(self, server: MCPServer) -> dict[str, str]:
        """为 Server 构造鉴权请求头（无凭据 → 空 dict）。

        Args:
            server: 目标 MCP Server（``credential_id`` 为**引用**）。

        Returns:
            ``{"Authorization": "<scheme> <明文>"}``；``credential_id`` 为空时返回 ``{}``。

        Note:
            ``credential_decoder.decrypt`` 的返回值**仅用于内存中的请求头**，
            **绝不**记录到日志或持久化（C-07）。
        """
        if not server.credential_id:
            return {}
        secret = self._decoder.decrypt(server.credential_id)
        if not secret:
            return {}
        return {"Authorization": f"{self._scheme} {secret}"}

    def apply(self, server: MCPServer, headers: Mapping[str, str] | None = None) -> dict[str, str]:
        """在既有请求头上追加鉴权头（**不覆盖**调用方显式提供的 ``Authorization``）。"""
        merged = dict(headers or {})
        if any(key.lower() == "authorization" for key in merged):
            return merged
        merged.update(self.headers_for(server))
        return merged
