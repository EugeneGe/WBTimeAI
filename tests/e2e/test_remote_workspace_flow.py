"""远程工作站**主链路**端到端（R5 / T2-63；设计 §3 #34/#35/#37/#39/#41；D15–D18）。

**纵切**（真实 HTTP / ``TestClient`` / 真实 SQLite；**零真实 Git 进程 / 零 Docker / 零网络**）：

    Workspace → Project → 异步 Clone（202） → 远程提交（202） → 持久化 Attempt
    → 运行视图（Attempt 计数 / 不透明 checkout_ref） → 事件**断点续读**（不透明 cursor）
    → 日志 / Diff（``200 + available`` 降级） → Apply / Push（冻结路径） → 取消（终态幂等）

**本地面 / 服务器面切分**（A-12：Manual 非豁免）：

- **本地面（必绿）**：控制面契约、隔离（404）、幂等提交、事件续读不重不漏、Diff 降级、
  冻结路径可达；Apply / Push 在本机**显式注入「未装配 Git」**（同 T2-62 e2e 手法）→ 确定性
  **503**（``DEPENDENCY_MISSING``），证明**控制面**闭环。
- **服务器面（挂账）**：真实 Clone → 运行 → Diff 内容 / Apply 落库 / Push 到远端 /
  Sandbox 出网阻断 —— 见 ``manual-checklists/phase2-remote-server.md``，由指定环境责任人执行留存。

🔴 不启动本地 Build / Test / Agent；结果默认**不** Push。
"""

from __future__ import annotations

from typing import Any


def _data(resp: Any) -> Any:
    """取统一响应壳的 ``data``（``{code,message,data,request_id}``）。"""
    body = resp.json()
    if isinstance(body, dict) and "data" in body and "code" in body:
        return body["data"]
    return body


def _seed_execution(
    session_factory: Any,
    *,
    task_id: str,
    attempt: int,
    checkout_ref: str,
    result_commit: str | None,
) -> None:
    """预置一条 Attempt（含不透明 ``checkout_ref``；``result_commit`` 可缺省）。"""
    from astra_database import SqlTaskExecutionRepository
    from astra_task import ExecutionRecorder

    repository = SqlTaskExecutionRepository(session_factory)
    record = ExecutionRecorder(repository).claim(
        task_id=task_id,
        attempt=attempt,
        checkout_ref=checkout_ref,
        base_commit="a" * 40,
        environment_digest="d" * 64,
    )
    record.result_commit = result_commit
    repository.update(record)


def _bootstrap(client: Any, headers: dict[str, str], *, name: str) -> tuple[str, str]:
    """建 [Workspace + 带仓库 Project]，返回 ``(workspace_id, project_id)``。"""
    ws = client.post("/api/v1/workspaces", headers=headers, json={"name": f"{name}-ws"})
    assert ws.status_code == 201, ws.text
    ws_id = str(_data(ws)["id"])
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": name,
            "workspace_id": ws_id,
            "repo_url": f"https://x/{name}.git",
            "default_branch": "main",
        },
    )
    assert project.status_code == 201, project.text
    return ws_id, str(_data(project)["id"])


def _submit(
    client: Any, headers: dict[str, str], *, ws_id: str, project_id: str, key: str | None = None
) -> str:
    """远程提交任务，返回 ``task_id``。"""
    payload: dict[str, Any] = {
        "workspace_id": ws_id,
        "project_id": project_id,
        "agent_version_id": "av-1",
        "requirement": "do the thing",
    }
    if key is not None:
        payload["idempotency_key"] = key
    created = client.post("/api/v1/tasks", headers=headers, json=payload)
    assert created.status_code == 202, created.text
    return str(_data(created)["task_id"])


# ---------------------------------------------------------------------------
# 1. 主链路：Project → Clone → Task → 视图 → 取消
# ---------------------------------------------------------------------------


