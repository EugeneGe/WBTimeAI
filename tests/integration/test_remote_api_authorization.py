"""远程 Project / Task API 授权与隔离集成测试（R3 / T2-60；I-P2-39）。

覆盖（真实 ``create_app`` + 真实 SQLite，``session_factory`` 与 API 同库）：

1. **API 权限**：远程提交 / 列表 / 读取 / 取消 / Diff / 下载**逐项鉴权**（A-14）；
   — 无足迹用户 → 集合 / 变更操作 ``403``；单资源读取 ``404``（统一隔离）；
   — 作用域受限用户 → 授权范围命中 ``200``；越界 ``404``；
2. **404 隔离**：跨租户 / 越界资源一律 ``404``（不泄漏存在性）；
3. **游标续读**：事件 ``seq`` 单调、``?cursor=`` / ``Last-Event-ID`` 续读；
   过期游标 → ``EVENT_CURSOR_EXPIRED``（``410``）；
4. **下载授权**：Artifact 下载**逐项重新鉴权**（未授权 → ``404``；授权后经注入读取器 → ``200``）。

🔴 断言点阵（本机 pytest 汇总行经 tty 不产出 → ``awk`` 点阵计数，``.``=pass）。
"""

from __future__ import annotations

from typing import Any

# -- 支撑 --------------------------------------------------------------------


def _shell_data(resp: Any) -> Any:
    """取统一响应壳的 ``data``（``{code,message,data,request_id}``）；非壳原样返回。"""
    body = resp.json()
    if isinstance(body, dict) and "data" in body and "code" in body:
        return body["data"]
    return body


def _services(client: Any) -> Any:
    """取已装配的组合根产物 ``AppServices``。"""
    return client.app.state.services


def _default_tenant_id(session_factory: Any) -> str:
    """取默认租户标识（与 ``/auth/register`` 落库口径一致）。"""
    from astra_identity import build_identity_services

    return str(build_identity_services(session_factory).tenants.ensure_default().id)


def _create_workspace(client: Any, headers: dict[str, str], *, name: str = "ws") -> str:
    """经 API 创建工作区，返回其 id。"""
    created = client.post("/api/v1/workspaces", headers=headers, json={"name": name})
    assert created.status_code == 201, created.text
    return str(_shell_data(created)["id"])


def _create_project(
    client: Any, headers: dict[str, str], *, workspace_id: str, name: str = "proj"
) -> str:
    """经 API 创建带仓库地址的项目，返回其 id。"""
    created = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "workspace_id": workspace_id, "repo_url": f"https://x/{name}.git"},
    )
    assert created.status_code == 201, created.text
    return str(_shell_data(created)["id"])


def _submit_task(
    client: Any,
    headers: dict[str, str],
    *,
    workspace_id: str,
    project_id: str,
    agent_version_id: str = "av-1",
) -> str:
    """经 API 远程提交一个任务，返回 ``task_id``。"""
    created = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "agent_version_id": agent_version_id,
            "requirement": "do the thing",
            "base_ref": "main",
        },
    )
    assert created.status_code == 202, created.text
    return str(_shell_data(created)["task_id"])


def _seed_execution(
    session_factory: Any,
    *,
    task_id: str,
    attempt: int,
    checkout_ref: str,
    artifact_refs: dict[str, Any] | None = None,
    finish: bool = True,
) -> str:
    """经 ``ExecutionRecorder`` 预置一条 ``task_execution``（含不透明 ``checkout_ref``）。"""
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
        artifact_refs=artifact_refs,
    )
    # ``claim`` 不设结果提交；测试需要 Diff ``available=True`` → 补写 ``result_commit``。
    record.result_commit = "b" * 40
    if finish:
        record = recorder.finish(record)
    else:
        record = repository.update(record)
    return str(record.id)


def _scoped_user_headers(
    session_factory: Any,
    *,
    tenant_id: str,
    project_id: str | None,
    capabilities: list[str],
    username: str,
) -> dict[str, str]:
    """构造一个**非管理员**、经 ``resource_permission`` 授权的用户请求头（A-14）。

    ``project_id`` 非空 → 实例级授权（仅该项目）；``None`` → 类型级（全项目）。
    """
    from astra_config import get_settings
    from astra_database import SqlResourcePermissionRepository
    from astra_domain import ResourcePermission
    from astra_identity import build_identity_services
    from astra_security import TokenService

    identity = build_identity_services(session_factory)
    user = identity.users.ensure_user(
        tenant_id=tenant_id,
        username=username,
        email=f"{username}@example.com",
        password_hash="x",
    )
    SqlResourcePermissionRepository(session_factory).add(
        ResourcePermission(
            tenant_id=tenant_id,
            subject_type="user",
            subject_id=user.id,
            resource_type="TASK",
            action="EXECUTE",
            effect="ALLOW",
            scope={"capabilities": list(capabilities)},
            resource_id=project_id,
        )
    )
    token = TokenService(get_settings().secret_key).create_access_token(
        user.id, tenant_id=tenant_id
    )
    return {"Authorization": f"Bearer {token}"}


