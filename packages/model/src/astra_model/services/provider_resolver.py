"""``ProviderResolver``——执行期「注册表原型 + 租户行 + 解密凭证」合流（M1）。

M1 · 真实 Provider 端到端：把「**注册表原型**（按 ``model_config.provider`` family 名）
＋ **租户 ``ModelProvider`` 行**（``endpoint`` + ``credential_id``）＋ **解密后 ``api_key``**
（经既有 :class:`~astra_model.services.ProviderRuntime`，带审计）」合流为**当次可调用**的具体
:class:`~astra_model.providers.base.HttpModelProvider` 实例。

🔴 **分层（H2）**：本模块属抽象包 ``astra_model``，**零 ORM / 零 Web / 零 ``astra_security``
   / 零 ``astra_database``**；凭证 / 仓储**全部**经**领域 Protocol**注入
   （``ModelProviderRepository`` 经 :class:`ProviderRuntime` 使用；解密**唯一**入口
   :meth:`ProviderRuntime.resolve_secret`）。SDK / HTTP 导入**只在** ``astra_model.providers``
   ——本模块**不** ``import httpx``，仅 ``from ..providers.base import HttpModelProvider``。

🔴 **凭证纪律（H4 / C-07）**：明文**仅内存**——解密后只搬进具体实例的 ``_api_key``；
   **不落库 / 不落日志 / 不回显 / 不入错误 ``data``**。错误 ``data`` **仅**含非敏感字段
   （``provider`` / ``provider_id`` / ``field``）。

🔴 **无凭证不静默（H6）**：未注册（Router 层）/ 无租户行 / endpoint 非法 / 需密钥却未绑凭证
   → :class:`~astra_core.DomainError`（``CONFIGURATION_ERROR``），**绝不** fallback 默认实例。
"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode
from astra_domain import (
    MODEL_PROVIDER_STATUS_ACTIVE,
    ModelProvider,
    ModelProviderRepository,
)

from ..provider import ModelProvider as ModelProviderProtocol
from ..providers.base import HttpModelProvider
from .provider_runtime import ProviderRuntime

__all__ = ["ProviderResolver", "build_provider_resolver"]


class ProviderResolver:
    """把注册表原型绑定为「租户 endpoint + 解密凭证」的具体 Provider 实例。

    依赖注入（均为**领域 Protocol**，零 ORM / 零 Web）：

    - ``provider_repository``：租户 Provider 行读取（``list_by_tenant`` / ``get``）；
    - ``provider_runtime``：**唯一**解密入口（写审计 ``model.credential.decrypt``）。
    """

    def __init__(
        self,
        *,
        provider_repository: ModelProviderRepository,
        provider_runtime: ProviderRuntime,
    ) -> None:
        self._providers = provider_repository
        self._runtime = provider_runtime

    def resolve(
        self,
        provider_name: str,
        *,
        prototype: ModelProviderProtocol,
        tenant_id: str,
        run_id: str | None = None,
    ) -> ModelProviderProtocol:
        """把 ``prototype`` 绑定为当次可调用的具体 Provider 实例。

        语义（对齐 M1 增量设计 §6.2）：

        - ``prototype`` **非** :class:`HttpModelProvider`（如 ``stub``）→ **原样返回**
          （无网络、无 endpoint / 凭证语义，绑定无意义；保证既有 ``provider="stub"``
          集成 / SSE 用例零回归）；
        - ``prototype`` 为 :class:`HttpModelProvider`：
            1. 取租户行（``type == provider_name`` 且 ``status == ACTIVE``；多行取
               ``(created_at, id)`` 最小首条；空集 → ``CONFIGURATION_ERROR``）；
            2. 校验 ``endpoint``（非空且非 ``http(s)://`` → ``CONFIGURATION_ERROR``；
               空 → 沿用原型默认 ``base_url``）；
            3. 凭证：``credential_id`` 有 → 经
               :meth:`ProviderRuntime.resolve_secret`（写审计）；无且
               ``requires_api_key`` → ``CONFIGURATION_ERROR``；无且
               ``requires_api_key=False`` → ``api_key=None``；
            4. ``prototype.with_binding(base_url=..., api_key=...)`` → 具体实例。

        Args:
            provider_name: 注册表 family 名（``model_config.provider``；与行 ``type`` 同集）。
            prototype: 注册表原型 Provider（按名解析所得，**不被修改**）。
            tenant_id: 租户标识（**必填**；决定绑定哪条租户行）。
            run_id: 关联 Run 标识（可空，**仅供审计**）。

        Returns:
            绑定后的 Provider 实例（携带租户 endpoint + 明文密钥，**仅内存**）；或
            ``prototype``（非 HTTP 形态时原样返回）。

        Raises:
            DomainError: 无匹配租户行 / endpoint 非法 / 需密钥却未绑凭证 / 凭证解密失败
                （``CONFIGURATION_ERROR`` / ``NOT_FOUND``，**不静默 fallback**）。
        """
        # 能力判定（isinstance，非 mode 分支）：非 HTTP 原型（如 stub）无绑定语义 → 旁路。
        if not isinstance(prototype, HttpModelProvider):
            return prototype

        row = self._select_row(provider_name, tenant_id)
        base_url = self._resolve_base_url(row, provider_name)
        api_key = self._resolve_api_key(row, prototype, tenant_id=tenant_id, run_id=run_id)
        return prototype.with_binding(base_url=base_url, api_key=api_key)

    # -- 内部：行匹配（确定性） ---------------------------------------------

    def _select_row(self, provider_name: str, tenant_id: str) -> ModelProvider:
        """选出租户下匹配 ``provider_name`` 的**唯一** ACTIVE 行（确定性）。

        匹配规则：``list_by_tenant(tenant_id)`` → 过滤
        ``status == MODEL_PROVIDER_STATUS_ACTIVE and type == provider_name`` →
        按 ``(created_at, id)`` 升序取首条；空集 → ``CONFIGURATION_ERROR``（H6）。

        Args:
            provider_name: 注册表 family 名（对齐行 ``type``）。
            tenant_id: 租户标识。

        Returns:
            选中的 :class:`~astra_domain.ModelProvider` 行。

        Raises:
            DomainError: 无匹配行（``CONFIGURATION_ERROR``）。
        """
        rows = self._providers.list_by_tenant(tenant_id)
        candidates = [
            row
            for row in rows
            if row.type == provider_name and row.status == MODEL_PROVIDER_STATUS_ACTIVE
        ]
        if not candidates:
            raise _config_error(
                f"租户未配置可用的模型提供方：{provider_name}",
                provider=provider_name,
            )
        # 确定性：``(created_at, id)`` 最小者（同一租户多行同 type 时）。
        candidates.sort(key=lambda row: (row.created_at, row.id))
        return candidates[0]

    # -- 内部：endpoint / 凭证 ---------------------------------------------

    def _resolve_base_url(self, row: ModelProvider, provider_name: str) -> str | None:
        """校验并归一化租户 ``endpoint``（空 → 沿用原型默认；非法 → 报错）。

        Args:
            row: 选中的租户 Provider 行。
            provider_name: 注册表 family 名（供错误 ``data``）。

        Returns:
            覆盖用 ``base_url``；租户行 ``endpoint`` 为空时返回 ``None``（＝沿用原型默认）。

        Raises:
            DomainError: ``endpoint`` 非空但非 ``http(s)://``（``CONFIGURATION_ERROR``）。
        """
        endpoint = (row.endpoint or "").strip()
        if not endpoint:
            return None
        if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
            raise _config_error(
                f"租户模型提供方 endpoint 非法（需 http(s)://）：{provider_name}",
                provider=provider_name,
                provider_id=row.id,
                field="endpoint",
            )
        return endpoint

    def _resolve_api_key(
        self,
        row: ModelProvider,
        prototype: ModelProviderProtocol,
        *,
        tenant_id: str,
        run_id: str | None,
    ) -> str | None:
        """解析当次密钥（有 ``credential_id`` → 解密；无 → 视 ``requires_api_key``）。

        🔴 解密**唯一**经 :meth:`ProviderRuntime.resolve_secret`（写审计
        ``model.credential.decrypt``）；明文的搬运用**仅内存**。

        Args:
            row: 选中的租户 Provider 行。
            prototype: 注册表原型（读取 ``requires_api_key``）。
            tenant_id: 租户标识（透传解密，供跨租户校验 / 审计）。
            run_id: 关联 Run 标识（透传审计）。

        Returns:
            明文密钥；``credential_id`` 空且 ``requires_api_key=False`` 时为 ``None``。

        Raises:
            DomainError: ``credential_id`` 空且 ``requires_api_key=True``
                （``CONFIGURATION_ERROR``）；或解密失败（由 ``ProviderRuntime`` 抛出）。
        """
        if row.credential_id:
            return self._runtime.resolve_secret(row.id, tenant_id=tenant_id, run_id=run_id)
        # 显式类属性判定（非 mode 分支）：本地 / 无密钥 Provider（如 ollama）无需凭证。
        requires_api_key = bool(getattr(prototype, "requires_api_key", True))
        if requires_api_key:
            raise _config_error(
                f"模型提供方需绑定凭证但未配置：{row.type}",
                provider=row.type,
                provider_id=row.id,
                field="credential_id",
            )
        return None


def build_provider_resolver(
    *,
    provider_repository: ModelProviderRepository,
    provider_runtime: ProviderRuntime,
) -> ProviderResolver:
    """装配 :class:`ProviderResolver`（组合根单点装配入口；H5）。

    Args:
        provider_repository: 租户 Provider 行读取（领域 Protocol）。
        provider_runtime: **唯一**解密入口（领域服务，写审计）。

    Returns:
        已注入依赖的 :class:`ProviderResolver`。
    """
    return ProviderResolver(
        provider_repository=provider_repository,
        provider_runtime=provider_runtime,
    )


def _config_error(
    message: str,
    *,
    provider: str | None = None,
    provider_id: str | None = None,
    field: str | None = None,
) -> DomainError:
    """构造 ``CONFIGURATION_ERROR``（``data`` **仅**含非敏感字段，H6 / H4）。"""
    data: dict[str, str] = {}
    if provider is not None:
        data["provider"] = provider
    if provider_id is not None:
        data["provider_id"] = provider_id
    if field is not None:
        data["field"] = field
    return DomainError(message, code=ErrorCode.CONFIGURATION_ERROR, data=data)
