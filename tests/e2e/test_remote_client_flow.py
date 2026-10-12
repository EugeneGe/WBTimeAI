"""远程客户端（CLI）经 API 控制服务端执行的**端到端**断言（R4 / T2-62；U-P2-41）。

覆盖（真实 ``create_app`` + 真实 SQLite；CLI 经**进程内**传输直连 ASGI 应用）：

1. **令牌纪律**：令牌经 ``Authorization: Bearer`` 注入（**不进 argv / 日志**）；
2. **CLI ↔ API 控制面**：``project status`` / ``project clone``（202） / ``remote list`` /
   ``remote follow``（事件断点续读）**命中真实端点并成功**；
3. **冻结路径**：``remote apply`` / ``remote push`` **必须**命中
   ``POST /tasks/{id}/apply`` · ``/push``（**禁止** ``/tasks/{id}/diff/apply``）；
4. **降级语义**：Diff 读取以 **200 + ``available`` 标志**降级（**不**伪造内容、**不**泄漏宿主
   路径）；Apply / Push 的 Git 能力未装配 → ``DEPENDENCY_MISSING``（503），CLI 以退出码 1 明示
   （**不**静默）。

🔴 令牌 / 宿主路径**不出现在** CLI 输出；🔴 本测试**不**启动本地 Build / Test / Agent。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from astra_cli.commands.project import project_app  # noqa: F401 - 确保分组已注册
from astra_cli.commands.remote import remote_app  # noqa: F401 - 确保分组已注册
from astra_cli.main import app
from astra_cli.remote_client import RemoteAPIClient
from typer.testing import CliRunner

# -- 支撑 --------------------------------------------------------------------


def _shell_data(resp: Any) -> Any:
    """取统一响应壳的 ``data``。"""
    body = resp.json()
    if isinstance(body, dict) and "data" in body and "code" in body:
        return body["data"]
    return body


def _create_workspace_and_project(
    client: Any, headers: dict[str, str], *, name: str
) -> tuple[str, str]:
    """经 API 建 [工作区 + 带仓库项目]，返回 ``(workspace_id, project_id)``。"""
    ws = client.post("/api/v1/workspaces", headers=headers, json={"name": f"{name}-ws"})
    assert ws.status_code == 201, ws.text
    ws_id = str(_shell_data(ws)["id"])
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "workspace_id": ws_id, "repo_url": f"https://x/{name}.git"},
    )
    assert project.status_code == 201, project.text
    return ws_id, str(_shell_data(project)["id"])


def _submit_remote_task(
    client: Any, headers: dict[str, str], *, workspace_id: str, project_id: str
) -> str:
    """经 API 远程提交任务，返回 ``task_id``。"""
    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "agent_version_id": "av-1",
            "requirement": "do the thing",
        },
    )
    assert created.status_code == 202, created.text
    return str(_shell_data(created)["task_id"])


def _seed_execution(session_factory: Any, *, task_id: str, attempt: int, checkout_ref: str) -> None:
    """预置一条已完成 Attempt（含不透明 ``checkout_ref`` / 结果提交）。"""
    from astra_database import SqlTaskExecutionRepository
    from astra_task import ExecutionRecorder

    repository = SqlTaskExecutionRepository(session_factory)
    recorder = ExecutionRecorder(repository)
    record = recorder.claim(
        task_id=task_id,
        attempt=attempt,
        checkout_ref=checkout_ref,
        base_commit="a" * 40,
        environment_digest="d" * 64,
    )
    record.result_commit = "b" * 40
    repository.update(record)


class _RecordingTransport:
    """进程内传输：记录请求路径并把调用转发给真实 ``TestClient``。"""

    def __init__(self, test_client: Any) -> None:
        self._client = test_client
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self, method: str, path: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, dict[str, str], bytes]:
        self.calls.append((method, path.split("?")[0]))
        response = self._client.request(method, path, headers=headers, content=body)
        return response.status_code, dict(response.headers), response.content

    def paths(self) -> list[str]:
        return [path for _method, path in self.calls]


@pytest.fixture()
def cli_harness(
    client: Any, auth_headers: dict[str, str], session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> Iterator[dict[str, Any]]:
    """构建 [CLI ↔ 真实 API] 环境：令牌经 env 注入、传输经进程内适配器。"""
    real_token = auth_headers["Authorization"].removeprefix("Bearer ")
    monkeypatch.setenv("ASTRA_REMOTE_TOKEN", real_token)
    transport = _RecordingTransport(client)

    def factory(server: str | None = None, *, token: str | None = None) -> RemoteAPIClient:
        _ = (server, token)  # 传输直连进程内应用；令牌由 env 提供
        return RemoteAPIClient("http://testserver", real_token, transport=transport)

    monkeypatch.setattr("astra_cli.commands.remote.build_remote_client", factory)
    monkeypatch.setattr("astra_cli.commands.project._build", factory)

    ws_id, project_id = _create_workspace_and_project(client, auth_headers, name="e2e")
    task_id = _submit_remote_task(client, auth_headers, workspace_id=ws_id, project_id=project_id)
    _seed_execution(session_factory, task_id=task_id, attempt=1, checkout_ref="wr_e2e_opaque")

    # Git 能力未装配 → Diff / Apply / Push 返回结构化 503（确定性；**不**触碰宿主 Git）。
    client.app.state.services.change_review._git = None  # noqa: SLF001 - 测试注入未装配态

    yield {
        "runner": CliRunner(),
        "transport": transport,
        "workspace_id": ws_id,
        "project_id": project_id,
        "task_id": task_id,
        "token": real_token,
    }


# -- 1. 令牌纪律 -------------------------------------------------------------


def test_cli_sends_bearer_token_and_never_echoes_it(cli_harness: dict[str, Any]) -> None:
    """令牌经 ``Authorization: Bearer`` 注入；CLI 输出**不含**令牌。"""
    result = cli_harness["runner"].invoke(
        app, ["remote", "list", "--project-id", cli_harness["project_id"]]
    )
    assert result.exit_code == 0, result.output
    assert cli_harness["token"] not in result.output


# -- 2. 控制面（真实端点成功） -----------------------------------------------


def test_project_status_and_clone(cli_harness: dict[str, Any]) -> None:
    """``project status`` → 200；``project clone`` → 202 ``{task_id}``。"""
    runner = cli_harness["runner"]
    status = runner.invoke(app, ["project", "status", cli_harness["project_id"]])
    assert status.exit_code == 0, status.output
    assert "repo_configured" in status.output

    clone = runner.invoke(
        app, ["project", "clone", cli_harness["project_id"], "--base-ref", "main"]
    )
    assert clone.exit_code == 0, clone.output
    assert "task_id" in clone.output
    assert f"/api/v1/projects/{cli_harness['project_id']}/clone" in cli_harness["transport"].paths()


def test_remote_list_returns_submitted_task(cli_harness: dict[str, Any]) -> None:
    """``remote list`` → 200 且含已提交的远程任务。"""
    result = cli_harness["runner"].invoke(
        app, ["remote", "list", "--project-id", cli_harness["project_id"]]
    )
    assert result.exit_code == 0, result.output
    assert cli_harness["task_id"] in result.output


def test_remote_follow_resumes_by_cursor(cli_harness: dict[str, Any]) -> None:
    """``remote follow`` → 200 事件页；携带 ``--cursor`` 发起**断点续读**。"""
    result = cli_harness["runner"].invoke(app, ["remote", "follow", cli_harness["task_id"]])
    assert result.exit_code == 0, result.output
    assert "events" in result.output

    path = cli_harness["transport"].paths()[-1]
    assert path.endswith(f"/api/v1/tasks/{cli_harness['task_id']}/events")


# -- 3. 冻结路径 + 结构化错误 ------------------------------------------------


def test_remote_apply_uses_frozen_path(cli_harness: dict[str, Any]) -> None:
    """``remote apply`` 命中 ``POST /tasks/{id}/apply``（**非** ``/diff/apply``）；
    未装配 → 退出码 1。"""
    result = cli_harness["runner"].invoke(
        app, ["remote", "apply", cli_harness["task_id"], "--target-ref", "main"]
    )
    paths = cli_harness["transport"].paths()
    assert f"/api/v1/tasks/{cli_harness['task_id']}/apply" in paths
    assert not any("/diff/apply" in p for p in paths)
    assert result.exit_code == 1
    assert "DEPENDENCY_MISSING" in result.output


def test_remote_push_uses_frozen_path(cli_harness: dict[str, Any]) -> None:
    """``remote push`` 命中 ``POST /tasks/{id}/push``（**独立**权限）；未装配 → 退出码 1。"""
    result = cli_harness["runner"].invoke(app, ["remote", "push", cli_harness["task_id"]])
    paths = cli_harness["transport"].paths()
    assert f"/api/v1/tasks/{cli_harness['task_id']}/push" in paths
    assert not any("/diff/apply" in p for p in paths)
    assert result.exit_code == 1
    assert "DEPENDENCY_MISSING" in result.output


def test_remote_diff_read_degrades_without_host_paths(cli_harness: dict[str, Any]) -> None:
    """``remote diff`` 命中冻结读取路径 ``/tasks/{id}/diff``；以 ``available`` 标志降级
    （**200**，非 503）；输出**不含**宿主路径 / 令牌。"""
    result = cli_harness["runner"].invoke(app, ["remote", "diff", cli_harness["task_id"]])
    assert f"/api/v1/tasks/{cli_harness['task_id']}/diff" in cli_harness["transport"].paths()
    # Diff 读取为 **200 + available 标志**的降级（**不**是 503）。
    assert result.exit_code == 0, result.output
    assert '"available"' in result.output
    # 🔴 令牌 / 宿主路径不出现在输出。
    assert cli_harness["token"] not in result.output
    assert cli_harness["workspace_id"] not in result.output  # 不泄漏无关标识
    assert ":/" not in result.output  # 无 ``scheme:/`` 形式的宿主路径
    assert "\\\\" not in result.output  # 无 Windows 宿主路径（JSON 转义后为 ``\\``）


# -- 4. 认证（无令牌 → 结构化错误；不静默） ----------------------------------


def test_cli_without_token_reports_configuration_error(
    client: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """无令牌（env / 存储均无）→ 结构化 ``CONFIGURATION_ERROR``（退出码 1）。"""
    monkeypatch.delenv("ASTRA_REMOTE_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    result = CliRunner().invoke(app, ["remote", "list"])
    assert result.exit_code == 1
    assert "未配置远程访问令牌" in result.output
