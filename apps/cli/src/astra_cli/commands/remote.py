"""``astra remote``——远程任务命令分组（R4 / T2-62；U-P2-41 / #41）。

经 **D5 核心分组** 注册（``main.py`` 调 ``register_command_group("remote", remote_app)``）：

- ``astra remote login``：把访问令牌写入**受保护凭据存储**（``0600``；令牌取自 env / stdin，
  **不进 argv**）；
- ``astra remote submit``：远程提交（固定 Agent / Workflow 版本）；
- ``astra remote list``：远程任务列表；
- ``astra remote follow``：事件**断点续读**（不透明 cursor）；
- ``astra remote cancel``：取消；
- ``astra remote diff``：受限 Diff；
- ``astra remote apply``：**显式 Apply**（不 Push）；
- ``astra remote push``：**显式 Push**（独立权限）。

🔴 **冻结路径**：Apply / Push **必须**命中 ``POST /tasks/{id}/apply`` · ``/push``
   （**禁止** `/tasks/{id}/diff/apply`）。
🔴 CLI **不在本地启动**项目 Build / Test / Agent；一切经远端 API。
🔴 **不改变** ``init`` / ``run`` / ``doctor`` 核心命令。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import typer

from astra_cli.remote_client import (
    TOKEN_ENV,
    RemoteAPIClient,
    RemoteAPIError,
    resolve_server,
    resolve_token,
    save_credential,
)

__all__ = ["remote_app", "build_remote_client"]

#: ``astra remote`` 命令分组（D5 核心分组）。
remote_app = typer.Typer(
    help="远程工作台（submit / list / follow / cancel / diff / apply / push）",
    no_args_is_help=True,
    add_completion=False,
)


def build_remote_client(server: str | None = None, *, token: str | None = None) -> RemoteAPIClient:
    """构造远程客户端（令牌取自 env / 受保护存储；**不进 argv**）。"""
    return RemoteAPIClient(resolve_server(server), resolve_token(token))


def _fail(error: RemoteAPIError) -> None:
    """打印错误（**不含**令牌 / 宿主路径）并以退出码 1 结束。"""
    detail = f" [{error.code}]" if error.code else ""
    typer.echo(f"错误：{error}{detail}")
    raise typer.Exit(code=1)


def _dump(data: Any) -> None:
    """以 JSON 打印结果（稳定、可脚本消费）。"""
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


@remote_app.command("login")
def login_command(
    server: str | None = typer.Option(  # noqa: UP007 - typer 需显式 Optional
        None, "--server", help="服务端地址（默认取 ASTRA_REMOTE_SERVER）"
    ),
    token_stdin: bool = typer.Option(  # noqa: B008 - typer 需函数签名默认值
        False, "--token-stdin", help="从 stdin 读取令牌（避免进 Shell 历史）"
    ),
) -> None:
    """登录：把令牌写入受保护凭据存储（``0600``）；令牌**不进 argv**。"""
    if token_stdin:
        token = sys.stdin.read().strip()
    else:
        token = (os.environ.get(TOKEN_ENV) or "").strip()
    if not token:
        typer.echo(
            f"错误：未提供令牌（请设置 {TOKEN_ENV} 或使用 --token-stdin）",
        )
        raise typer.Exit(code=1)
    path = save_credential(resolve_server(server), token)
    typer.echo(f"已保存凭据：{path}（服务端 {resolve_server(server)}）")


@remote_app.command("submit")
def submit_command(
    project_id: str = typer.Option(..., "--project-id", help="归属 Project 标识"),
    workspace_id: str = typer.Option(..., "--workspace-id", help="归属 Workspace 标识"),
    agent_version_id: str | None = typer.Option(None, "--agent-version-id", help="固定 Agent 版本"),
    workflow_version_id: str | None = typer.Option(
        None, "--workflow-version-id", help="固定 Workflow 版本"
    ),
    requirement: str = typer.Option("", "--requirement", help="需求文本"),
    base_ref: str | None = typer.Option(None, "--base-ref", help="基准引用（分支 / tag / 提交）"),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """远程提交任务（``agent_version_id`` | ``workflow_version_id`` 二选一）。"""
    if bool(agent_version_id) == bool(workflow_version_id):
        typer.echo("错误：需指定 --agent-version-id 或 --workflow-version-id 之一")
        raise typer.Exit(code=2)
    body: dict[str, Any] = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "requirement": requirement,
        "base_ref": base_ref,
    }
    if agent_version_id:
        body["agent_version_id"] = agent_version_id
    if workflow_version_id:
        body["workflow_version_id"] = workflow_version_id
    try:
        client = build_remote_client(server)
        _dump(client.request("POST", "/tasks", json_body=body))
    except RemoteAPIError as error:
        _fail(error)


@remote_app.command("list")
def list_command(
    project_id: str | None = typer.Option(None, "--project-id", help="按 Project 过滤"),
    status: str | None = typer.Option(None, "--status", help="按状态过滤"),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """列出远程任务（可按 Project / 状态过滤）。"""
    try:
        client = build_remote_client(server)
        _dump(client.request("GET", "/tasks", params={"project_id": project_id, "status": status}))
    except RemoteAPIError as error:
        _fail(error)


@remote_app.command("follow")
def follow_command(
    task_id: str = typer.Argument(..., help="任务标识"),
    cursor: str | None = typer.Option(None, "--cursor", help="起始不透明游标（断点续读）"),
    max_polls: int = typer.Option(1, "--max-polls", help="最多拉取页数（默认 1，避免长驻）"),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """事件**断点续读**：从 ``--cursor`` 续读，逐页打印并输出下一页游标。"""
    try:
        client = build_remote_client(server)
    except RemoteAPIError as error:
        _fail(error)
        return
    next_cursor = cursor
    pages = 0
    while pages < max(1, max_polls):
        try:
            page = client.request("GET", f"/tasks/{task_id}/events", params={"cursor": next_cursor})
        except RemoteAPIError as error:
            _fail(error)
            return
        _dump(page)
        next_cursor = (page or {}).get("next_cursor") or None
        pages += 1
        if not next_cursor:
            break
    if next_cursor:
        typer.echo(f"下一页游标：{next_cursor}")


@remote_app.command("cancel")
def cancel_command(
    task_id: str = typer.Argument(..., help="任务标识"),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """取消远程任务（终态幂等）。"""
    try:
        client = build_remote_client(server)
        _dump(client.request("POST", f"/tasks/{task_id}/cancel"))
    except RemoteAPIError as error:
        _fail(error)


@remote_app.command("diff")
def diff_command(
    task_id: str = typer.Argument(..., help="任务标识"),
    attempt: int | None = typer.Option(None, "--attempt", help="Attempt 序号（默认最近完成）"),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """某 Attempt 的**受限** Diff（不透明 ``checkout_ref``，**不含**宿主路径）。"""
    try:
        client = build_remote_client(server)
        _dump(client.request("GET", f"/tasks/{task_id}/diff", params={"attempt": attempt}))
    except RemoteAPIError as error:
        _fail(error)


@remote_app.command("apply")
def apply_command(
    task_id: str = typer.Argument(..., help="任务标识"),
    target_ref: str | None = typer.Option(
        None, "--target-ref", help="目标分支（默认 Project 默认分支）"
    ),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """**显式 Apply**（F-R6；**不** Push）：命中冻结路径 ``POST /tasks/{id}/apply``。"""
    try:
        client = build_remote_client(server)
        _dump(
            client.request("POST", f"/tasks/{task_id}/apply", json_body={"target_ref": target_ref})
        )
    except RemoteAPIError as error:
        _fail(error)


@remote_app.command("push")
def push_command(
    task_id: str = typer.Argument(..., help="任务标识"),
    target_ref: str | None = typer.Option(
        None, "--target-ref", help="目标分支（默认 Project 默认分支）"
    ),
    remote: str = typer.Option("origin", "--remote", help="远端名（仅 origin 合法）"),
    server: str | None = typer.Option(None, "--server", help="服务端地址"),
) -> None:
    """**显式 Push**（F-R7；**独立**权限）：命中冻结路径 ``POST /tasks/{id}/push``。"""
    try:
        client = build_remote_client(server)
        _dump(
            client.request(
                "POST",
                f"/tasks/{task_id}/push",
                json_body={"target_ref": target_ref, "remote": remote},
            )
        )
    except RemoteAPIError as error:
        _fail(error)