class _FakeArtifactReader:
    """确定性 Artifact 读取器替身（返回固定字节；供下载授权成功路径）。"""

    def read(self, ref: str) -> tuple[bytes, str]:
        """返回 ``(content, content_type)``。"""
        return f"content-of:{ref}".encode(), "text/plain"


class _FakeDiffGit:
    """确定性 Git 替身：``diff_name_status`` 返回预置 ``--name-status`` 输出（不触宿主 Git）。"""

    def __init__(self, stdout: str = "M\tapp.py\n") -> None:
        self._stdout = stdout

    def diff_name_status(
        self,
        session: Any,
        base: str,
        result: str,
        *,
        cwd: str | None = None,
        timeout_ms: int | None = None,
        env: Any = None,
    ) -> Any:
        """返回预置 ``(ok=True, stdout=...)``（供 :meth:`ChangeReviewService.diff` 解析）。"""
        from types import SimpleNamespace

        return SimpleNamespace(ok=True, stdout=self._stdout, stderr="", exit_code=0)


def _valid_checkout_ref(execution_id: str) -> str:
    """构造一个**可服务端还原**的不透明 ``checkout_ref``（供 ChangeReviewService containment 解析）。"""
    from astra_config import get_settings
    from astra_workspace import ProjectStorage

    return ProjectStorage(get_settings().workspace_root).checkout_ref(execution_id, 1)


# -- 1. API 权限（提交 / 列表 / 读取 / 取消） ---------------------------------


def test_submit_requires_permission(
    client: Any,
    auth_headers: dict[str, str],
    permissionless_headers: dict[str, str],
) -> None:
    """远程提交：无足迹用户 → ``403``（不静默、不创建）；管理员 → ``202 {task_id}``。"""
    ws = _create_workspace(client, auth_headers, name="perm-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)

    denied = client.post(
        "/api/v1/tasks",
        headers=permissionless_headers,
        json={"workspace_id": ws, "project_id": project, "agent_version_id": "av-1"},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["code"] == "PERMISSION_DENIED"

    allowed = client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"workspace_id": ws, "project_id": project, "agent_version_id": "av-1"},
    )
    assert allowed.status_code == 202, allowed.text
    assert _shell_data(allowed)["task_id"]


def test_submit_requires_version_exactly_one(client: Any, auth_headers: dict[str, str]) -> None:
    """远程提交：``agent_version_id`` / ``workflow_version_id`` 须二选一（否则 422）。"""
    ws = _create_workspace(client, auth_headers, name="ver-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    both = client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={
            "workspace_id": ws,
            "project_id": project,
            "agent_version_id": "av-1",
            "workflow_version_id": "wv-1",
        },
    )
    assert both.status_code == 422, both.text
    assert both.json()["code"] == "VALIDATION_ERROR"
    neither = client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"workspace_id": ws, "project_id": project},
    )
    assert neither.status_code == 422, neither.text


