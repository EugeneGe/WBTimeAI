"""变更审阅（Diff / 显式 Apply / 显式 Push）安全集成测试（R3 / T2-61；``I-P2-40``）。

覆盖（服务层用**真实** ``GitService`` + **脚本化**假 ``SandboxProvider``；API 层用真实
``client``）：

- **权限**：缺 ``git.apply`` / ``git.push`` → **403**；跨租户 → **404**（统一隔离）；API 端点同；
- **基线 / 冲突（保留原状）**：
  · 目标分支**前进**（HEAD ≠ Attempt ``base_commit``）→ **409**，**不**触碰合并；
  · Attempt 工作树**脏** → **409**，**不**触碰合并；
  · 合并**冲突** → **409** + ``merge --abort`` 回滚（目标分支**保持**原提交）；
- **Apply 不 Push**：Apply 全程**不**调用 ``git push``；
- **凭证**：未配置写凭证 → **422**（``CONFIGURATION_ERROR``）；凭证**仅**注入**独立 Push Sandbox**
  的 push 命令 env，**不**出现在响应 / 审计 / Apply 会话；
- **禁强推 / 删分支 / 任意 URL**：``remote=--force`` / ``target_ref=':main'`` / ``'+main'`` /
  ``remote='https://evil/x.git'`` → **403**；
- **前向硬约束**：``checkout_ref`` 经 ``ProjectStorage.resolve_checkout_ref``
  （canonical containment）还原（伪造 / 缺失 ``checkout_ref`` → 结构化错误，
  **不**直接接受宿主路径）。

🔴 **Git 仅经 Sandbox**：本测试**不**启动宿主 Git；全部经脚本化假 ``SandboxProvider.exec``。
"""

from __future__ import annotations

from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_database import SqlTaskExecutionRepository, SqlTaskRepository, session_scope
from astra_domain import SandboxSession
from astra_sandbox import ExecResult
from astra_task import ExecutionRecorder, Task
from astra_workspace import ChangeReviewService, GitService, GitWriteCredential, ProjectStorage
from astra_workspace.application.remote_task_service import (
    REMOTE_TASK_TYPE,
    RemoteAccessDecision,
)
from astra_workspace.repositories import SqlProjectRepository

TENANT = "tenant-t61"
OTHER_TENANT = "tenant-other"
BASE_COMMIT = "a" * 40
RESULT_COMMIT = "b" * 40
ADVANCED_COMMIT = "c" * 40


# -- 测试替身 ----------------------------------------------------------------


class _ScriptedSandbox:
    """脚本化假 ``SandboxProvider``：按 git 子命令返回确定性 ``ExecResult``。"""

    kind = "local_process"
    available = True

    def __init__(
        self,
        *,
        target_head: str = BASE_COMMIT,
        clean: bool = True,
        merge_ok: bool = True,
        push_ok: bool = True,
        push_stdout: str = "",
        diff_output: str = "M\tfile.py\nA\tnew.py\n",
    ) -> None:
        self.target_head = target_head
        self.result_commit = RESULT_COMMIT
        self.clean = clean
        self.merge_ok = merge_ok
        self.push_ok = push_ok
        self.push_stdout = push_stdout
        self.diff_output = diff_output
        self._merged = False
        self.calls: list[tuple[str, list[str], dict[str, str], str | None]] = []
        self.sessions: list[SandboxSession] = []
        self.destroyed: int = 0

    def create_session(self, **kwargs: Any) -> SandboxSession:
        session = SandboxSession(workspace_id=kwargs.get("workspace_id"))
        self.sessions.append(session)
        return session

    def exec(  # noqa: A003 - 与 Protocol 语义一致
        self,
        session: SandboxSession,
        command: Any,
        *,
        timeout_ms: int | None = None,
        env: Any = None,
        cwd: str | None = None,
    ) -> ExecResult:
        args = [command] if isinstance(command, str) else list(command)
        sub = args[1] if len(args) > 1 and args[0] == "git" else ""
        self.calls.append((sub, args, dict(env or {}), cwd))
        if sub == "rev-parse":
            head = self.result_commit if self._merged else self.target_head
            return ExecResult(exit_code=0, stdout=head)
        if sub == "status":
            return ExecResult(exit_code=0, stdout="" if self.clean else " M dirty.py\n")
        if sub == "diff":
            return ExecResult(exit_code=0, stdout=self.diff_output)
        if sub == "merge":
            if "--abort" in args:
                self._merged = False
                return ExecResult(exit_code=0)
            if self.merge_ok:
                self._merged = True
                return ExecResult(exit_code=0)
            return ExecResult(exit_code=1, stderr="CONFLICT")
        if sub == "fetch":
            return ExecResult(exit_code=0)
        if sub == "push":
            return ExecResult(exit_code=0 if self.push_ok else 1, stdout=self.push_stdout)
        return ExecResult(exit_code=0)

    def put_file(  # pragma: no cover
        self, session: SandboxSession, path: str, content: str
    ) -> None:
        return None

    def get_file(self, session: SandboxSession, path: str) -> str:  # pragma: no cover
        return ""

    def destroy(self, session: SandboxSession) -> None:
        self.destroyed += 1

    def push_calls(self) -> list[tuple[str, list[str], dict[str, str], str | None]]:
        return [call for call in self.calls if call[0] == "push"]

    def merge_calls(self) -> list[tuple[str, list[str], dict[str, str], str | None]]:
        return [call for call in self.calls if call[0] == "merge"]


