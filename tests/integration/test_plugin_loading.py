"""插件装载 / Registry / CLI 扩展集成测试（W1b 裁定 §3 / §4；T2-05）。

覆盖：装载 → 注册扩展点 → 卸载（卸载后仍可启动）/ CLI 命令冲突 ``CONFLICT`` /
核心保留键冲突 / 扩展点版本不兼容 ``CONFIGURATION_ERROR`` / 装载失败降级（跳过）/
目录扫描 / ``CLIRegistry`` 分组装配与冲突。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import typer
from astra_cli.registry import CLICommandSpec, CLIRegistry
from astra_core import DomainError, ErrorCode
from astra_plugin.loader import PluginLoader
from astra_plugin.metadata import PluginMetadata
from astra_plugin.registry import PluginRegistry

_EP = tuple[str, str, object]
_CLI = tuple[CLICommandSpec, Callable[..., Any]]


def _handler() -> None:
    """无参处理器端点（占位）。"""
    typer.echo("ok")


class _FakePlugin:
    """结构契合 ``Plugin`` 的测试插件。"""

    def __init__(
        self,
        name: str,
        *,
        kind: str = "community",
        extension_points: tuple[_EP, ...] = (),
        cli_commands: tuple[_CLI, ...] = (),
        should_fail: bool = False,
    ) -> None:
        self._metadata = PluginMetadata(name=name, version="1.0.0", kind=kind)
        self._extension_points = extension_points
        self._cli_commands = cli_commands
        self._should_fail = should_fail
        self.unregistered = False

    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata

    def register(self, registrar: Any) -> None:
        if self._should_fail:
            raise RuntimeError("模拟插件注册失败")
        for point, version, impl in self._extension_points:
            registrar.register_extension_point(point, version, impl)
        for spec, handler in self._cli_commands:
            registrar.register_cli(spec, handler)

    def unregister(self) -> None:
        self.unregistered = True


# -- 装载 / 卸载 --------------------------------------------------------------


def test_register_and_unregister_keeps_registry_startable() -> None:
    registry = PluginRegistry()
    impl = object()
    plugin = _FakePlugin(
        "demo",
        extension_points=(("auth_provider", "auth_provider/v1", impl),),
    )
    registry.register(plugin)
    assert "demo" in registry
    assert [meta.name for meta in registry.list()] == ["demo"]
    assert registry.extension_points()["auth_provider"] == [impl]

    registry.unregister("demo")
    assert "demo" not in registry
    assert registry.extension_points() == {}
    assert plugin.unregistered is True
    # 卸载后仍可继续注册（应用仍可启动）。
    registry.register(_FakePlugin("again"))
    assert len(registry) == 1


def test_unregister_is_idempotent() -> None:
    registry = PluginRegistry()
    registry.unregister("never-registered")
    assert len(registry) == 0


def test_get_missing_plugin_raises_not_found() -> None:
    with pytest.raises(DomainError) as excinfo:
        PluginRegistry().get("missing")
    assert excinfo.value.code is ErrorCode.NOT_FOUND


# -- 命令冲突 -----------------------------------------------------------------


def test_cli_command_conflict_raises_conflict() -> None:
    registry = PluginRegistry()
    spec = CLICommandSpec(group="data", command="export", summary="导出")
    registry.register(_FakePlugin("p1", cli_commands=((spec, _handler),)))

    with pytest.raises(DomainError) as excinfo:
        registry.register(_FakePlugin("p2", cli_commands=((spec, _handler),)))
    assert excinfo.value.code is ErrorCode.CONFLICT
    assert excinfo.value.data["group"] == "data"
    assert excinfo.value.data["command"] == "export"
    assert excinfo.value.data["incoming_plugin"] == "p2"


def test_core_reserved_command_conflict() -> None:
    registry = PluginRegistry()
    spec = CLICommandSpec(group="", command="init", summary="非法占用核心命令")
    with pytest.raises(DomainError) as excinfo:
        registry.register(_FakePlugin("bad", cli_commands=((spec, _handler),)))
    assert excinfo.value.code is ErrorCode.CONFLICT
    assert excinfo.value.data["existing_plugin"] == "<core>"


# -- 版本不兼容（原子：不落账） ----------------------------------------------


def test_incompatible_extension_point_version_raises_configuration_error() -> None:
    registry = PluginRegistry()
    plugin = _FakePlugin(
        "incompatible",
        extension_points=(("auth_provider", "auth_provider/v2", object()),),
    )
    with pytest.raises(DomainError) as excinfo:
        registry.register(plugin)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    # 原子性：不落账。
    assert "incompatible" not in registry


# -- 装载器 -------------------------------------------------------------------


class _FakeEntryPoint:
    def __init__(self, name: str, obj: object) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> object:
        return self._obj


def test_loader_installs_entry_point_plugin() -> None:
    plugin = _FakePlugin("entry", extension_points=(("connector", "connector/v1", object()),))
    loader = PluginLoader(entry_points_provider=lambda: [_FakeEntryPoint("entry", plugin)])
    registry = PluginRegistry()
    assert loader.install(registry) == ["entry"]
    assert "entry" in registry


def test_loader_skips_failing_plugin_without_blocking() -> None:
    good = _FakePlugin("good")
    bad = _FakePlugin("bad", should_fail=True)
    loader = PluginLoader(
        entry_points_provider=lambda: [_FakeEntryPoint("good", good), _FakeEntryPoint("bad", bad)]
    )
    registry = PluginRegistry()
    assert loader.install(registry) == ["good"]
    assert "good" in registry
    assert "bad" not in registry


def test_loader_scans_plugin_directory(tmp_path: Path) -> None:
    official = tmp_path / "official"
    plugin_dir = official / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.toml").write_text(
        'name = "demo"\nversion = "1.0.0"\nkind = "official"\nmodule = "demo_plugin"\n',
        encoding="utf-8",
    )
    (plugin_dir / "demo_plugin.py").write_text(
        "from astra_plugin.metadata import PluginMetadata\n"
        "\n"
        "class DemoPlugin:\n"
        "    @property\n"
        "    def metadata(self):\n"
        '        return PluginMetadata(name="demo", version="1.0.0", kind="official")\n'
        "    def register(self, registrar):\n"
        "        return None\n"
        "    def unregister(self):\n"
        "        return None\n"
        "\n"
        "plugin = DemoPlugin()\n",
        encoding="utf-8",
    )
    loader = PluginLoader(plugin_dirs=[official])
    registry = PluginRegistry()
    assert loader.install(registry) == ["demo"]
    assert "demo" in registry


# -- CLIRegistry --------------------------------------------------------------


def test_cli_registry_build_groups_and_conflict() -> None:
    registry = CLIRegistry()
    spec = CLICommandSpec(group="data", command="export", summary="导出数据")
    registry.register(spec, _handler)
    groups = registry.build_groups()
    assert "data" in groups
    assert registry.get(spec) is _handler

    with pytest.raises(DomainError) as excinfo:
        registry.register(spec, _handler)
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_cli_registry_rejects_core_reserved_command() -> None:
    registry = CLIRegistry()
    spec = CLICommandSpec(group="", command="doctor", summary="非法")
    with pytest.raises(DomainError) as excinfo:
        registry.register(spec, _handler)
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_mount_plugin_commands_keeps_core_commands() -> None:
    """装配插件命令后，核心三命令仍在（init / run / doctor 一字不动）。"""
    from astra_cli.main import app, mount_plugin_commands
    from typer.testing import CliRunner

    mount_plugin_commands()  # 仓库内现无插件 → 空装配，不报错。
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init", "run", "doctor"):
        assert command in result.output
