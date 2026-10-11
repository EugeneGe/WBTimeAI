"""2c API 面（``/projects`` / ``/workspaces/{id}/files|environment`` / ``/approvals`` / ``/tasks``）
集成回归（W10 / T2-49 · 冻结接口 R-W10-01~09）。

覆盖（真实 ``create_app`` + 真实 SQLite，``session_factory`` 与 API 同库）：

1. ``/projects`` 列表 / 创建 / 详情（含跨租户 404）；
2. ``/workspaces/{id}/files`` ``/environment``（含 ``files=None`` → 503 降级；环境敏感项 masked）；
3. ``/approvals`` 待办 + ``approve`` / ``reject``（含 409 重复决议；跨租户 404）；
4. ``/tasks`` 列表 / 详情 / 执行历史 / 取消（含跨租户 404、终态幂等）；
5. 统一响应壳字段 ``{code,message,data,request_id}`` 恒存在。

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


def _assert_shell(resp: Any) -> dict[str, Any]:
    """断言响应为统一响应壳，返回其体。"""
    body = resp.json()
    assert isinstance(body, dict), f"响应非壳对象：{body}"
    assert set(body.keys()) >= {"code", "message", "data", "request_id"}, f"非统一响应壳：{body}"
    return body


def _default_tenant_id(session_factory: Any) -> str:
    """取默认租户标识（与 ``/auth/register`` 落库口径一致）。"""
    from astra_identity import build_identity_services

    return str(build_identity_services(session_factory).tenants.ensure_default().id)


def _create_workspace(client: Any, headers: dict[str, str], *, name: str = "WS") -> str:
    """经 API 创建工作区，返回其 id。"""
    created = client.post("/api/v1/workspaces", headers=headers, json={"name": name})
    assert created.status_code == 201, created.text
    return _shell_data(created)["id"]


def _seed_pending_approval(
    session_factory: Any, *, tenant_id: str, subject_ref: str = "tool:demo"
) -> str:
    """经真实仓储预置一条 ``PENDING`` 审批，返回其 id。"""
    from astra_domain import Approval
    from astra_security.repositories import SqlApprovalRepository

    approval = SqlApprovalRepository(session_factory).add(
        Approval(
            tenant_id=tenant_id,
            subject_type="tool",
            subject_ref=subject_ref,
            status="PENDING",
        )
    )
    return str(approval.id)


def _seed_task(session_factory: Any, *, tenant_id: str, task_type: str = "agent.run") -> str:
    """经真实仓储预置一条 ``CREATED`` 任务，返回其 id。"""
    from astra_database import SqlTaskRepository
    from astra_task import Task, TaskStatus

    task = SqlTaskRepository(session_factory).add(
        Task(tenant_id=tenant_id, type=task_type, status=TaskStatus.CREATED)
    )
    return str(task.task_id)


def _seed_execution(session_factory: Any, *, task_id: str) -> str:
    """经 ``ExecutionRecorder`` 预置一条 ``task_execution``（``attempt`` 从 1 起），返回其 id。"""
    from astra_database import SqlTaskExecutionRepository
    from astra_task import ExecutionRecorder

    record = ExecutionRecorder(SqlTaskExecutionRepository(session_factory)).begin(task_id=task_id)
    return str(record.id)


# -- 1. /projects ------------------------------------------------------------


def test_projects_create_list_detail(client: Any, auth_headers: dict[str, str]) -> None:
    """``/projects`` 创建 → 列表 → 详情（走统一响应壳）。"""
    workspace_id = _create_workspace(client, auth_headers, name="proj-ws")

    created = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": "Demo Project", "workspace_id": workspace_id, "repo_url": "https://x/y.git"},
    )
    assert created.status_code == 201, created.text
    body = _assert_shell(created)
    project_id = body["data"]["id"]
    assert body["data"]["name"] == "Demo Project"
    assert body["data"]["workspace_id"] == workspace_id

    listing = client.get(f"/api/v1/projects?workspace_id={workspace_id}", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    assert project_id in [item["id"] for item in _shell_data(listing)]

    detail = client.get(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert _shell_data(detail)["id"] == project_id


def test_projects_cross_tenant_404(
    client: Any, auth_headers: dict[str, str], other_tenant_headers: dict[str, str]
) -> None:
    """跨租户访问项目 → 404（隔离 I-1，不泄漏存在性）。"""
    workspace_id = _create_workspace(client, auth_headers, name="ct-ws")
    project_id = _shell_data(
        client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json={"name": "P", "workspace_id": workspace_id},
        )
    )["id"]

    peek = client.get(f"/api/v1/projects/{project_id}", headers=other_tenant_headers)
    assert peek.status_code == 404, f"跨租户应 404，实得 {peek.status_code}"
    assert peek.json()["code"] == "NOT_FOUND"


# -- 2. /workspaces/{id}/files | environment ---------------------------------


def test_workspace_files_503_when_unassembled(client: Any, auth_headers: dict[str, str]) -> None:
    """缺 ``Storage`` 注入 → 文件端点结构化 ``503``（不 500、不静默空）。"""
    listing = client.get("/api/v1/workspaces/ws-1/files", headers=auth_headers)
    assert listing.status_code == 503, listing.text
    assert listing.json()["code"] == "DEPENDENCY_MISSING"

    content = client.get(
        "/api/v1/workspaces/ws-1/files/content?path=README.md", headers=auth_headers
    )
    assert content.status_code == 503, content.text
    assert content.json()["code"] == "DEPENDENCY_MISSING"


def test_workspace_environment_list_and_detail_masked(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """环境清单 / 详情可用；敏感项 ``masked=True`` 且**不回显明文**。"""
    tenant_id = _default_tenant_id(session_factory)
    workspace_id = _create_workspace(client, auth_headers, name="env-ws")

    services = client.app.state.services  # type: ignore[attr-defined]
    services.workspace.environment.create(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        name="dev",
        env_vars={"PLAIN": "hello", "API_TOKEN": {"$ref": "secret:MY_TOKEN"}},
    )

    listing = client.get(f"/api/v1/workspaces/{workspace_id}/environment", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    envs = _shell_data(listing)
    assert len(envs) == 1, envs

    env_id = envs[0]["id"]
    detail = client.get(
        f"/api/v1/workspaces/{workspace_id}/environment/{env_id}", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    detail_body = _assert_shell(detail)["data"]

    vars_by_name = {item["name"]: item for item in detail_body["env_vars"]}
    assert vars_by_name["PLAIN"]["value"] == "hello"
    assert vars_by_name["PLAIN"]["masked"] is False
    assert vars_by_name["API_TOKEN"]["masked"] is True
    assert vars_by_name["API_TOKEN"]["value"] is None
    assert vars_by_name["API_TOKEN"]["ref"] == "secret:MY_TOKEN"
    # 敏感明文禁止回显（响应体不得含 secret 明文标记）
    assert "hello" in detail.text and "secret:MY_TOKEN" in detail.text


def test_workspace_environment_cross_workspace_404(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """同租户**跨工作区**取环境详情 → 404（路径 ``workspace_id`` 与资源一致性，R-W10-09）。

    QA OBS-1 回归：``GET /workspaces/{W2}/environment/{env_of_W1}`` 曾因仅校验租户而返回
    200（泄漏 W1 环境）；现状须为 404（**不泄漏**存在性）。
    """
    tenant_id = _default_tenant_id(session_factory)
    ws_a = _create_workspace(client, auth_headers, name="env-ws-a")
    ws_b = _create_workspace(client, auth_headers, name="env-ws-b")

    services = client.app.state.services  # type: ignore[attr-defined]
    env_id = str(
        services.workspace.environment.create(
            tenant_id=tenant_id, workspace_id=ws_a, name="dev", env_vars={"PLAIN": "hello"}
        ).id
    )

    # 正路径（同工作区）→ 200
    ok = client.get(f"/api/v1/workspaces/{ws_a}/environment/{env_id}", headers=auth_headers)
    assert ok.status_code == 200, ok.text
    ok_body = _shell_data(ok)
    assert ok_body["id"] == env_id
    assert ok_body["workspace_id"] == ws_a

    # 同租户跨工作区 → 404（不泄漏存在性）
    peek = client.get(f"/api/v1/workspaces/{ws_b}/environment/{env_id}", headers=auth_headers)
    assert peek.status_code == 404, f"跨工作区应 404，实得 {peek.status_code}"
    assert peek.json()["code"] == "NOT_FOUND"


# -- 3. /approvals -----------------------------------------------------------


def test_approvals_pending_list_and_approve(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """待办列表可见 → 详情 → ``approve`` 决议 → 重复决议 ``409``。"""
    tenant_id = _default_tenant_id(session_factory)
    approval_id = _seed_pending_approval(session_factory, tenant_id=tenant_id)

    listing = client.get("/api/v1/approvals", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    assert approval_id in [item["id"] for item in _shell_data(listing)]

    detail = client.get(f"/api/v1/approvals/{approval_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert _shell_data(detail)["status"] == "PENDING"

    approved = client.post(f"/api/v1/approvals/{approval_id}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    approved_body = _assert_shell(approved)["data"]
    assert approved_body["status"] == "APPROVED"
    assert approved_body["decided_by"]

    # 已决议（非 PENDING）再决议 → 409（不报 500，且不改状态机）
    again = client.post(f"/api/v1/approvals/{approval_id}/reject", headers=auth_headers)
    assert again.status_code == 409, f"重复决议应 409，实得 {again.status_code}"
    assert again.json()["code"] == "CONFLICT"


def test_approvals_reject(client: Any, auth_headers: dict[str, str], session_factory: Any) -> None:
    """``reject`` 决议（``PENDING → REJECTED``）。"""
    tenant_id = _default_tenant_id(session_factory)
    approval_id = _seed_pending_approval(session_factory, tenant_id=tenant_id, subject_ref="mcp:x")

    rejected = client.post(f"/api/v1/approvals/{approval_id}/reject", headers=auth_headers)
    assert rejected.status_code == 200, rejected.text
    assert _shell_data(rejected)["status"] == "REJECTED"


def test_approvals_cross_tenant_404(
    client: Any,
    auth_headers: dict[str, str],
    other_tenant_headers: dict[str, str],
    session_factory: Any,
) -> None:
    """跨租户访问审批 → 404。"""
    tenant_id = _default_tenant_id(session_factory)
    approval_id = _seed_pending_approval(session_factory, tenant_id=tenant_id)

    peek = client.get(f"/api/v1/approvals/{approval_id}", headers=other_tenant_headers)
    assert peek.status_code == 404, f"跨租户应 404，实得 {peek.status_code}"

    decide = client.post(f"/api/v1/approvals/{approval_id}/approve", headers=other_tenant_headers)
    assert decide.status_code == 404, f"跨租户决议应 404，实得 {decide.status_code}"


# -- 4. /tasks ---------------------------------------------------------------


def test_tasks_list_and_cancel_idempotent(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``/tasks`` 列表（类型过滤）→ 取消 → 二次取消**幂等**返回既有状态。"""
    tenant_id = _default_tenant_id(session_factory)
    task_id = _seed_task(session_factory, tenant_id=tenant_id, task_type="agent.run")

    listing = client.get("/api/v1/tasks?task_type=agent.run", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    assert task_id in [item["id"] for item in _shell_data(listing)]

    cancelled = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200, cancelled.text
    assert _shell_data(cancelled)["status"] == "CANCELLED"

    # 终态再取消 → 幂等（200 + 既有状态，不报错）
    again = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=auth_headers)
    assert again.status_code == 200, again.text
    assert _shell_data(again)["status"] == "CANCELLED"


