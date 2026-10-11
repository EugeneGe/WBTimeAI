"""``astra marketplace``——Marketplace 静态注册表与发布命令（W8 / T2-43；裁定 R3 / D5）。

经 **D5 核心分组** 注册（``main.py`` 调 ``register_command_group("marketplace", …)``）：
``astra marketplace publish <package-path> --registry <path>``。

🔴 **不上传**托管服务；``--registry`` 仅接受本地 Git 工作树 / 静态目录。
🔴 不新增顶级核心命令；``init`` / ``run`` / ``doctor`` 一字不动。
"""

from __future__ import annotations

import typer
from astra_plugin.marketplace.package import DEFAULT_CORE_VERSION
from astra_plugin.marketplace.publish import publish_package

__all__ = ["marketplace_app", "publish_command"]

#: ``astra marketplace`` 命令分组（D5 核心分组）。
marketplace_app = typer.Typer(
    help="Marketplace 静态注册表：发布版本化包（不上传托管服务）",
    no_args_is_help=True,
    add_completion=False,
)


@marketplace_app.command("publish")
def publish_command(
    package_path: str = typer.Argument(  # noqa: B008 - typer 需函数签名默认值
        ...,
        help="包目录（含 astra-package.yaml）或该清单路径",
    ),
    registry: str = typer.Option(  # noqa: B008 - typer 需函数签名默认值
        ...,
        "--registry",
        help="本地 Git 工作树或静态目录路径（不接受托管 URL）",
    ),
    core_version: str = typer.Option(  # noqa: B008 - typer 需函数签名默认值
        DEFAULT_CORE_VERSION,
        "--core-version",
        help="当前 core 版本（core_compat 兼容区间校验）",
    ),
) -> None:
    """把本地包发布到静态注册表（幂等；同名同版本异摘要拒绝）。"""
    summary = publish_package(package_path, registry, core_version=core_version)
    typer.echo(f"[{summary.outcome}] {summary.kind}/{summary.name}@{summary.version}")
    typer.echo(f"  摘要：{summary.artifact_sha256}")
    typer.echo(f"  归档：{summary.download}")
    typer.echo(f"  索引：{summary.index_path}")