def test_remote_project_clone_and_task_view(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """Project Clone（202）+ 远程提交（202）+ 运行视图（Attempt 计数 / 不透明 ref）+ 取消幂等。"""
    ws_id, project_id = _bootstrap(client, auth_headers, name="flow")

    clone = client.post(
        f"/api/v1/projects/{project_id}/clone", headers=auth_headers, json={"base_ref": "main"}
    )
    assert clone.status_code == 202, clone.text
    assert _data(clone).get("task_id")

    status = client.get(f"/api/v1/projects/{project_id}/status", headers=auth_headers)
    assert status.status_code == 200, status.text
    assert _data(status)["repo_configured"] is True

    task_id = _submit(client, auth_headers, ws_id=ws_id, project_id=project_id)
    _seed_execution(
        session_factory,
        task_id=task_id,
        attempt=1,
        checkout_ref="wr_flow_opaque",
        result_commit="b" * 40,
    )

    view = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert view.status_code == 200, view.text
    data = _data(view)
    assert data["attempt_count"] == 1
    assert data["checkout_ref"] == "wr_flow_opaque"
    assert "/" not in data["checkout_ref"]  # 不透明、无宿主路径

    # 取消：终态幂等。
    first = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=auth_headers)
    assert first.status_code == 200, first.text
    second = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=auth_headers)
    assert second.status_code == 200, second.text
    assert _data(second)["status"] == _data(first)["status"]


# ---------------------------------------------------------------------------
# 2. 幂等提交（#35 / D16：重复 idempotency key 不创建第二个任务）
# ---------------------------------------------------------------------------


def test_remote_submit_idempotency(client: Any, auth_headers: dict[str, str]) -> None:
    """同 ``idempotency_key`` 二次提交 → **同一** ``task_id``（不重复创建）。"""
    ws_id, project_id = _bootstrap(client, auth_headers, name="idem")
    key = "idem-key-0001"
    first = _submit(client, auth_headers, ws_id=ws_id, project_id=project_id, key=key)
    second = _submit(client, auth_headers, ws_id=ws_id, project_id=project_id, key=key)
    assert first == second


# ---------------------------------------------------------------------------
# 3. 事件断点续读（#35 / D16：不重复、不遗漏；seq 单调）
# ---------------------------------------------------------------------------


