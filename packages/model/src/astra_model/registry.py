"""``ModelRegistry``（Provider 注册表）。"""

from __future__ import annotations

from astra_core import DomainError, ErrorCode

from .provider import ModelProvider

__all__ = ["ModelRegistry"]


class ModelRegistry:
    """模型 Provider 注册表。

    以名称为键注册 Provider；重名注册默认覆盖（同名视为更新实现）。
    """

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}

    def register(self, name: str, provider: ModelProvider, *, override: bool = True) -> None:
        """注册 Provider。

        Args:
            name: Provider 名称（唯一）。
            provider: Provider 实例。
            override: 重名时是否覆盖（默认 ``True``）。

        Raises:
            DomainError: 重名且 ``override=False``（``CONFLICT``）。
        """
        if not override and name in self._providers:
            raise DomainError(
                f"Provider 已注册：{name}", code=ErrorCode.CONFLICT, data={"name": name}
            )
        self._providers[name] = provider

    def unregister(self, name: str) -> None:
        """注销 Provider（运行时注册表；总纲 §12 RP-15）。

        幂等：名称不存在时静默返回（不抛错）。**向后兼容**——既有接口不变。
        """
        self._providers.pop(name, None)

    def get(self, name: str) -> ModelProvider:
        """按名称获取 Provider。

        Raises:
            DomainError: 未注册（``CONFIGURATION_ERROR``；设计 R26，W1b 裁定 §5.2）。
        """
        try:
            return self._providers[name]
        except KeyError as exc:
            raise DomainError(
                f"Provider 未注册：{name}",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"name": name},
            ) from exc

    def names(self) -> list[str]:
        """返回已注册 Provider 名称（排序）；委托 :meth:`list`（向后兼容）。"""
        return self.list()

    def list(self) -> list[str]:
        """返回已注册 Provider 名称（排序）。

        与 :meth:`names` 同源；``names`` 为向后兼容别名（W1b 裁定 §5.2）。
        """
        return sorted(self._providers)

    def __contains__(self, name: object) -> bool:  # noqa: D105
        return isinstance(name, str) and name in self._providers

    def __len__(self) -> int:  # noqa: D105
        return len(self._providers)
