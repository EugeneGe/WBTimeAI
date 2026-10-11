"""``PluginRegistry`` 与装载期注册器（设计 §2.14；W1b 裁定 §3.3 / §3.4）。

- :class:`_PluginRegistrar`：装载期注入的具体注册器（结构契合 ``PluginRegistrar``）；
- :class:`PluginRegistry`：插件生命周期（``register`` / ``unregister`` / ``get`` /
  ``list`` / ``extension_points``）。

🔴 **原子注册**：单插件 ``register`` 期间任一步失败（版本不兼容 / 命令冲突 /
  插件自身异常）→ **整插件不落账**（不留半成品）。
🔴 **零 ORM**：本模块不 import 任何 ORM / Web / 能力包（W1b 裁定 R2）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainError, ErrorCode

from .cli_extension import RESERVED_CORE_COMMANDS, CLICommandIndex, PluginCLICommand
from .extension_points import SUPPORTED_EXTENSION_POINTS, is_compatible_point
from .metadata import Plugin, PluginMetadata

__all__ = ["PluginRegistry"]


@dataclass
class _Registration:
    """单个插件的注册账目（扩展点 + CLI 命令）。"""

    plugin: Plugin
    extension_points: list[tuple[str, str, object]] = field(default_factory=list)
    cli_commands: list[PluginCLICommand] = field(default_factory=list)


class _PluginRegistrar:
    """装载期具体注册器（结构契合 ``PluginRegistrar`` Protocol）。"""

    def __init__(self, registry: PluginRegistry, plugin_name: str) -> None:
        self._registry = registry
        self._plugin_name = plugin_name
        self.extension_points: list[tuple[str, str, object]] = []
        self.cli_commands: list[PluginCLICommand] = []
        self._claimed_cli_keys: set[tuple[str, str]] = set()

    def register_extension_point(self, point: str, version: str, impl: object) -> None:
        """上报扩展点实现；版本与核心支持版本 MAJOR 不一致 → ``CONFIGURATION_ERROR``。"""
        supported = SUPPORTED_EXTENSION_POINTS.get(point)
        if not is_compatible_point(point, version):
            raise DomainError(
                f"扩展点版本不兼容：{point} 声明 {version}（核心支持 {supported}）",
                code=ErrorCode.CONFIGURATION_ERROR,
                data={"point": point, "declared": version, "supported": supported},
            )
        self.extension_points.append((point, version, impl))

    def register_cli(self, spec: object, handler: Callable[..., Any]) -> None:
        """上报 CLI 命令；键冲突（含核心保留键）→ ``CONFLICT``（**不静默覆盖**）。"""
        group = str(getattr(spec, "group", ""))
        command = str(getattr(spec, "command", ""))
        key = (group, command)
        if key in self._claimed_cli_keys or self._registry._cli_index.conflict(group, command):
            self._registry._cli_index.raise_conflict(group, command, self._plugin_name)
        self._claimed_cli_keys.add(key)
        self.cli_commands.append(
            PluginCLICommand(
                group=group,
                command=command,
                plugin_name=self._plugin_name,
                spec=spec,
                handler=handler,
            )
        )


class PluginRegistry:
    """插件注册表（生命周期 + 扩展点 / CLI 命令聚合）。

    Args:
        core_commands: 核心命令保留键（默认 :data:`RESERVED_CORE_COMMANDS`）。
    """

    def __init__(
        self, *, core_commands: frozenset[tuple[str, str]] = RESERVED_CORE_COMMANDS
    ) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._registrations: dict[str, _Registration] = {}
        self._extension_points: dict[str, list[object]] = {}
        self._cli_index = CLICommandIndex(core_commands)
        self._cli_commands: list[PluginCLICommand] = []

    def register(self, plugin: Plugin) -> None:
        """注册插件（冲突 → ``CONFLICT``）。

        插件 ``register`` 期间上报的扩展点 / CLI 命令**在成功后**原子落账：
        任一步失败（版本不兼容 / 命令冲突 / 插件异常）→ 整插件不落账。

        Raises:
            DomainError: 插件名重复（``CONFLICT``）；扩展点版本不兼容
                （``CONFIGURATION_ERROR``）；CLI 命令冲突（``CONFLICT``）。
        """
        metadata = plugin.metadata
        if metadata.name in self._plugins:
            raise DomainError(
                f"插件已注册：{metadata.name}",
                code=ErrorCode.CONFLICT,
                data={"name": metadata.name},
            )

        registrar = _PluginRegistrar(self, metadata.name)
        # 插件自行上报；任一异常在此抛出，注册账目不落账（原子）。
        plugin.register(registrar)

        # -- 原子提交 --------------------------------------------------------
        self._plugins[metadata.name] = plugin
        self._registrations[metadata.name] = _Registration(
            plugin=plugin,
            extension_points=list(registrar.extension_points),
            cli_commands=list(registrar.cli_commands),
        )
        for _point, _version, impl in registrar.extension_points:
            self._extension_points.setdefault(_point, []).append(impl)
        for command in registrar.cli_commands:
            self._cli_index.set_owner(command.group, command.command, metadata.name)
            self._cli_commands.append(command)

    def unregister(self, name: str) -> None:
        """卸载插件（**幂等**：不存在静默返回）。

        一并移除该插件注册的扩展点与 CLI 命令，使应用仍可启动（``I-P2-19``）。
        """
        registration = self._registrations.pop(name, None)
        if registration is None:
            return
        plugin = self._plugins.pop(name)

        for point, _version, impl in registration.extension_points:
            bucket = self._extension_points.get(point)
            if bucket is None:
                continue
            if impl in bucket:
                bucket.remove(impl)
            if not bucket:
                del self._extension_points[point]
        for command in registration.cli_commands:
            self._cli_index.release(command.group, command.command)
            if command in self._cli_commands:
                self._cli_commands.remove(command)

        try:
            plugin.unregister()
        except Exception:  # noqa: BLE001 - 生命周期钩子失败不阻断卸载
            return

    def get(self, name: str) -> Plugin:
        """按名获取插件。

        Raises:
            DomainError: 未注册（``NOT_FOUND``）。
        """
        try:
            return self._plugins[name]
        except KeyError as exc:
            raise DomainError(
                f"插件未注册：{name}", code=ErrorCode.NOT_FOUND, data={"name": name}
            ) from exc

    def extension_points(self) -> Mapping[str, list[object]]:
        """返回「点 → 实现列表」视图（副本）。"""
        return {point: list(impls) for point, impls in self._extension_points.items()}

    def cli_commands(self) -> list[PluginCLICommand]:
        """返回已登记的插件 CLI 命令（按登记顺序）。"""
        return list(self._cli_commands)

    def list(self) -> list[PluginMetadata]:
        """返回已注册插件元数据（按 ``name`` 排序）。"""
        return [self._plugins[name].metadata for name in sorted(self._plugins)]

    def __contains__(self, name: object) -> bool:  # noqa: D105
        return isinstance(name, str) and name in self._plugins

    def __len__(self) -> int:  # noqa: D105
        return len(self._plugins)
