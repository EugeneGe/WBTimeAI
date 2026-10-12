"""远程 API 客户端与**受保护凭据存储**（R4 / T2-62；U-P2-41）。

CLI 经 `astra remote ...` / `astra project clone` 控制**服务端**执行——**不**在本地启动
项目 Build / Test / Agent。

🔴 **Token 纪律（硬性）**：访问令牌**禁止**作为命令行参数传入（会进 Shell 历史 / `ps`），
   仅取自**环境变量**（``ASTRA_REMOTE_TOKEN``）或本机**受保护凭据存储**
   （``~/.astra-ai/credentials/remote.json``，``0600``）；令牌**不**写入日志 / 异常文本。
   `astra remote login` 支持经 **stdin** 写入令牌（同样不进 argv）。

🔴 **契约**：路径为服务端冻结面——Apply / Push **必须**命中
   ``POST /tasks/{id}/apply`` · ``/push``（**禁止** `/tasks/{id}/diff/apply`）。

传输层可注入（``transport``）——便于测试经**进程内**适配器直连 ASGI 应用。
"""

from __future__ import annotations

import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_SERVER",
    "API_PREFIX",
    "TOKEN_ENV",
    "SERVER_ENV",
    "CREDENTIAL_DIR",
    "CREDENTIAL_FILE",
    "RemoteAPIError",
    "RemoteCredential",
    "RemoteAPIClient",
    "resolve_server",
    "load_credential",
    "save_credential",
    "resolve_token",
]

#: 默认服务端地址（本地模式）。
DEFAULT_SERVER = "http://127.0.0.1:8080"

#: API 前缀（对齐后端统一前缀）。
API_PREFIX = "/api/v1"

#: 令牌环境变量名（**不进 argv**）。
TOKEN_ENV = "ASTRA_REMOTE_TOKEN"

#: 服务端地址环境变量名。
SERVER_ENV = "ASTRA_REMOTE_SERVER"

#: 凭据根目录（本地模式）。
CREDENTIAL_DIR = "~/.astra-ai/credentials"

#: 凭据文件名。
CREDENTIAL_FILE = "remote.json"


class RemoteAPIError(RuntimeError):
    """远程 API 调用错误（**不含**令牌 / 宿主路径）。

    Attributes:
        status: HTTP 状态码（网络错误 → ``None``）。
        code: 统一响应壳错误码（如有）。
    """

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class RemoteCredential:
    """受保护凭据（服务端地址 + 访问令牌）。

    Attributes:
        server: 服务端地址。
        access_token: 访问令牌（``repr`` 隐藏）。
    """

    server: str
    access_token: str


def _credentials_path() -> Path:
    """返回凭据文件路径（``~`` 展开）。"""
    return Path(CREDENTIAL_DIR).expanduser() / CREDENTIAL_FILE


def resolve_server(explicit: str | None = None) -> str:
    """解析服务端地址：``--server`` > ``ASTRA_REMOTE_SERVER`` > 默认。"""
    if explicit:
        return explicit.rstrip("/")
    env = os.environ.get(SERVER_ENV)
    if env:
        return env.rstrip("/")
    return DEFAULT_SERVER


def load_credential() -> RemoteCredential | None:
    """读取受保护凭据文件（不存在 / 损坏 → ``None``）。"""
    path = _credentials_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    server = str(payload.get("server") or "").strip()
    token = str(payload.get("access_token") or "").strip()
    if not token:
        return None
    return RemoteCredential(server=server or DEFAULT_SERVER, access_token=token)


def resolve_token(explicit: str | None = None) -> str:
    """解析访问令牌（**严禁**来自 argv：``explicit`` 仅供内部注入）。

    优先级：显式（内部） > ``ASTRA_REMOTE_TOKEN`` > 受保护凭据存储。

    Raises:
        RemoteAPIError: 无可用令牌（``CONFIGURATION_ERROR``；**不**回显任何令牌）。
    """
    if explicit:
        return explicit
    env = os.environ.get(TOKEN_ENV)
    if env:
        return env.strip()
    credential = load_credential()
    if credential is not None:
        return credential.access_token
    raise RemoteAPIError(
        "未配置远程访问令牌：请设置 ASTRA_REMOTE_TOKEN 或运行 `astra remote login`",
        code="CONFIGURATION_ERROR",
    )


def save_credential(server: str, access_token: str) -> Path:
    """把令牌写入**受保护**凭据文件（``0600``；目录 ``0700``）。

    Args:
        server: 服务端地址。
        access_token: 访问令牌（写入后**不**回显）。

    Returns:
        凭据文件路径。
    """
    directory = Path(CREDENTIAL_DIR).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    except OSError:  # pragma: no cover - 平台差异（如 Windows）
        pass
    path = directory / CREDENTIAL_FILE
    path.write_text(
        json.dumps(
            {"server": server.rstrip("/"), "access_token": access_token}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # pragma: no cover - 平台差异（如 Windows）
        pass
    return path


def _urllib_transport(
    server: str,
) -> Any:
    """构造基于 ``urllib`` 的默认传输。

    传输签名：``(method, path, headers, body) -> (status, headers, body)``。
    """

    def transport(
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> tuple[int, Mapping[str, str], bytes]:
        url = f"{server}{path}"
        request = urllib.request.Request(url, data=body, method=method)
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request) as response:  # noqa: S310 - 受控服务端地址
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:  # 4xx / 5xx 仍返回体（统一响应壳）
            return exc.code, dict(exc.headers), exc.read()

    return transport


class RemoteAPIClient:
    """远程 API 客户端（统一响应壳**解壳**；令牌经 ``Authorization: Bearer``）。

    Attributes:
        server: 服务端地址。
    """

    def __init__(
        self,
        server: str,
        access_token: str,
        *,
        transport: Any | None = None,
    ) -> None:
        """构造（``transport`` 可注入，便于测试经进程内适配器直连 ASGI 应用）。"""
        self.server = server.rstrip("/")
        self._token = access_token
        self._transport = transport or _urllib_transport(self.server)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """发起请求并**解壳**返回 ``data``（失败 → :class:`RemoteAPIError`）。

        Args:
            method: HTTP 方法。
            path: 相对路径（如 ``/tasks/t1/apply``）。
            json_body: JSON 请求体（``None`` → 无体）。
            params: 查询参数（值为 ``None`` 者省略）。

        Returns:
            统一响应壳的 ``data``（无壳时返回原体）。

        Raises:
            RemoteAPIError: 非 2xx（含统一响应壳 ``code`` / ``message``）。
        """
        url_path = f"{API_PREFIX}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url_path = f"{url_path}?{urllib.parse.urlencode(clean)}"
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, _resp_headers, raw = self._transport(method, url_path, headers, body)
        payload: Any = None
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = None
        if not 200 <= status < 300:
            code = payload.get("code") if isinstance(payload, dict) else None
            message = payload.get("message") if isinstance(payload, dict) else None
            raise RemoteAPIError(
                str(message or f"HTTP {status}"),
                status=status,
                code=str(code) if code else None,
            )
        if isinstance(payload, dict) and "data" in payload and "code" in payload:
            return payload["data"]
        return payload