def test_list_remote_requires_permission(
    client: Any,
    auth_headers: dict[str, str],
    permissionless_headers: dict[str, str],
) -> None:
    """远程列表（``?project_id=``）：无足迹用户 → ``403``（不能枚举）。"""
    ws = _create_workspace(client, auth_headers, name="list-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    _submit_task(client, auth_headers, workspace_id=ws, project_id=project)

    denied = client.get(f"/api/v1/tasks?project_id={project}", headers=permissionless_headers)
    assert denied.status_code == 403, denied.text
    allowed = client.get(f"/api/v1/tasks?project_id={project}", headers=auth_headers)
    assert allowed.status_code == 200, allowed.text
    assert len(_shell_data(allowed)) == 1


def test_scoped_user_can_read_within_scope(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """作用域受限（非管理员）用户：命中授权项目 → ``200``；越界项目 → ``404``。"""
    tenant = _default_tenant_id(session_factory)
    ws = _create_workspace(client, auth_headers, name="scope-ws")
    project_a = _create_project(client, auth_headers, workspace_id=ws, name="a")
    project_b = _create_project(client, auth_headers, workspace_id=ws, name="b")
    task_a = _submit_task(client, auth_headers, workspace_id=ws, project_id=project_a)
    task_b = _submit_task(client, auth_headers, workspace_id=ws, project_id=project_b)
    scoped = _scoped_user_headers(
        session_factory,
        tenant_id=tenant,
        project_id=project_a,
        capabilities=["task.read"],
        username="scoped-reader",
    )

    ok = client.get(f"/api/v1/tasks/{task_a}", headers=scoped)
    assert ok.status_code == 200, ok.text

    out = client.get(f"/api/v1/tasks/{task_b}", headers=scoped)
    assert out.status_code == 404, f"越界应 404，实得 {out.status_code}: {out.text}"


def test_cancel_remote_requires_capability(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """远程取消：缺 ``task.cancel`` capability → ``403``；具备 → ``200`` 且置 ``CANCELLED``。"""
    tenant = _default_tenant_id(session_factory)
    ws = _create_workspace(client, auth_headers, name="cancel-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)
    reader_only = _scoped_user_headers(
        session_factory,
        tenant_id=tenant,
        project_id=project,
        capabilities=["task.read"],
        username="scoped-nocancel",
    )
    denied = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=reader_only)
    assert denied.status_code == 403, denied.text

    ok = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=auth_headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["status"] == "CANCELLED"


# -- 2. 404 隔离 -------------------------------------------------------------


def test_cross_tenant_remote_404(
    client: Any,
    auth_headers: dict[str, str],
    other_tenant_headers: dict[str, str],
) -> None:
    """跨租户访问远程任务 / 项目 → ``404``（不泄漏存在性）。"""
    ws = _create_workspace(client, auth_headers, name="ct-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)

    peek_task = client.get(f"/api/v1/tasks/{task_id}", headers=other_tenant_headers)
    assert peek_task.status_code == 404, peek_task.text
    assert peek_task.json()["code"] == "NOT_FOUND"

    peek_events = client.get(f"/api/v1/tasks/{task_id}/events", headers=other_tenant_headers)
    assert peek_events.status_code == 404, peek_events.text

    peek_project = client.get(f"/api/v1/projects/{project}/status", headers=other_tenant_headers)
    assert peek_project.status_code == 404, peek_project.text


def test_read_isolation_returns_404_not_403(
    client: Any, auth_headers: dict[str, str], permissionless_headers: dict[str, str]
) -> None:
    """单资源读取：无足迹用户 → ``404``（统一隔离，不泄漏存在性）。"""
    ws = _create_workspace(client, auth_headers, name="iso-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)

    resp = client.get(f"/api/v1/tasks/{task_id}/attempts", headers=permissionless_headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "NOT_FOUND"


# -- 3. 游标续读 -------------------------------------------------------------


def test_event_cursor_resume(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """事件 ``seq`` 单调；``?cursor=`` 续读无重复无遗漏；``Last-Event-ID`` 回退可用。"""
    ws = _create_workspace(client, auth_headers, name="ev-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)
    _seed_execution(session_factory, task_id=task_id, attempt=1, checkout_ref="wr_ref_1")

    first = client.get(f"/api/v1/tasks/{task_id}/events", headers=auth_headers)
    assert first.status_code == 200, first.text
    page = _shell_data(first)
    seqs = [event["seq"] for event in page["events"]]
    assert seqs == [1, 2], page

    # 续读（不透明 cursor）→ 无新事件。
    resumed = client.get(
        f"/api/v1/tasks/{task_id}/events",
        headers=auth_headers,
        params={"cursor": page["next_cursor"]},
    )
    assert resumed.status_code == 200, resumed.text
    assert _shell_data(resumed)["events"] == []

    # ``Last-Event-ID`` 回退（序号 1）→ 只回放 ``seq > 1``（去重，不重放）。
    replay = client.get(
        f"/api/v1/tasks/{task_id}/events",
        headers={**auth_headers, "Last-Event-ID": "1"},
    )
    assert replay.status_code == 200, replay.text
    assert [event["seq"] for event in _shell_data(replay)["events"]] == [2]


def test_event_cursor_expired_returns_stable_code(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """过期游标 → ``EVENT_CURSOR_EXPIRED``（``410``；保留窗口裁剪后旧 cursor 失效）。"""
    from astra_workspace import ExecutionTaskEventSource

    ws = _create_workspace(client, auth_headers, name="exp-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)
    _seed_execution(session_factory, task_id=task_id, attempt=1, checkout_ref="wr_e1")
    _seed_execution(session_factory, task_id=task_id, attempt=2, checkout_ref="wr_e2")

    # 把事件源换成**只保留最近 1 个 Attempt**（窗口低水位上移）→ 旧 cursor 过期。
    services = _services(client)
    from astra_database import SqlTaskExecutionRepository

    services.remote_tasks._events = ExecutionTaskEventSource(  # noqa: SLF001 - 测试注入保留窗口
        SqlTaskExecutionRepository(session_factory), retention_attempts=1
    )

    fresh = client.get(f"/api/v1/tasks/{task_id}/events", headers=auth_headers)
    assert fresh.status_code == 200, fresh.text
    assert [event["seq"] for event in _shell_data(fresh)["events"]] == [3, 4]

    # 构造指向 ``seq=1``（已被裁剪）的不透明 cursor。
    stale_cursor = services.remote_tasks.encode_event_cursor(task_id, 1)
    expired = client.get(
        f"/api/v1/tasks/{task_id}/events",
        headers=auth_headers,
        params={"cursor": stale_cursor},
    )
    assert expired.status_code == 410, expired.text
    assert expired.json()["code"] == "EVENT_CURSOR_EXPIRED"


def test_event_cursor_invalid_returns_422(client: Any, auth_headers: dict[str, str]) -> None:
    """非法游标 → ``422 VALIDATION_ERROR``（稳定且非 500）。"""
    ws = _create_workspace(client, auth_headers, name="bad-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)
    bad = client.get(
        f"/api/v1/tasks/{task_id}/events",
        headers=auth_headers,
        params={"cursor": "not-a-cursor"},
    )
    assert bad.status_code == 422, bad.text
    assert bad.json()["code"] == "VALIDATION_ERROR"


# -- 4. 下载授权 -------------------------------------------------------------


def test_artifact_download_reauthorizes(
    client: Any,
    auth_headers: dict[str, str],
    permissionless_headers: dict[str, str],
    session_factory: Any,
) -> None:
    """Artifact 下载**逐项重新鉴权**：未授权 → ``404``；授权（注入读取器）→ ``200``。"""
    tenant = _default_tenant_id(session_factory)
    ws = _create_workspace(client, auth_headers, name="dl-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)
    _seed_execution(
        session_factory,
        task_id=task_id,
        attempt=1,
        checkout_ref="wr_dl",
        artifact_refs={"report": {"ref": "art://report-1", "content_type": "text/plain"}},
    )

    # 未授权（无足迹）→ 404（不泄漏存在性）。
    denied = client.get(f"/api/v1/tasks/{task_id}/artifacts/report", headers=permissionless_headers)
    assert denied.status_code == 404, denied.text

    # 授权但未装配读取器（显式置空）→ 结构化 503（不 500、不静默空）。
    # F2 后组合根已**真实装配**读取器 → 覆盖为 ``None`` 验证**未装配**防御分支（随后注入替身 → 200）。
    _services(client).remote_tasks._artifact_reader = None  # noqa: SLF001
    unassembled = client.get(f"/api/v1/tasks/{task_id}/artifacts/report", headers=auth_headers)
    assert unassembled.status_code == 503, unassembled.text
    assert unassembled.json()["code"] == "DEPENDENCY_MISSING"

    # 注入读取器替身 → 管理员下载 → 200。
    _services(client).remote_tasks._artifact_reader = _FakeArtifactReader()  # noqa: SLF001
    ok = client.get(f"/api/v1/tasks/{task_id}/artifacts/report", headers=auth_headers)
    assert ok.status_code == 200, ok.text
    assert ok.content == b"content-of:art://report-1"

    # 作用域受限用户（授权 ``artifact.download``）→ 200；且**不含宿主路径**。
    scoped = _scoped_user_headers(
        session_factory,
        tenant_id=tenant,
        project_id=project,
        capabilities=["artifact.download"],
        username="scoped-dl",
    )
    scoped_ok = client.get(f"/api/v1/tasks/{task_id}/artifacts/report", headers=scoped)
    assert scoped_ok.status_code == 200, scoped_ok.text


def test_artifact_download_via_real_storage_adapter(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """F2（R5A-01a）：组合根装配的 ``_StorageArtifactReader`` 经**真实 storage** 取回对象。

    证明下载端点**真实可达**（不依赖测试后门注入读取器）：向组合根 ``providers.storage``
    put 对象 → seed ``artifact_refs`` 指向该 key → 管理员 ``GET`` → ``200`` + 内容字节一致。
    """
    ws = _create_workspace(client, auth_headers, name="dl-real-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)

    services = _services(client)
    storage = services.providers.storage
    assert services.remote_tasks._artifact_reader is not None  # noqa: SLF001 - 组合根装配（非后门）

    key = f"artifacts/{task_id}/report.txt"
    payload = b"hello-real-artifact"
    storage.put(key, payload, content_type="text/plain")
    try:
        _seed_execution(
            session_factory,
            task_id=task_id,
            attempt=1,
            checkout_ref="wr_real_adapter",
            artifact_refs={
                "report": {"ref": key, "size": len(payload), "content_type": "text/plain"}
            },
        )
        resp = client.get(f"/api/v1/tasks/{task_id}/artifacts/report", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.content == payload
    finally:
        storage.delete(key)


def test_artifact_metadata_and_diff_hide_host_paths(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """Artifact 元数据 / Diff 仅暴露不透明 ``checkout_ref``，**不含**宿主路径。"""
    ws = _create_workspace(client, auth_headers, name="meta-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)
    checkout_ref = _valid_checkout_ref("exec-meta-1")
    _seed_execution(
        session_factory,
        task_id=task_id,
        attempt=1,
        checkout_ref=checkout_ref,
        artifact_refs={"log": {"ref": "art://log-1", "size": 12}},
    )

    artifacts = client.get(f"/api/v1/tasks/{task_id}/artifacts", headers=auth_headers)
    assert artifacts.status_code == 200, artifacts.text
    body = _shell_data(artifacts)
    assert body[0]["name"] == "log" and body[0]["ref"] == "art://log-1"

    # F4：Diff 出口统一至 ``ChangeReviewService.diff``（经 Sandbox）；注入 fake git 返回真实摘要
    # （**不**触真实仓库 / 宿主 Git），保留「不透明 checkout_ref / 无宿主路径」断言。
    _services(client).change_review._git = _FakeDiffGit()  # noqa: SLF001
    diff = client.get(f"/api/v1/tasks/{task_id}/diff", headers=auth_headers)
    assert diff.status_code == 200, diff.text
    diff_body = _shell_data(diff)
    assert diff_body["checkout_ref"] == checkout_ref
    dumped = str(diff_body)
    assert "/" not in diff_body["checkout_ref"]  # 不透明句柄（不含路径分隔符）
    assert "\\" not in dumped and "C:" not in dumped and "/tmp" not in dumped


def test_task_diff_reaches_change_review_service(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """F4 / R5A-02：``GET /tasks/{id}/diff`` 经 ``ChangeReviewService.diff`` 真实出口。

    fake git 返回 ``M\\tapp.py`` / ``A\\tsrc/new.py`` → 200 且 ``files`` 逐项映射、
    ``available == True`` —— 证明 Diff 已由占位视图切到变更审阅服务（经 Sandbox 的文件摘要）。
    """
    ws = _create_workspace(client, auth_headers, name="diff-real-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)
    task_id = _submit_task(client, auth_headers, workspace_id=ws, project_id=project)
    _seed_execution(
        session_factory,
        task_id=task_id,
        attempt=1,
        checkout_ref=_valid_checkout_ref("exec-diff-real"),
    )

    _services(client).change_review._git = _FakeDiffGit("M\tapp.py\nA\tsrc/new.py\n")  # noqa: SLF001
    resp = client.get(f"/api/v1/tasks/{task_id}/diff", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = _shell_data(resp)
    assert body["available"] is True
    assert [item["path"] for item in body["files"]] == ["app.py", "src/new.py"]


def test_project_clone_and_status(
    client: Any, auth_headers: dict[str, str], permissionless_headers: dict[str, str]
) -> None:
    """Project Clone（``202 {task_id}``）/ 状态（不含宿主路径）；未授权 → ``403`` / ``404``。"""
    ws = _create_workspace(client, auth_headers, name="clone-ws")
    project = _create_project(client, auth_headers, workspace_id=ws)

    status = client.get(f"/api/v1/projects/{project}/status", headers=auth_headers)
    assert status.status_code == 200, status.text
    status_body = _shell_data(status)
    assert status_body["repo_configured"] is True
    assert "path" not in status_body

    clone = client.post(
        f"/api/v1/projects/{project}/clone",
        headers=auth_headers,
        json={"base_ref": "main", "idempotency_key": "clone-1"},
    )
    assert clone.status_code == 202, clone.text
    assert _shell_data(clone)["task_id"]

    denied_clone = client.post(
        f"/api/v1/projects/{project}/clone", headers=permissionless_headers, json={}
    )
    assert denied_clone.status_code == 404, denied_clone.text

    # Git ref 查询：F3 后组合根已装配 Sandbox GitRefsProvider；显式置空验证**未装配**降级 503。
    _services(client).remote_tasks._git_refs_provider = None  # noqa: SLF001
    refs = client.get(f"/api/v1/projects/{project}/git/refs", headers=auth_headers)
    assert refs.status_code == 503, refs.text
    assert refs.json()["code"] == "DEPENDENCY_MISSING"