def test_remote_events_resume_with_cursor(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """事件续读：不透明 cursor **续读不重不漏**；``seq`` **页内严格单调**。

    R5Q-04（断言去条件化）：**不再**因续读页为空而**跳过**排序断言；改为无条件断言
    「两页不重复」+「末页无新事件（续读幂等）**或** 新事件严格晚于基线页」的**析取**，
    并对续读 cursor **稳定性**（幂等重放锚点）与 ``Last-Event-ID`` 回退**去重**校验。
    """
    ws_id, project_id = _bootstrap(client, auth_headers, name="events")
    task_id = _submit(client, auth_headers, ws_id=ws_id, project_id=project_id)
    _seed_execution(
        session_factory, task_id=task_id, attempt=1, checkout_ref="wr_evt_1", result_commit="b" * 40
    )
    _seed_execution(
        session_factory, task_id=task_id, attempt=2, checkout_ref="wr_evt_2", result_commit="c" * 40
    )

    page1 = client.get(f"/api/v1/tasks/{task_id}/events", headers=auth_headers)
    assert page1.status_code == 200, page1.text
    body1 = _data(page1)
    seqs_1 = [int(e["seq"]) for e in body1["events"]]

    # (1) 去条件化：基线页**必非空**（已 seed 2 个 Attempt ⇒ 至少 2 条 ``attempt.started``）。
    assert seqs_1, "续读基线页不应为空（已 seed 2 个 Attempt）"
    # (2) 页内**严格**单调递增（无重复、无倒序）—— **无条件**断言。
    # ``seqs_1[1:]`` 刻意丢弃首元素 → 两序列**必然不等长**（差 1）→ 显式 ``strict=False``：
    # 保持原「相邻对」语义（``strict=True`` 会因长度不等抛 ``ValueError``，属行为变化）。
    assert all(b > a for a, b in zip(seqs_1, seqs_1[1:], strict=False)), seqs_1
    # (3) 强化 cursor 断言（替代近永真的 ``isinstance(str)``）：**非空**不透明句柄、无路径分隔。
    cursor = body1.get("next_cursor")
    assert isinstance(cursor, str) and cursor, cursor
    assert "/" not in cursor and "\\" not in cursor

    page2 = client.get(
        f"/api/v1/tasks/{task_id}/events",
        headers=auth_headers,
        params={"cursor": cursor},
    )
    assert page2.status_code == 200, page2.text
    body2 = _data(page2)
    seqs_2 = [int(e["seq"]) for e in body2["events"]]
    # (4) **无条件**：两页 **不重复**（无重放）。
    assert not (set(seqs_1) & set(seqs_2))
    # (5) **无条件析取**：末页无新事件（续读幂等）**或** 新事件**严格晚于**基线页（不重不漏）。
    assert (not seqs_2) or (min(seqs_2) > max(seqs_1)), (seqs_1, seqs_2)
    # (6) 末页 cursor **稳定**（幂等重放锚点）。
    assert body2.get("next_cursor") == cursor

    # (7) ``Last-Event-ID`` 回退：只回放 ``seq > anchor``（去重、不重放、不引入新事件）。
    anchor = seqs_1[0]
    replay = client.get(
        f"/api/v1/tasks/{task_id}/events",
        headers={**auth_headers, "Last-Event-ID": str(anchor)},
    )
    assert replay.status_code == 200, replay.text
    replay_seqs = [int(e["seq"]) for e in _data(replay)["events"]]
    assert replay_seqs, "Last-Event-ID 回退不应为空（存在 seq > anchor 的事件）"
    assert min(replay_seqs) > anchor
    assert set(replay_seqs).issubset(set(seqs_1))


# ---------------------------------------------------------------------------
# 4. Diff 降级（本地：200 + available；不伪造、不泄漏宿主路径）
# ---------------------------------------------------------------------------


def test_remote_diff_degrades_without_host_paths(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """Diff 读取以 ``200 + available`` 降级（**不** 503）；输出不含宿主路径 / 令牌。"""
    ws_id, project_id = _bootstrap(client, auth_headers, name="diff")
    task_id = _submit(client, auth_headers, ws_id=ws_id, project_id=project_id)
    # 缺 result_commit → available=false（本地面确定性降级）。
    _seed_execution(
        session_factory, task_id=task_id, attempt=1, checkout_ref="wr_diff_1", result_commit=None
    )

    resp = client.get(f"/api/v1/tasks/{task_id}/diff", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = _data(resp)
    assert data["available"] is False  # 缺可比提交 → 降级
    assert ":/" not in resp.text and "\\\\" not in resp.text


# ---------------------------------------------------------------------------
# 5. 控制面闭环：Apply / Push 冻结路径（本地注入未装配 Git → 确定性 503）
# ---------------------------------------------------------------------------


def test_remote_apply_push_frozen_paths_unassembled_locally(
    client: Any, auth_headers: dict[str, str], session_factory: Any
) -> None:
    """Apply = ``/tasks/{id}/apply``、Push = ``/tasks/{id}/push``（**非** ``/diff/apply``）。

    本机注入「未装配 Git」→ 确定性 **503**（``DEPENDENCY_MISSING``）；真实落库 / 推送归服务器面。
    """
    ws_id, project_id = _bootstrap(client, auth_headers, name="apply")
    task_id = _submit(client, auth_headers, ws_id=ws_id, project_id=project_id)
    _seed_execution(
        session_factory,
        task_id=task_id,
        attempt=1,
        checkout_ref="wr_apply_1",
        result_commit="b" * 40,
    )

    client.app.state.services.change_review._git = None  # noqa: SLF001 - 注入未装配态（本地面）

    frozen = client.post(
        f"/api/v1/tasks/{task_id}/apply", headers=auth_headers, json={"target_ref": "main"}
    )
    assert frozen.status_code == 503, frozen.text
    assert frozen.json()["code"] == "DEPENDENCY_MISSING"

    push = client.post(
        f"/api/v1/tasks/{task_id}/push",
        headers=auth_headers,
        json={"target_ref": "main", "remote": "origin"},
    )
    assert push.status_code == 503, push.text

    legacy = client.post(
        f"/api/v1/tasks/{task_id}/diff/apply", headers=auth_headers, json={"target_ref": "main"}
    )
    assert legacy.status_code == 404  # 冻结路径未注册