class _FakeAuthorizer:
    """假授权器：按授予的 capability 集合判定（记录调用）。"""

    def __init__(self, allowed: set[str]) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, str | None]] = []

    def authorize(
        self,
        principal: Any,
        *,
        capability: str,
        resource_type: str = "TASK",
        resource_id: str | None = None,
    ) -> RemoteAccessDecision:
        self.calls.append((capability, resource_id))
        ok = capability in self.allowed
        return RemoteAccessDecision(allowed=ok, in_scope=ok, reason="test")


class _RecordingAudit:
    """假审计出口（记录 metadata）。"""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _FakeCredentials:
    """假写凭证提供者（返回注入凭证或 ``None``）。"""

    def __init__(self, credential: GitWriteCredential | None) -> None:
        self._credential = credential

    def write_credentials(self, *, tenant_id: str, project_id: str) -> GitWriteCredential | None:
        return self._credential


class _ProjectsAdapter:
    """``ProjectRepository`` 适配（风格① 仓储逐调用短时会话）。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def get(self, project_id: str) -> Any:
        with session_scope(self._session_factory) as session:
            return SqlProjectRepository(session).get(project_id)


# -- 夹具 --------------------------------------------------------------------


@pytest.fixture
def principal() -> Any:
    """默认租户调用主体。"""
    from astra_workspace import RemotePrincipal

    return RemotePrincipal(tenant_id=TENANT, user_id="user-1")


def _seed_project(session_factory: Any) -> Any:
    """经 ``ProjectService`` 建一个带仓库地址的项目。"""
    from astra_workspace import ProjectService

    return ProjectService(session_factory).create(
        tenant_id=TENANT,
        workspace_id="ws-1",
        name="proj",
        repo_url="https://example.com/repo.git",
        default_branch="main",
    )


def _seed_task(session_factory: Any, *, project_id: str, tenant_id: str = TENANT) -> str:
    """建一个**远程**任务（载荷含 ``project_id``）。"""
    task = Task(
        tenant_id=tenant_id,
        workspace_id="ws-1",
        type=REMOTE_TASK_TYPE,
        execution_mode="QUEUED",
        payload={"project_id": project_id},
    )
    return str(SqlTaskRepository(session_factory).add(task).task_id)


def _seed_attempt(
    session_factory: Any,
    *,
    task_id: str,
    storage: ProjectStorage,
    checkout_ref: str | None = None,
) -> str:
    """经 ``ExecutionRecorder`` 预置一条已完成 Attempt（含不透明 ``checkout_ref``）。"""
    repository = SqlTaskExecutionRepository(session_factory)
    recorder = ExecutionRecorder(repository)
    record = recorder.claim(
        task_id=task_id,
        attempt=1,
        checkout_ref=checkout_ref or storage.checkout_ref("pending", 1),
        base_commit=BASE_COMMIT,
        environment_digest="d" * 64,
    )
    record.result_commit = RESULT_COMMIT
    record.checkout_ref = checkout_ref or storage.checkout_ref(str(record.id), 1)
    repository.update(record)
    return str(record.id)


def _build(
    session_factory: Any,
    tmp_path: Any,
    *,
    sandbox: _ScriptedSandbox | None = None,
    allowed: set[str] | None = None,
    credential: GitWriteCredential | None = None,
) -> tuple[ChangeReviewService, _ScriptedSandbox, _RecordingAudit, _FakeAuthorizer]:
    """构造 [服务 + 沙箱 + 审计 + 授权器] 四元组。"""
    sandbox = sandbox or _ScriptedSandbox()
    audit = _RecordingAudit()
    authorizer = _FakeAuthorizer(allowed or {"git.apply", "git.push", "git.diff"})
    storage = ProjectStorage(tmp_path / "wsroot")
    service = ChangeReviewService(
        tasks=SqlTaskRepository(session_factory),
        executions=SqlTaskExecutionRepository(session_factory),
        projects=_ProjectsAdapter(session_factory),
        git=GitService(sandbox),
        sandbox=sandbox,
        storage=storage,
        authorizer=authorizer,
        audit=audit,
        credentials=_FakeCredentials(credential),
    )
    return service, sandbox, audit, authorizer


# -- 1. 权限 ----------------------------------------------------------------


def test_apply_requires_capability(session_factory: Any, tmp_path: Any, principal: Any) -> None:
    """缺 ``git.apply`` → 403（且**不**触发任何 git 调用）。"""
    service, sandbox, _audit, _auth = _build(session_factory, tmp_path, allowed={"git.push"})
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.apply(principal, task_id)
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert sandbox.calls == []


def test_push_requires_capability(session_factory: Any, tmp_path: Any, principal: Any) -> None:
    """缺 ``git.push`` → 403（且**不**触发任何 git 调用）。"""
    service, sandbox, _audit, _auth = _build(
        session_factory, tmp_path, allowed={"git.apply"}, credential=GitWriteCredential(token="t")
    )
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.push(principal, task_id)
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert sandbox.calls == []


def test_cross_tenant_apply_is_404(session_factory: Any, tmp_path: Any) -> None:
    """跨租户 Apply → 404（统一隔离，不泄漏存在性）。"""
    from astra_workspace import RemotePrincipal

    service, _sandbox, _audit, _auth = _build(session_factory, tmp_path)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id, tenant_id=OTHER_TENANT)
    intruder = RemotePrincipal(tenant_id=TENANT, user_id="x")

    with pytest.raises(DomainError) as excinfo:
        service.apply(intruder, task_id)
    assert excinfo.value.code is ErrorCode.NOT_FOUND


# -- 2. 基线 / 冲突（保留原状） ---------------------------------------------


def test_apply_happy_applies_to_target_without_push(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """正常 Apply：更新目标分支 + **不** Push；返回 ``applied_commit``。"""
    service, sandbox, audit, _auth = _build(session_factory, tmp_path)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    result = service.apply(principal, task_id)
    assert result.target_ref == "main"
    assert result.result_commit == RESULT_COMMIT
    assert result.applied_commit == RESULT_COMMIT
    # Apply **不** Push。
    assert sandbox.push_calls() == []
    # 审计写入（成功）。
    assert any(rec["action"] == "task.remote.apply" for rec in audit.records)


def test_apply_target_advanced_is_conflict_and_preserves(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """目标分支前进（HEAD ≠ base）→ 409，**不**触碰合并（保留原状）。"""
    sandbox = _ScriptedSandbox(target_head=ADVANCED_COMMIT)
    service, sandbox, _audit, _auth = _build(session_factory, tmp_path, sandbox=sandbox)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.apply(principal, task_id)
    assert excinfo.value.code is ErrorCode.CONFLICT
    assert excinfo.value.status_code == 409
    assert sandbox.merge_calls() == []  # 未合并 → 原状保留


def test_apply_dirty_worktree_is_conflict_and_preserves(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """Attempt 工作树脏 → 409，**不**触碰合并。"""
    sandbox = _ScriptedSandbox(clean=False)
    service, sandbox, _audit, _auth = _build(session_factory, tmp_path, sandbox=sandbox)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.apply(principal, task_id)
    assert excinfo.value.code is ErrorCode.CONFLICT
    assert sandbox.merge_calls() == []


def test_apply_merge_conflict_is_conflict_and_aborts(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """合并冲突 → 409 且 ``merge --abort`` 回滚（保留原状）。"""
    sandbox = _ScriptedSandbox(merge_ok=False)
    service, sandbox, _audit, _auth = _build(session_factory, tmp_path, sandbox=sandbox)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.apply(principal, task_id)
    assert excinfo.value.code is ErrorCode.CONFLICT
    aborts = [call for call in sandbox.merge_calls() if "--abort" in call[1]]
    assert aborts, "冲突后必须 merge --abort 回滚"


# -- 3. 凭证 ----------------------------------------------------------------


def test_push_without_credential_is_422(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """未配置写凭证 → 422 ``CONFIGURATION_ERROR``（且**不**触发 push）。"""
    service, sandbox, _audit, _auth = _build(session_factory, tmp_path, credential=None)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.push(principal, task_id)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert sandbox.push_calls() == []


def test_push_uses_credential_only_in_push_sandbox(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """凭证**仅**注入 push 命令 env；**不**出现在响应 / 审计。"""
    credential = GitWriteCredential(username="x-access-token", token="s3cr3t-token")
    service, sandbox, audit, _auth = _build(session_factory, tmp_path, credential=credential)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    result = service.push(principal, task_id)
    assert result.pushed is True
    pushes = sandbox.push_calls()
    assert len(pushes) == 1
    push_env = pushes[0][2]
    assert push_env.get("ASTRA_GIT_PASSWORD") == "s3cr3t-token"
    # 凭证**不**出现在响应 / 审计。
    assert "s3cr3t-token" not in repr(result)
    assert all("s3cr3t-token" not in str(rec) for rec in audit.records)
    # 其余非 push 命令 **不**携带凭证。
    for sub, _args, env, _cwd in sandbox.calls:
        if sub != "push":
            assert "ASTRA_GIT_PASSWORD" not in env


# -- 4. 禁强推 / 删分支 / 任意 URL ------------------------------------------


@pytest.mark.parametrize("target_ref", ["+main", ":main"])
def test_push_rejects_force_and_branch_delete(
    session_factory: Any, tmp_path: Any, principal: Any, target_ref: str
) -> None:
    """``+main``（强推）/ ``:main``（删远端分支）→ 403（且**不**触发 push）。"""
    credential = GitWriteCredential(token="t")
    service, sandbox, _audit, _auth = _build(session_factory, tmp_path, credential=credential)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.push(principal, task_id, target_ref=target_ref)
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert sandbox.push_calls() == []


def test_push_rejects_arbitrary_url(session_factory: Any, tmp_path: Any, principal: Any) -> None:
    """``remote='https://evil/x.git'`` → 403（任意 URL）。"""
    credential = GitWriteCredential(token="t")
    service, sandbox, _audit, _auth = _build(session_factory, tmp_path, credential=credential)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.push(principal, task_id, remote="https://evil/x.git")
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert sandbox.push_calls() == []


# -- 5. 前向硬约束：checkout_ref 经 canonical containment -------------------


def test_apply_rejects_foreign_checkout_ref(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """伪造 / 非法 ``checkout_ref`` → 结构化 ``VALIDATION_ERROR``（**不**直接接受宿主路径）。"""
    service, _sandbox, _audit, _auth = _build(session_factory, tmp_path)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    # 伪造：直接塞入一个**宿主路径**冒充 checkout_ref（非 wr_ 前缀）。
    _seed_attempt(
        session_factory, task_id=task_id, storage=service.storage, checkout_ref="C:/host/escape"
    )  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.apply(principal, task_id)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_diff_returns_limited_file_summary(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """受限 Diff：由 ``--name-status`` 生成文件摘要（**不含**宿主路径）。"""
    service, _sandbox, _audit, _auth = _build(session_factory, tmp_path)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    view = service.diff(principal, task_id)
    assert view.available is True
    assert [f.path for f in view.files] == ["file.py", "new.py"]
    assert [f.change_type for f in view.files] == ["modified", "added"]
    assert view.checkout_ref is not None and "/" not in view.checkout_ref


# -- 6. API 端点（冻结路径 ``POST /tasks/{task_id}/apply`` · ``/push``；F-R6 / F-R7） --
#
# 🔴 冻结路径（team-lead 裁决）：``POST /tasks/{task_id}/apply`` + ``POST /tasks/{task_id}/push``
#    ——**不是** ``/tasks/{task_id}/diff/apply``（派单路径 vs 冻结路径不一致 → 以冻结为准）。


def _api_shell_data(resp: Any) -> Any:
    """取统一响应壳的 ``data``（``{code,message,data,request_id}``）；非壳原样返回。"""
    body = resp.json()
    if isinstance(body, dict) and "data" in body and "code" in body:
        return body["data"]
    return body


def _api_seed_remote_task(
    client: Any, headers: dict[str, str], *, name: str
) -> tuple[str, str, str]:
    """经 API 建 [工作区 + 带仓库项目 + 远程任务]，返回 ``(workspace_id, project_id, task_id)``。"""
    ws_resp = client.post("/api/v1/workspaces", headers=headers, json={"name": f"{name}-ws"})
    assert ws_resp.status_code == 201, ws_resp.text
    ws_id = str(_api_shell_data(ws_resp)["id"])
    proj_resp = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "workspace_id": ws_id, "repo_url": f"https://x/{name}.git"},
    )
    assert proj_resp.status_code == 201, proj_resp.text
    project_id = str(_api_shell_data(proj_resp)["id"])
    task_resp = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "agent_version_id": "av-1",
            "requirement": "do the thing",
        },
    )
    assert task_resp.status_code == 202, task_resp.text
    task_id = str(_api_shell_data(task_resp)["task_id"])
    return ws_id, project_id, task_id


def test_apply_endpoint_requires_capability(
    client: Any, auth_headers: dict[str, str], permissionless_headers: dict[str, str]
) -> None:
    """``POST /tasks/{task_id}/apply``：无足迹用户 → 403（不静默、不触碰工作区）。"""
    _ws, _proj, task_id = _api_seed_remote_task(client, auth_headers, name="api-apply")
    denied = client.post(f"/api/v1/tasks/{task_id}/apply", headers=permissionless_headers, json={})
    assert denied.status_code == 403, denied.text
    assert denied.json()["code"] == "PERMISSION_DENIED"


def test_push_endpoint_requires_capability(
    client: Any, auth_headers: dict[str, str], permissionless_headers: dict[str, str]
) -> None:
    """``POST /tasks/{task_id}/push``：无足迹用户 → 403（**独立**权限，不越权复用 Apply）。"""
    _ws, _proj, task_id = _api_seed_remote_task(client, auth_headers, name="api-push")
    denied = client.post(f"/api/v1/tasks/{task_id}/push", headers=permissionless_headers, json={})
    assert denied.status_code == 403, denied.text
    assert denied.json()["code"] == "PERMISSION_DENIED"


def test_change_review_cross_tenant_is_404(
    client: Any, auth_headers: dict[str, str], other_tenant_headers: dict[str, str]
) -> None:
    """跨租户 Apply / Push → 404（统一隔离，不泄漏存在性）。"""
    _ws, _proj, task_id = _api_seed_remote_task(client, auth_headers, name="api-ct")
    for path in (
        f"/api/v1/tasks/{task_id}/apply",
        f"/api/v1/tasks/{task_id}/push",
    ):
        resp = client.post(path, headers=other_tenant_headers, json={})
        assert resp.status_code == 404, f"{path} 应 404，实得 {resp.status_code}: {resp.text}"
        assert resp.json()["code"] == "NOT_FOUND"


def test_apply_uses_frozen_path_not_diff_apply(
    client: Any, auth_headers: dict[str, str], permissionless_headers: dict[str, str]
) -> None:
    """冻结路径存在（缺能力 → 403，证明路由可达）；派单路径 ``/diff/apply`` **未**注册 → 404。"""
    _ws, _proj, task_id = _api_seed_remote_task(client, auth_headers, name="api-frozen")
    frozen = client.post(f"/api/v1/tasks/{task_id}/apply", headers=permissionless_headers, json={})
    assert frozen.status_code == 403, frozen.text
    legacy = client.post(
        f"/api/v1/tasks/{task_id}/diff/apply", headers=permissionless_headers, json={}
    )
    assert legacy.status_code == 404, legacy.text
