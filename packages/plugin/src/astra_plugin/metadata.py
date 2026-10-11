"""插件元数据与聚合入口 Protocol（设计 §2.14；W1b 裁定 §3.1 / §3.3）。

- :class:`PluginMetadata`：插件元数据（frozen）；
- :class:`Plugin`：插件聚合入口（``metadata`` / ``register`` / ``unregister``）；
- :class:`PluginRegistrar`：装载期注入的**注册收集器**——插件在 ``register`` 中
  经它上报**扩展点实现**与 **CLI 命令**。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # 仅类型引用，避免 ``plugin → astra_cli`` 运行期依赖（W1b 裁定 R4）
    from astra_cli.registry import CLICommandSpec

__all__ = ["PluginMetadata", "Plugin", "PluginRegistrar"]


@dataclass(frozen=True)
class PluginMetadata:
    """插件元数据（唯一键 ``name``）。

    Attributes:
        name: 插件名（唯一键）。
        version: 插件版本。
        kind: 插件类别（``official`` / ``community`` / ``customer``）。
        entry_point: entry point 引用（可空；目录插件为 ``module:attr``）。
        permissions: 声明权限（默认空）。
        manifest: 原始清单（可空）。
        description: 描述（默认空）。
        extension_point_versions: 点 → 声明版本（用于同 MAJOR 兼容校验，裁定 §1.1-6）。
    """

    name: str
    version: str
    kind: str
    entry_point: str | None = None
    permissions: tuple[str, ...] = ()
    manifest: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""
    extension_point_versions: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class PluginRegistrar(Protocol):
    """装载期注入的注册收集器（结构契合即可，无需继承）。"""

    def register_extension_point(self, point: str, version: str, impl: object) -> None:
        """上报一个扩展点实现；版本不兼容 → ``DomainError(CONFIGURATION_ERROR)``。"""
        ...

    def register_cli(self, spec: CLICommandSpec, handler: Callable[..., Any]) -> None:
        """上报一个 CLI 命令；键冲突 → ``DomainError(CONFLICT)``。"""
        ...


@runtime_checkable
class Plugin(Protocol):
    """插件聚合入口。"""

    @property
    def metadata(self) -> PluginMetadata:
        """插件元数据。"""
        ...

    def register(self, registrar: PluginRegistrar) -> None:
        """装载期回调：经 ``registrar`` 上报扩展点 / CLI 命令。"""
        ...

    def unregister(self) -> None:
        """卸载回调（生命周期钩子，可空实现）。"""
        ...
