"""远程工作站**安全边界**独立测试（R5 / T2-63；设计 §3 #36/#38/#39/#42；N5 / D17 / D19）。

覆盖五类**边界不变量**（本地可跑：真实 ``create_app`` + SQLite；Git 经脚本化假 ``SandboxProvider``，
**零真实进程 / 零 Docker / 零网络**）：

1. **资源越权**（#36/#39）：跨租户取 Task → **404**；无 capability 列举 / 变更 → **403**；
   跨租户 Apply / Push → **404**（统一隔离，不泄漏存在性）。
2. **路径逃逸**（#36）：伪造宿主路径 ``checkout_ref`` / ``..`` 穿越 → **VALIDATION_ERROR**；
   ``ProjectStorage`` canonical containment 保证 Attempt 目录**恒在 root 之内**。
3. **Secret 泄漏**（#38）：写凭证**仅**注入 Push 命令 env，**不出现在**响应 / 审计；远程视图
   仅暴露不透明 ``checkout_ref``（**无**宿主路径 / 令牌）。
4. **Git 写权限**（#37）：Push **独立** capability（有 Apply 无 Push → 403）；无写凭证 → **422**；
   拒强推 ``+b`` / 删分支 ``:b`` / 任意 URL。
5. **网络绕过**（#42/N10·D19）：EgressPolicy 默认拒全部 + 私网 / 元数据 / DNS rebinding 全拒；
   真实 **Docker / Compose** 网络隔离断言**挂账待服务器**（``docker`` 标记，缺运行时 skip）。

> 口径来源：B3B（越权 403/404 分裂）、B3C（Apply/Push 安全 + 凭证隔离）、R4（CLI/Web 令牌与
> 宿主路径纪律）——均在此**正式化**为可回归用例。

🔴 **Git 仅经 Sandbox**：不启动宿主 Git；🔴 Docker / Compose 档隔离强度归 T2-63 服务器验收。
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_database import SqlTaskExecutionRepository, SqlTaskRepository, session_scope
from astra_domain.ports.egress import METADATA_IPS
from astra_sandbox import ExecResult
from astra_security.egress import SecurityEgressPolicy
from astra_task import ExecutionRecorder, Task
from astra_workspace import ChangeReviewService, GitService, GitWriteCredential, ProjectStorage
from astra_workspace.application.remote_task_service import REMOTE_TASK_TYPE, RemoteAccessDecision
from astra_workspace.paths import ManagedWorkspacePaths
from astra_workspace.repositories import SqlProjectRepository

pytestmark = pytest.mark.security

TENANT = "tenant-sec"
BASE_COMMIT = "a" * 40
RESULT_COMMIT = "b" * 40


# ===========================================================================
# 测试替身 / 夹具
# ===========================================================================


class _ScriptedSandbox:
    """脚本化假 ``SandboxProvider``：按 git 子命令返回确定性 ``ExecResult``（记录 env / cwd）。"""

    kind = "local_process"
    available = True

    def __init__(self, *, push_ok: bool = True) -> None:
        self.push_ok = push_ok
        self.calls: list[tuple[str, list[str], dict[str, str], str | None]] = []

    def create_session(self, **kwargs: Any) -> Any:
        from astra_domain import SandboxSession

        return SandboxSession(workspace_id=kwargs.get("workspace_id"))

    def exec(
        self,
        session: Any,
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
            return ExecResult(exit_code=0, stdout=BASE_COMMIT)
        if sub == "status":
            return ExecResult(exit_code=0, stdout="")
        if sub == "push":
            return ExecResult(exit_code=0 if self.push_ok else 1)
        return ExecResult(exit_code=0)

    def put_file(self, session: Any, path: str, content: str) -> None:  # pragma: no cover
        return None

    def get_file(self, session: Any, path: str) -> str:  # pragma: no cover
        return ""

    def destroy(self, session: Any) -> None:
        return None

    def subs(self) -> list[str]:
        return [sub for sub, _a, _e, _c in self.calls]

    def push_env(self) -> list[dict[str, str]]:
        return [env for sub, _a, env, _c in self.calls if sub == "push"]


class _FakeAuthorizer:
    """假授权器：按授予 capability 集合判定（记录调用）。"""

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
    """假审计出口（记录整条 metadata，供凭证泄漏扫描）。"""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _FakeCredentials:
    """假写凭证提供者。"""

    def __init__(self, credential: GitWriteCredential | None) -> None:
        self._credential = credential

    def write_credentials(self, *, tenant_id: str, project_id: str) -> GitWriteCredential | None:
        return self._credential


class _ProjectsAdapter:
    """``ProjectRepository`` 适配（仓储逐调用短时会话）。"""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def get(self, project_id: str) -> Any:
        with session_scope(self._session_factory) as session:
            return SqlProjectRepository(session).get(project_id)


@pytest.fixture
def principal() -> Any:
    """默认租户调用主体。"""
    from astra_workspace import RemotePrincipal

    return RemotePrincipal(tenant_id=TENANT, user_id="user-sec")


def _seed_project(session_factory: Any) -> Any:
    from astra_workspace import ProjectService

    return ProjectService(session_factory).create(
        tenant_id=TENANT,
        workspace_id="ws-1",
        name="sec-proj",
        repo_url="https://example.com/repo.git",
        default_branch="main",
    )


def _seed_task(session_factory: Any, *, project_id: str, tenant_id: str = TENANT) -> str:
    task = Task(
        tenant_id=tenant_id,
        workspace_id="ws-1",
        type=REMOTE_TASK_TYPE,
        execution_mode="QUEUED",
        payload={"project_id": project_id},
    )
    return str(SqlTaskRepository(session_factory).add(task).task_id)


def _seed_attempt(
    session_factory: Any, *, task_id: str, storage: ProjectStorage, checkout_ref: str | None = None
) -> None:
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


def _build(
    session_factory: Any,
    tmp_path: Any,
    *,
    allowed: set[str] | None = None,
    credential: GitWriteCredential | None = None,
    sandbox: _ScriptedSandbox | None = None,
) -> tuple[ChangeReviewService, _ScriptedSandbox, _RecordingAudit]:
    sandbox = sandbox or _ScriptedSandbox()
    audit = _RecordingAudit()
    storage = ProjectStorage(tmp_path / "wsroot")
    service = ChangeReviewService(
        tasks=SqlTaskRepository(session_factory),
        executions=SqlTaskExecutionRepository(session_factory),
        projects=_ProjectsAdapter(session_factory),
        git=GitService(sandbox),
        sandbox=sandbox,
        storage=storage,
        authorizer=_FakeAuthorizer(allowed or {"git.apply", "git.push", "git.diff"}),
        audit=audit,
        credentials=_FakeCredentials(credential),
    )
    return service, sandbox, audit


def _shell(resp: Any) -> dict[str, Any]:
    body = resp.json()
    return body if isinstance(body, dict) else {}


def _api_seed_remote_task(client: Any, headers: dict[str, str], *, name: str) -> str:
    """经 API 建 [工作区 + 带仓库项目 + 远程任务]，返回 ``task_id``。"""
    ws = client.post("/api/v1/workspaces", headers=headers, json={"name": f"{name}-ws"})
    assert ws.status_code == 201, ws.text
    ws_id = str(_shell(ws)["data"]["id"])
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "workspace_id": ws_id, "repo_url": f"https://x/{name}.git"},
    )
    assert project.status_code == 201, project.text
    project_id = str(_shell(project)["data"]["id"])
    task = client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "workspace_id": ws_id,
            "project_id": project_id,
            "agent_version_id": "av-1",
            "requirement": "x",
        },
    )
    assert task.status_code == 202, task.text
    return str(_shell(task)["data"]["task_id"])


# ===========================================================================
# 1. 资源越权（#36 / #39）
# ===========================================================================


def test_cross_tenant_task_read_is_404(
    client: Any, auth_headers: dict[str, str], other_tenant_headers: dict[str, str]
) -> None:
    """跨租户 ``GET /tasks/{id}`` → 404（**不**泄漏存在性）。"""
    task_id = _api_seed_remote_task(client, auth_headers, name="sec-ct-read")
    resp = client.get(f"/api/v1/tasks/{task_id}", headers=other_tenant_headers)
    assert resp.status_code == 404, resp.text
    assert _shell(resp)["code"] == "NOT_FOUND"


def test_permissionless_cannot_enumerate_tasks(
    client: Any, auth_headers: dict[str, str], permissionless_headers: dict[str, str]
) -> None:
    """无足迹用户带 ``project_id`` 列举 → 403（**不**枚举、**不**静默返回空）。"""
    _api_seed_remote_task(client, auth_headers, name="sec-enum")
    resp = client.get(
        "/api/v1/tasks", headers=permissionless_headers, params={"project_id": "p-any"}
    )
    assert resp.status_code == 403, resp.text
    assert _shell(resp)["code"] == "PERMISSION_DENIED"


@pytest.mark.parametrize("suffix", ["apply", "push"])
def test_permissionless_mutation_is_403(
    client: Any,
    auth_headers: dict[str, str],
    permissionless_headers: dict[str, str],
    suffix: str,
) -> None:
    """无 capability 的**变更**（Apply / Push）→ 403（变更操作不静默、不降级为 404）。"""
    task_id = _api_seed_remote_task(client, auth_headers, name=f"sec-cap-{suffix}")
    resp = client.post(f"/api/v1/tasks/{task_id}/{suffix}", headers=permissionless_headers, json={})
    assert resp.status_code == 403, resp.text
    assert _shell(resp)["code"] == "PERMISSION_DENIED"


def test_permissionless_read_is_404_not_403(
    client: Any, auth_headers: dict[str, str], permissionless_headers: dict[str, str]
) -> None:
    """无足迹用户**单资源读取** Diff → **404**（统一隔离 I-1：不泄漏存在性，非 403）。"""
    task_id = _api_seed_remote_task(client, auth_headers, name="sec-cap-diff")
    resp = client.get(f"/api/v1/tasks/{task_id}/diff", headers=permissionless_headers)
    assert resp.status_code == 404, resp.text
    assert _shell(resp)["code"] == "NOT_FOUND"


def test_cross_tenant_apply_push_is_404(
    client: Any, auth_headers: dict[str, str], other_tenant_headers: dict[str, str]
) -> None:
    """跨租户 Apply / Push → 404（统一隔离，**不**触碰工作区）。"""
    task_id = _api_seed_remote_task(client, auth_headers, name="sec-ct-mut")
    for suffix in ("apply", "push"):
        resp = client.post(
            f"/api/v1/tasks/{task_id}/{suffix}", headers=other_tenant_headers, json={}
        )
        assert resp.status_code == 404, f"{suffix}: {resp.text}"
        assert _shell(resp)["code"] == "NOT_FOUND"


# ===========================================================================
# 2. 路径逃逸（#36）
# ===========================================================================


@pytest.mark.parametrize("forged", ["C:/host/escape", "/etc/passwd", "wr_../../escape", "plain"])
def test_forged_checkout_ref_is_validation_error(tmp_path: Any, forged: str) -> None:
    """伪造 / 穿越 ``checkout_ref`` → ``VALIDATION_ERROR``（**不**把宿主路径当目录）。"""
    storage = ProjectStorage(tmp_path / "wsroot")
    with pytest.raises(DomainError) as excinfo:
        storage.resolve_checkout_ref(forged)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_path_for_checkout_ref_is_contained_within_root(tmp_path: Any) -> None:
    """合法 ``checkout_ref`` 还原的 Attempt 目录**恒在** ``wsroot`` 之内。

    （canonical containment 规范化包含校验）。
    """
    root = tmp_path / "wsroot"
    storage = ProjectStorage(root)
    ref = storage.checkout_ref("exec-1", 1)
    resolved = storage.resolve_checkout_ref(ref).resolve()
    assert str(resolved).startswith(str(root.resolve()))
    # 不透明：不含宿主分隔符 / 伪前缀逃逸痕迹。
    assert "/" not in ref and ".." not in ref


def test_service_rejects_forged_host_path_in_attempt(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """Attempt 记录内被塞入**宿主路径**冒充 ``checkout_ref`` → Apply ``VALIDATION_ERROR``。"""
    service, sandbox, _audit = _build(session_factory, tmp_path)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(
        session_factory, task_id=task_id, storage=service.storage, checkout_ref="C:/host/escape"
    )  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.apply(principal, task_id)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR
    assert sandbox.subs() == []  # 未触碰 Git


def test_managed_paths_rejects_unsafe_segment(tmp_path: Any) -> None:
    """``ManagedWorkspacePaths`` 拒绝绝对路径 / ``..`` / 分隔符片段（纵深防御）。"""
    paths = ManagedWorkspacePaths(tmp_path / "root")
    with pytest.raises(DomainError) as excinfo:
        paths.attempt_dir("../escape", 1)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


# ===========================================================================
# 3. Secret 泄漏（#38）
# ===========================================================================


def test_push_credential_only_in_push_env_not_response_or_audit(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """写凭证**仅**注入 Push 命令 env；**不**出现在响应 / 审计 / 非 Push 命令。"""
    secret = "s3cr3t-token-do-not-leak"
    credential = GitWriteCredential(username="x-access-token", token=secret)
    service, sandbox, audit = _build(session_factory, tmp_path, credential=credential)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    result = service.push(principal, task_id)

    assert result.pushed is True
    assert secret not in repr(result)
    assert all(secret not in str(rec) for rec in audit.records)
    # 凭证只在 push 命令的 env；其余子命令不带。
    assert sandbox.push_env() and sandbox.push_env()[0].get("ASTRA_GIT_PASSWORD") == secret
    for sub, _args, env, _cwd in sandbox.calls:
        if sub != "push":
            assert "ASTRA_GIT_PASSWORD" not in env


def test_remote_task_view_exposes_no_host_path_or_token(
    client: Any, auth_headers: dict[str, str], session_factory: Any, tmp_path: Any
) -> None:
    """远程任务视图仅返回**必有**的不透明 ``checkout_ref``（无宿主路径 / 令牌样式串）。"""
    task_id = _api_seed_remote_task(client, auth_headers, name="sec-view")
    storage = ProjectStorage(tmp_path / "wsroot")
    opaque = storage.checkout_ref("exec-secview", 1)
    _seed_attempt(session_factory, task_id=task_id, storage=storage, checkout_ref=opaque)

    resp = client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    text = resp.text
    assert ":/" not in text  # 无 scheme:/（如 C:/、file:/）宿主路径
    assert "\\\\" not in text  # 无 JSON 转义双反斜杠（Windows 宿主路径）
    assert str(tmp_path) not in text  # 不含宿主配置根绝对路径
    # 去条件化强断言：视图**必**暴露不透明 ``checkout_ref``，且不含任何路径分隔符。
    data = _shell(resp)["data"]
    ref = data.get("checkout_ref")
    assert ref is not None, f"视图应暴露不透明 checkout_ref：{data}"
    assert ref == opaque
    assert "/" not in ref and "\\" not in ref  # 不透明引用不含路径分隔符


def test_remote_events_and_logs_have_no_plaintext_secret(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """事件 / 日志载荷不含常见凭证明文前缀（纵深：远程面**不**回显秘密）。"""
    task_id = _api_seed_remote_task(client, auth_headers, name="sec-evt")
    markers = ("ASTRA_GIT_PASSWORD", "Bearer ", "s3cr3t", "password=")
    for suffix in ("events", "logs", "attempts"):
        resp = client.get(f"/api/v1/tasks/{task_id}/{suffix}", headers=auth_headers)
        assert resp.status_code == 200, f"{suffix}: {resp.text}"
        assert not any(m in resp.text for m in markers), f"{suffix} 泄漏疑似秘密"


# ===========================================================================
# 4. Git 写权限（#37）
# ===========================================================================


def test_push_requires_independent_capability(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """仅授 ``git.apply``（无 ``git.push``）→ Push **独立**拒绝 403（不复用 Apply 授权）。"""
    service, sandbox, _audit = _build(
        session_factory, tmp_path, allowed={"git.apply"}, credential=GitWriteCredential(token="t")
    )
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.push(principal, task_id)
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert sandbox.subs() == []


def test_push_without_write_credential_is_422_and_no_push(
    session_factory: Any, tmp_path: Any, principal: Any
) -> None:
    """未配置写凭证 → 422 ``CONFIGURATION_ERROR``（且**不**触发 push）。"""
    service, sandbox, _audit = _build(session_factory, tmp_path, credential=None)
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.push(principal, task_id)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    assert sandbox.subs() == []


@pytest.mark.parametrize("target_ref", ["+main", ":main"])
def test_push_rejects_force_and_branch_delete(
    session_factory: Any, tmp_path: Any, principal: Any, target_ref: str
) -> None:
    """``+main``（强推）/ ``:main``（删远端分支）→ 403（且**不**触发 push）。"""
    service, sandbox, _audit = _build(
        session_factory, tmp_path, credential=GitWriteCredential(token="t")
    )
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.push(principal, task_id, target_ref=target_ref)
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert sandbox.subs() == []


def test_push_rejects_arbitrary_url(session_factory: Any, tmp_path: Any, principal: Any) -> None:
    """``remote='https://evil/x.git'`` → 403（任意 URL）。"""
    service, sandbox, _audit = _build(
        session_factory, tmp_path, credential=GitWriteCredential(token="t")
    )
    project = _seed_project(session_factory)
    task_id = _seed_task(session_factory, project_id=project.id)
    _seed_attempt(session_factory, task_id=task_id, storage=service.storage)  # type: ignore[arg-type]

    with pytest.raises(DomainError) as excinfo:
        service.push(principal, task_id, remote="https://evil/x.git")
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED
    assert sandbox.subs() == []


# ===========================================================================
# 5. 网络绕过（#42 / N10 · D19）
# ===========================================================================


def test_egress_default_deny_all() -> None:
    """默认（enabled + 空 allow）→ **拒绝**全部出网（应用层基线）。"""
    assert SecurityEgressPolicy().authorize("https://example.com/").allowed is False


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_egress_private_and_metadata_rejected(url: str) -> None:
    """私网 / 环回 / 云元数据 IP —— **即使**显式白名单也强制拒段。"""
    assert "169.254.169.254" in METADATA_IPS
    host = url.split("//", 1)[1].split("/", 1)[0].strip("[]")
    assert SecurityEgressPolicy(allow=[host]).authorize(url).allowed is False


def test_egress_dns_rebinding_rejected() -> None:
    """DNS rebinding（首解析公网 → 二次内网）→ 拒绝。"""
    state = {"n": 0}

    def resolver(host: str) -> list[str]:
        state["n"] += 1
        return ["93.184.216.34"] if state["n"] == 1 else ["127.0.0.1"]

    decision = SecurityEgressPolicy(allow=["example.com"]).authorize(
        "https://example.com/", resolver=resolver
    )
    assert decision.allowed is False


@pytest.mark.docker
def test_sandbox_network_isolation_requires_docker_profile() -> None:
    """**#42 / D19 挂账**：真实 ``network=none`` 沙箱出网阻断**仅在** Docker / Compose 档验证。

    本机无 Docker 运行时 → 缺运行时 ``skip``；``ASTRA_TEST_REQUIRE_DOCKER=1``（服务器/CI）时
    **必须**实跑（**不**豁免）。应用层白名单检查**不可替代**网络层隔离。
    """
    if os.environ.get("ASTRA_TEST_REQUIRE_DOCKER") == "1":
        pytest.fail("Docker 运行时下必须实跑网络隔离断言（T2-63 服务器验收）——请接真实 Docker 复验")
    pytest.skip("挂账待服务器：真实 Docker / Compose 网络隔离（#42 / D19）")
