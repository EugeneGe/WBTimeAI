"""``astra project``——远程 Project 命令分组（R4 / T2-62；U-P2-41）。

经 **D5 核心分组** 注册（``main.py`` 调 ``register_command_group("project", project_app)``）：

- ``astra project clone``：异步克隆 Project（``202 {task_id}``；``EXECUTE + project.clone``）；
- ``astra project status``：远程 Project 状态（**不含宿主路径**）。

🔴 Project 仓库在**服务端**克隆；CLI 仅派发 / 查询，**不在本地拉取**。
🔴 **不改变** ``init`` / ``run`` / ``doctor`` 核心命令。
"""

from __future__ import annotations

import json

import typer

from astra_cli.commands.remote import build_remote_client as _build
from astra_cli.remote_client import RemoteAPIError

__all__ = ["project_app"]

#: ``astra project`` 命令分组（D5 核心分组）。
project_app = typer.Typer(
    help="远程项目（clone / status）",
    no_args_is_help=True,
    add_completion=False,
)


def _dump(data: object) -> None:
    """以 JSON 打印结果（稳定、可脚本消费）。"""
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _fail(error: RemoteAPIError) -> None:
    """打印错误（**不含**令牌 / 宿主路径）并以退出码 1 结束。"""
    detail = f" [{error.code}]" if error.code else ""
    typer.echo(f"错误：{error}{detail}")
    raise typer.Exit(code=1)


@project_app.command("clone")
def clone_command(
    project_id: str = typer.Argument(..., help="项目标识"),
    base_ref: str | None = typer.Option(None, "--base-ref", help="克隆基准引用（可空）"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key", help="幂等键（可空）"),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """异步克隆 Project（服务端执行；返回 ``task_id``）。"""
    try:
        client = _build(server)
        _dump(
            client.request(
                "POST",
                f"/projects/{project_id}/clone",
                json_body={"base_ref": base_ref, "idempotency_key": idempotency_key},
            )
        )
    except RemoteAPIError as error:
        _fail(error)


@project_app.command("status")
def status_command(
    project_id: str = typer.Argument(..., help="项目标识"),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """远程 Project 状态（**不含宿主路径**）。"""
    try:
        client = _build(server)
        _dump(client.request("GET", f"/projects/{project_id}/status"))
    except RemoteAPIError as error:
        _fail(error)
