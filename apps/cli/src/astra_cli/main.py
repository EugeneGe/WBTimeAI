"""Astra AI 命令行入口（Typer，决策 D5）。

子命令：``astra init`` / ``astra run`` / ``astra doctor``（**三核心命令兼容稳定**）。

扩展机制（D5 / P0-11）：新增能力经 ``astra <group> <cmd>`` **分组注册**接入，
由 :func:`register_command_group` 完成；**不新增顶级核心命令**。

🔴 CLI **不判断 mode**（唯一分流点在 ``astra_config.providers``）；
   ``run`` 复用 ``astra_api.main:app``（``create_app``），不复制业务逻辑。
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import typer

from astra_cli.commands.data import data_app
from astra_cli.commands.doctor import run_doctor
from astra_cli.commands.init import run_init
from astra_cli.commands.marketplace import marketplace_app
from astra_cli.commands.run import DEFAULT_HOST, DEFAULT_PORT, run

__all__ = ["app", "main", "register_command_group", "mount_plugin_commands"]

app = typer.Typer(
    help="Astra AI 命令行（init / run / doctor）",
    no_args_is_help=True,
    add_completion=False,
)


def register_command_group(name: str, group: typer.Typer) -> None:
    """注册扩展命令分组：``astra <name> <cmd>``（D5 / P0-11）。

    供核心或插件以「分组」方式扩展命令，**不新增顶级核心命令**（`init` / `run` /
    `doctor` 保持稳定）。例如 ``register_command_group("agents", agents_app)`` 后
    可用 ``astra agents list``。

    Args:
        name: 分组名（命令首段）。
        group: 该分组的 :class:`typer.Typer` 子应用。
    """
    app.add_typer(group, name=name)


# W8 / T2-43：Marketplace 走 **D5 核心分组**
# （`astra marketplace publish <path> --registry <path>`）。
# 不新增顶级核心命令；`init` / `run` / `doctor` 一字不动（RESERVED_CORE_COMMANDS 不受影响）。
register_command_group("marketplace", marketplace_app)

# W9 / T2-48：数据保留与清理配套命令走 **D5 核心分组**
# （`astra data backup` / `astra data restore`）。
# 不新增顶级核心命令；`init` / `run` / `doctor` 一字不动。
register_command_group("data", data_app)


def _plugins_root() -> Path:
    """解析仓库内插件根目录 ``<repo>/plugins``（best-effort；不存在则目录扫描为空）。"""
    return Path(__file__).resolve().parents[4] / "plugins"


def mount_plugin_commands() -> None:
    """装配插件 CLI 扩展（组合根注入；W1b 裁定 §3.2 / §4）。

    - 经 :class:`~astra_plugin.loader.PluginLoader`（entry points + ``plugins/{official,
      community}/`` 目录扫描）装载插件；
    - 插件上报的 ``CLICommandSpec`` 经 :class:`~astra_cli.registry.CLIRegistry` 统一注册；
    - :meth:`~astra_cli.registry.CLIRegistry.build_groups` 的产物经既有
      :func:`register_command_group` 挂载。

    🔴 CLI **不判断 mode**；`init` / `run` / `doctor` 一字不动。
    🔴 命令冲突（``DomainError(CONFLICT)``）**向上抛出**——启动失败，不静默覆盖。
    """
    from astra_plugin.loader import PluginLoader
    from astra_plugin.registry import PluginRegistry

    from astra_cli.registry import CLICommandSpec, CLIRegistry

    root = _plugins_root()
    loader = PluginLoader(plugin_dirs=[root / "official", root / "community"])
    plugin_registry = PluginRegistry()
    loader.install(plugin_registry)

    cli_registry = CLIRegistry()
    for command in plugin_registry.cli_commands():
        cli_registry.register(cast(CLICommandSpec, command.spec), command.handler)
    for name, group in cli_registry.build_groups().items():
        register_command_group(name, group)


@app.command("init")
def init_command(
    data_dir: str | None = typer.Option(  # noqa: UP007 - typer 需显式 Optional
        None,
        "--data-dir",
        help="数据目录（默认取配置 ASTRA_DATA_DIR，通常为 ~/.astra-ai）",
    ),
) -> None:
    """初始化本地数据目录、``config.yaml`` 与默认身份（幂等）。"""
    report = run_init(data_dir=data_dir)
    typer.echo(f"数据目录：{report.data_dir}")
    typer.echo(f"子目录：新建 {len(report.created_dirs)} 个，已存在 {len(report.existing_dirs)} 个")
    written = "写入" if report.config_written else "已存在（跳过）"
    typer.echo(f"config.yaml：{report.config_path}（{written}）")
    typer.echo(f"数据库 schema：{report.schema_backend}")
    typer.echo(f"默认租户：{report.bootstrap_tenant_slug}")


@app.command("run")
def run_command(
    host: str = typer.Option(DEFAULT_HOST, "--host", help="监听地址"),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="监听端口"),
    reload: bool = typer.Option(False, "--reload", help="开发自动重载"),
) -> None:
    """单进程启动 Astra AI HTTP 服务（默认 127.0.0.1:8080）。"""
    run(host=host, port=port, reload=reload)


@app.command("doctor")
def doctor_command() -> None:
    """本机自检（配置 / DB / 迁移 / 目录 / 依赖 / Docker / Provider），返回退出码。"""
    raise typer.Exit(code=run_doctor())


def main() -> None:
    """CLI 入口（``[project.scripts] astra``）。"""
    mount_plugin_commands()
    app()