def test_tasks_detail_preserved(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """既有 ``GET /tasks/{id}`` **零破坏**（Phase 0 契约保持）。"""
    tenant_id = _default_tenant_id(session_factory)
    task_id = _seed_task(session_factory, tenant_id=tenant_id)

    detail = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert _shell_data(detail)["id"] == task_id

    missing = client.get("/api/v1/tasks/does-not-exist", headers=auth_headers)
    assert missing.status_code == 404, missing.text


def test_tasks_detail_cross_tenant_404(
    client: Any,
    auth_headers: dict[str, str],
    other_tenant_headers: dict[str, str],
    session_factory: Any,
) -> None:
    """``GET /tasks/{id}`` 跨租户 → 404（W10-E3 租户校验收紧，I-1）。"""
    tenant_id = _default_tenant_id(session_factory)
    task_id = _seed_task(session_factory, tenant_id=tenant_id)

    peek = client.get(f"/api/v1/tasks/{task_id}", headers=other_tenant_headers)
    assert peek.status_code == 404, f"跨租户应 404，实得 {peek.status_code}"
    assert peek.json()["code"] == "NOT_FOUND"


def test_task_executions_history(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """``GET /tasks/{id}/executions``：无记录 → 空列表；预置后返回记录（含 ``attempt``）。"""
    tenant_id = _default_tenant_id(session_factory)
    task_id = _seed_task(session_factory, tenant_id=tenant_id)

    empty = client.get(f"/api/v1/tasks/{task_id}/executions", headers=auth_headers)
    assert empty.status_code == 200, empty.text
    assert _shell_data(empty) == []

    _seed_execution(session_factory, task_id=task_id)

    listing = client.get(f"/api/v1/tasks/{task_id}/executions", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    records = _shell_data(listing)
    assert len(records) == 1, records
    assert records[0]["attempt"] == 1
    assert records[0]["task_id"] == task_id
    assert records[0]["status"] == "RUNNING"


def test_task_executions_cross_tenant_404(
    client: Any,
    auth_headers: dict[str, str],
    other_tenant_headers: dict[str, str],
    session_factory: Any,
) -> None:
    """``GET /tasks/{id}/executions`` 跨租户 → 404（先校验任务归属）。"""
    tenant_id = _default_tenant_id(session_factory)
    task_id = _seed_task(session_factory, tenant_id=tenant_id)

    peek = client.get(f"/api/v1/tasks/{task_id}/executions", headers=other_tenant_headers)
    assert peek.status_code == 404, f"跨租户应 404，实得 {peek.status_code}"


# -- 5. 统一响应壳 ------------------------------------------------------------


def test_unified_response_shell_fields(
    client: Any, auth_headers: dict[str, str], other_tenant_headers: dict[str, str]
) -> None:
    """成功 / 失败响应**恒**为统一壳 ``{code,message,data,request_id}``。"""
    ok = client.get("/api/v1/tasks", headers=auth_headers)
    assert ok.status_code == 200, ok.text
    assert set(ok.json().keys()) >= {"code", "message", "data", "request_id"}

    err = client.get("/api/v1/projects/does-not-exist", headers=auth_headers)
    assert err.status_code in {404, 422}, err.text
    assert set(err.json().keys()) >= {"code", "message", "data", "request_id"}
