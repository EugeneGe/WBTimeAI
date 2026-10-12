"""真实 Provider 的 HTTP 公共基类（超时 / 重试钩子 / 错误归一化）。

设计 §2.3.2：每个 Provider 内部封装对应 HTTP；**SDK/HTTP 只在 ``providers/``**。
本模块提供与具体厂商无关的 HTTP 调用、错误归一化（429/5xx/timeout → 可重试）与
粗略 token 计数；具体厂商在子类里做请求 / 响应映射。

🔴 密钥仅在使用时持有，**不落日志**（T1-30 收口）。
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
from astra_core import DomainError, ErrorCode

from ..types import ChatMessage, TokenCount

__all__ = [
    "ProviderError",
    "HttpModelProvider",
    "DEFAULT_TIMEOUT_SECONDS",
    "RETRYABLE_STATUS_CODES",
    "messages_to_dicts",
    "normalize_usage",
]

#: 默认请求超时（秒）。
DEFAULT_TIMEOUT_SECONDS = 60.0

#: 触发可重试标记的 HTTP 状态码（限流 + 服务端错误）。
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class ProviderError(DomainError):
    """Provider 调用错误（跨厂商归一化）。

    Attributes:
        retryable: 是否可重试（429 / 5xx / timeout → ``True``）。
        http_status: 触发错误的 HTTP 状态码（超时等无则为 ``None``）。
    """

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
        data: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = dict(data or {})
        payload["retryable"] = retryable
        if http_status is not None:
            payload["http_status"] = http_status
        super().__init__(message, code=ErrorCode.INTERNAL_ERROR, data=payload)
        self.http_status = http_status
        self.retryable = retryable


def messages_to_dicts(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """把 ``ChatMessage`` 转换为 ``{role, content[, name]}`` 列表。"""
    converted: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.name:
            item["name"] = message.name
        converted.append(item)
    return converted


def normalize_usage(raw: dict[str, Any] | None) -> dict[str, Any]:
    """把厂商用量字段归一化为 ``{prompt_tokens, completion_tokens, total_tokens}``。"""
    if not raw:
        return {}
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    total = raw.get("total_tokens")
    usage: dict[str, Any] = {}
    if prompt is not None:
        usage["prompt_tokens"] = int(prompt)
    if completion is not None:
        usage["completion_tokens"] = int(completion)
    if total is not None:
        usage["total_tokens"] = int(total)
    return usage


class HttpModelProvider:
    """基于 ``httpx`` 的 Provider 公共基类（子类实现厂商请求 / 响应映射）。"""

    #: Provider 名（注册进 ``ModelRegistry`` 的键）。
    provider_name: str = ""
    #: 是否**必须**绑定凭证（API Key）。
    #:
    #: M1：默认 ``True``——本地 / 无密钥 Provider（如 ``OllamaProvider``）置 ``False``，
    #: 以便执行期绑定（``ProviderResolver``）区分「需密钥却未绑 → ``CONFIGURATION_ERROR``」
    #: 与「本就无需密钥 → ``api_key=None``」。
    requires_api_key: bool = True
    #: 能力声明（供契约套件按能力断言）。
    supports_chat: bool = True
    supports_stream: bool = True
    supports_embeddings: bool = True
    #: 默认模型名（调用未显式给定时使用）。
    default_chat_model: str = ""
    default_embedding_model: str = ""

    def __init__(
        self,
        *,
        name: str | None = None,
        base_url: str = "",
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
        max_retries: int = 0,
    ) -> None:
        self.name = name or self.provider_name
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self._extra_headers = dict(extra_headers or {})
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    # -- 执行期绑定（M1：仅内存；明文不落库 / 日志 / 回显） ---------------------

    def with_binding(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> HttpModelProvider:
        """返回一个携带**当次绑定** ``base_url`` / ``api_key`` 的**新实例**（浅拷贝）。

        M1 执行期「原型 + 租户 endpoint + 解密凭证」合流用：``ProviderResolver`` 以注册表
        原型为模板，覆盖租户 ``endpoint`` 与解密后的明文密钥，产出**当次可调用**的具体实例。

        - **不重跑构造**、**不引入工厂反射**：``copy.copy(self)`` 后仅覆盖 ``base_url`` /
          ``_api_key``（``httpx.Client`` 等其余状态按引用共享）。
        - 形参为 ``None`` 时**保持**原值（``base_url=None`` ＝ 沿用原型默认端点；
          ``api_key=None`` ＝ 不注入密钥，如 ``requires_api_key=False`` 的本地 Provider）。
        - 🔴 **明文仅内存**：``api_key`` 只存于新实例的 ``_api_key``，**不落库 / 不落日志 /
          不回显 / 不入错误 ``data``**（C-07）；原型实例**不被修改**。

        Args:
            base_url: 覆盖端点（``None`` → 沿用原型 ``base_url``）。
            api_key: 覆盖明文密钥（``None`` → 保持原型密钥，通常为 ``None``）。

        Returns:
            覆盖后的新 :class:`HttpModelProvider` 实例（原型不变）。
        """
        bound = copy.copy(self)
        if base_url is not None:
            bound.base_url = base_url.rstrip("/")
        if api_key is not None:
            bound._api_key = api_key
        return bound

    # -- 生命周期 ------------------------------------------------------------

    def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        self._client.close()

    def __enter__(self) -> HttpModelProvider:  # noqa: D105
        return self

    def __exit__(self, *exc_info: object) -> None:  # noqa: D105
        self.close()

    # -- 请求基座 ------------------------------------------------------------

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        """返回请求头（子类可追加鉴权头）。"""
        return dict(self._extra_headers)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON 并返回解析后的响应体（错误归一化）。"""
        try:
            response = self._client.post(
                self._url(path), json=payload, headers=self._headers(), timeout=self.timeout
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"{self.name} 请求超时",
                retryable=True,
                data={"provider": self.name},
            ) from exc
        if response.status_code >= 400:
            raise self._error_from_response(response)
        return _json_or_empty(response)

    def _iter_response_lines(self, path: str, payload: dict[str, Any]) -> Iterator[str]:
        """POST JSON 并以流式逐行读取响应（错误归一化）。"""
        try:
            with self._client.stream(
                "POST", self._url(path), json=payload, headers=self._headers(), timeout=self.timeout
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    raise self._error_from_response(response)
                yield from response.iter_lines()
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"{self.name} 流式请求超时",
                retryable=True,
                data={"provider": self.name},
            ) from exc

    def _error_from_response(self, response: httpx.Response) -> ProviderError:
        """把 HTTP 错误响应归一化为 :class:`ProviderError`（429/5xx 可重试）。"""
        status = response.status_code
        detail: Any
        try:
            detail = response.json()
        except (json.JSONDecodeError, ValueError):
            detail = response.text[:200]
        return ProviderError(
            f"{self.name} 调用失败：HTTP {status}",
            http_status=status,
            retryable=status in RETRYABLE_STATUS_CODES,
            data={"provider": self.name, "detail": detail},
        )

    def _resolve_model(self, options: dict[str, Any], default: str) -> str:
        model = options.get("model") or default
        if not model:
            raise ProviderError(
                f"{self.name} 未指定模型名",
                retryable=False,
                data={"provider": self.name},
            )
        return str(model)

    def _apply_sampling(self, payload: dict[str, Any], options: dict[str, Any]) -> None:
        """把采样 / 生成参数透传到请求体（跳过空值）。"""
        for key in (
            "temperature",
            "max_tokens",
            "top_p",
            "stop",
            "seed",
            "presence_penalty",
            "frequency_penalty",
        ):
            value = options.get(key)
            if value is not None:
                payload[key] = value

    # -- 契约方法（子类覆盖；基类给出通用 token 计数） -----------------------

    def chat(self, messages: Sequence[ChatMessage], **options: Any) -> Any:  # pragma: no cover
        """执行一次对话补全（子类实现）。"""
        raise NotImplementedError

    def stream(self, messages: Sequence[ChatMessage], **options: Any) -> Iterator[str]:
        """流式会话（子类实现）。"""
        raise NotImplementedError

    def embeddings(self, texts: Sequence[str], **options: Any) -> Any:  # pragma: no cover
        """计算文本嵌入（子类实现）。"""
        raise NotImplementedError

    def count_tokens(self, text: str, **options: Any) -> TokenCount:
        """粗略 token 计数（无外部依赖；约 4 字符 / token，空串为 0）。"""
        stripped = text or ""
        count = (len(stripped) + 3) // 4
        return TokenCount(count=count, model=self.name)


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    """解析响应 JSON；空体返回空字典。"""
    if not response.content:
        return {}
    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
