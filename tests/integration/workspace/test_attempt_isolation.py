"""Attempt 独立副本 / 隔离 / 环境快照集成测试（R2 / T2-58；``I-P2-36`` / ``I-P2-38``）。

覆盖：

- **并发 Attempt 独立**：两个 Attempt 使用**不同** ``checkout_ref`` / 不同目录；写**同名文件**
  互不覆盖；
- **独立 clone（非共享 refs / index）**：每次 Attempt 经**独立** ``git clone``（各自 ``.git`` /
  refs / index；**非** ``git worktree``），每 Attempt 一个**独立** Git Provision Sandbox 会话；
- **凭证 / 宿主路径隔离**：Git Provision 命令 / 环境**不含**宿主绝对路径、**不含**凭证 env；
- **复用拒绝**：同 ``(execution_id, attempt)`` 二次供给 → ``CONFLICT``；
- **依赖缺失**：未注入 ``ProjectStorage`` / ``GitService`` / ``SandboxProvider`` →
  ``CONFIGURATION_ERROR``；
- **环境快照**：``compute_environment_digest`` **确定性**（键序无关）+ **剔除 Secret**；
  ``environment_digest_for`` 由 ``WorkspaceEnvironment`` 计算；
- **Worker 处理器**：``HANDLERS`` **4→6**（``project.clone`` / ``remote.agent_run``）；未注入
  执行体 → ``NotImplementedYetError``（非静默）；注入后可调用；
- **工厂装配**：``build_workspace_services(project_storage=...)`` 注入；缺省向后兼容（``None``）。

🔴 **Git 仅经 Sandbox**：所有 git 命令经假 ``SandboxProvider.exec``；**不**启动宿主 Git Shell。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode, NotImplementedYetError
from astra_domain import SandboxSession
from astra_sandbox import ExecResult
from astra_workspace import (
    GitService,
    ProjectService,
    ProjectStorage,
    WorkspaceEnvironment,
    build_workspace_services,
    compute_environment_digest,
    environment_digest_for,
)

TENANT_A = "tenant-aaaa"

#: 假 ``git rev-parse`` 输出（40 位十六进制 OID）。
_FAKE_SHA = "a" * 40


# -- 测试替身 ----------------------------------------------------------------


class _FakeSandbox:
    """记录调用的假 ``SandboxProvider``（断言 Git 仅经沙箱 + 每 Attempt 独立会话）。"""

    kind = "local_process"
    available = True

    def __init__(self) -> None:
        self.calls: list[tuple[int, list[str], dict[str, str], str | None]] = []
        self.created: list[SandboxSession] = []
        self.destroyed: list[SandboxSession] = []

    def create_session(self, **kwargs: Any) -> SandboxSession:
        session = SandboxSession(workspace_id=kwargs.get("workspace_id"))
        self.created.append(session)
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
        self.calls.append((id(session), args, dict(env or {}), cwd))
        stdout = _FAKE_SHA if "rev-parse" in args else "ok"
        return ExecResult(exit_code=0, stdout=stdout)

    def put_file(
        self, session: SandboxSession, path: str, content: str
    ) -> None:  # pragma: no cover
        return None

    def get_file(self, session: SandboxSession, path: str) -> str:  # pragma: no cover
        return ""

    def destroy(self, session: SandboxSession) -> None:
        self.destroyed.append(session)


def _build(
    session_factory: object, tmp_path: Path
) -> tuple[_FakeSandbox, ProjectStorage, ProjectService]:
    """构造 [假沙箱 + 受管目录 + ProjectService] 三元组。"""
    sandbox = _FakeSandbox()
    storage = ProjectStorage(tmp_path / "wsroot")
    service = ProjectService(
        session_factory,  # type: ignore[arg-type]
        GitService(sandbox),
        storage=storage,
        sandbox=sandbox,
    )
    return sandbox, storage, service


def _make_project(service: ProjectService) -> Any:
    return service.create(
        tenant_id=TENANT_A,
        workspace_id="ws-1",
        name="demo",
        repo_url="https://example.com/repo.git",
        default_branch="main",
    )


# -- 并发 Attempt 独立 -------------------------------------------------------


def test_two_attempts_get_distinct_checkout_ref_and_dirs(
    session_factory: object, tmp_path: Path
) -> None:
    """两个 Attempt：不同 ``checkout_ref`` / 不同目录；同名文件互不覆盖。"""
    sandbox, storage, service = _build(session_factory, tmp_path)
    project = _make_project(service)

    a = service.prepare_attempt(
        tenant_id=TENANT_A, project_id=project.id, execution_id="exec-1", attempt=1, base_ref="main"
    )
    b = service.prepare_attempt(
        tenant_id=TENANT_A, project_id=project.id, execution_id="exec-2", attempt=1, base_ref="main"
    )

    assert a.checkout_ref != b.checkout_ref
    assert a.base_commit == _FAKE_SHA and b.base_commit == _FAKE_SHA
    # 返回值**不含**宿主绝对路径。
    assert str(tmp_path) not in a.checkout_ref and str(tmp_path) not in b.checkout_ref

    dir_a = storage.attempt_dir("exec-1", 1)
    dir_b = storage.attempt_dir("exec-2", 1)
    assert dir_a != dir_b and dir_a.is_dir() and dir_b.is_dir()

    # 写同名文件 → 互不覆盖（独立工作副本）。
    (dir_a / "same.txt").write_text("A", encoding="utf-8")
    (dir_b / "same.txt").write_text("B", encoding="utf-8")
    assert (dir_a / "same.txt").read_text(encoding="utf-8") == "A"
    assert (dir_b / "same.txt").read_text(encoding="utf-8") == "B"

    # 每 Attempt 一个独立 Git Provision Sandbox 会话（各自独立 .git / refs / index）。
    assert len(sandbox.created) == 2
    assert len(sandbox.destroyed) == 2
    session_ids = {call[0] for call in sandbox.calls}
    assert len(session_ids) == 2, "两次供给应在**不同**沙箱会话内执行"


def test_attempt_uses_fresh_clone_not_shared_worktree(
    session_factory: object, tmp_path: Path
) -> None:
    """供给用 ``git clone``（独立 ``.git``）而非 ``git worktree``（共享 refs / index）。"""
    sandbox, _storage, service = _build(session_factory, tmp_path)
    project = _make_project(service)
    service.prepare_attempt(
        tenant_id=TENANT_A, project_id=project.id, execution_id="exec-1", attempt=1, base_ref="main"
    )
    commands = [call[1] for call in sandbox.calls]
    assert commands[0] == ["git", "clone", "https://example.com/repo.git"]
    assert ["git", "checkout", "main"] in commands
    assert ["git", "rev-parse", "main"] in commands
    # 全部 git 前缀 + **无** worktree（不共享 .git / refs / index）。
    assert all(cmd[0] == "git" for cmd in commands)
    assert not any("worktree" in cmd for cmd in commands)


def test_attempt_provisioning_no_host_path_no_credentials(
    session_factory: object, tmp_path: Path
) -> None:
    """Git Provision 命令 / env **不含**宿主绝对路径，也**不含**凭证材料。"""
    sandbox, _storage, service = _build(session_factory, tmp_path)
    project = _make_project(service)
    service.prepare_attempt(
        tenant_id=TENANT_A, project_id=project.id, execution_id="exec-1", attempt=1, base_ref="main"
    )
    host_root = str(tmp_path)
    for _sid, cmd, env, cwd in sandbox.calls:
        assert all(host_root not in str(part) for part in cmd), cmd
        assert cwd is None or host_root not in str(cwd), cwd
        upper = {str(k).upper() for k in env}
        assert not any("TOKEN" in key or "SECRET" in key or "PASSWORD" in key for key in upper), env


def test_prepare_attempt_rejects_reuse(session_factory: object, tmp_path: Path) -> None:
    """同 ``(execution_id, attempt)`` 二次供给 → ``CONFLICT``（不得复用工作副本）。"""
    _sandbox, _storage, service = _build(session_factory, tmp_path)
    project = _make_project(service)
    service.prepare_attempt(
        tenant_id=TENANT_A, project_id=project.id, execution_id="exec-1", attempt=1
    )
    with pytest.raises(DomainError) as excinfo:
        service.prepare_attempt(
            tenant_id=TENANT_A, project_id=project.id, execution_id="exec-1", attempt=1
        )
    assert excinfo.value.code is ErrorCode.CONFLICT


def test_prepare_attempt_requires_dependencies(session_factory: object) -> None:
    """未注入 ``ProjectStorage`` / ``GitService`` / ``SandboxProvider`` 时失败。

    预期 → ``CONFIGURATION_ERROR``。
    """
    service = ProjectService(session_factory)  # type: ignore[arg-type]
    project = _make_project(service)
    with pytest.raises(DomainError) as excinfo:
        service.prepare_attempt(
            tenant_id=TENANT_A, project_id=project.id, execution_id="exec-1", attempt=1
        )
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


# -- 环境快照 ----------------------------------------------------------------


def test_environment_digest_deterministic_and_key_order_independent() -> None:
    """同输入 → 同摘要；键序无关；不同非敏感输入 → 不同摘要。"""
    d1 = compute_environment_digest(runtime={"python": "3.12", "node": "20"})
    d2 = compute_environment_digest(runtime={"node": "20", "python": "3.12"})
    assert d1 == d2
    assert len(d1) == 64
    assert compute_environment_digest(image_digest="sha256:abc") != compute_environment_digest(
        image_digest="sha256:def"
    )


def test_environment_digest_excludes_secrets() -> None:
    """🔴 Secret 键（TOKEN / API_KEY / PASSWORD…）**不参与**摘要。"""
    with_secret = compute_environment_digest(
        runtime={"python": "3.12", "LOG_LEVEL": "info"},
        config={"GITHUB_TOKEN": "leak", "DB_PASSWORD": "pw", "DEPLOY_API_KEY": "k"},
    )
    without_secret = compute_environment_digest(
        runtime={"python": "3.12", "LOG_LEVEL": "info"}, config={}
    )
    assert with_secret == without_secret
    # 可追溯：同输入 → 同摘要。
    assert with_secret == compute_environment_digest(
        runtime={"LOG_LEVEL": "info", "python": "3.12"}, config={}
    )


def test_environment_digest_excludes_authorization_and_bearer() -> None:
    """R5A-06：``AUTHORIZATION`` / ``BEARER`` 键名**同源敏感**（不进摘要，不回归 token/secret）。"""
    from astra_workspace.environment_snapshot import is_sensitive_key

    for key in ("AUTHORIZATION", "Authorization", "HTTP_AUTHORIZATION", "BEARER", "BEARER_TOKEN"):
        assert is_sensitive_key(key) is True, key
    for key in ("python", "LOG_LEVEL", "network"):
        assert is_sensitive_key(key) is False, key

    with_creds = compute_environment_digest(
        runtime={"python": "3.12"},
        config={"AUTHORIZATION": "Bearer leak", "BEARER": "leak", "TOKEN": "leak", "SECRET": "leak"},
    )
    without_creds = compute_environment_digest(runtime={"python": "3.12"}, config={})
    assert with_creds == without_creds


def test_environment_digest_for_workspace_environment() -> None:
    """``environment_digest_for`` 由 ``WorkspaceEnvironment.runtime`` 计算（敏感剔除）。"""
    env = WorkspaceEnvironment(
        tenant_id=TENANT_A,
        workspace_id="ws-1",
        name="dev",
        runtime={
            "image_digest": "sha256:img",
            "python": "3.12",
            "dependency_locks": {"poetry.lock": "deadbeef"},
            "config": {"network": "offline"},
        },
    )
    expected = compute_environment_digest(
        image_digest="sha256:img",
        runtime={"python": "3.12"},
        dependency_locks={"poetry.lock": "deadbeef"},
        config={"network": "offline"},
    )
    assert environment_digest_for(env) == expected


# -- Worker 处理器 -----------------------------------------------------------


def test_worker_handlers_registered_six() -> None:
    """``HANDLERS`` 由 4 → **6**（``project.clone`` / ``remote.agent_run``，C-6）。"""
    from astra_worker.tasks import HANDLERS

    assert set(HANDLERS) == {
        "agent.run",
        "workflow.run",
        "knowledge.index",
        "maintenance.cleanup",
        "project.clone",
        "remote.agent_run",
    }
    assert len(HANDLERS) == 6


def test_worker_handlers_without_service_raise(session_factory: object, tmp_path: Path) -> None:
    """未注入执行体 → ``NotImplementedYetError``（**非静默**）；缺字段 → ``VALIDATION_ERROR``。"""
    from astra_worker import HandlerContext
    from astra_worker.tasks.project_clone import handle_project_clone
    from astra_worker.tasks.remote_agent_run import handle_remote_agent_run

    empty_ctx = HandlerContext(providers=object())

    with pytest.raises(NotImplementedYetError):
        handle_project_clone({"payload": {"project_id": "p", "tenant_id": "t"}}, empty_ctx)
    with pytest.raises(NotImplementedYetError):
        handle_remote_agent_run({"payload": {"execution_id": "e"}}, empty_ctx)

    with pytest.raises(DomainError) as excinfo:
        handle_project_clone({"payload": {}}, empty_ctx)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR
    with pytest.raises(DomainError) as excinfo2:
        handle_remote_agent_run({"payload": {}}, empty_ctx)
    assert excinfo2.value.code is ErrorCode.VALIDATION_ERROR


def test_worker_handlers_with_injected_services(session_factory: object, tmp_path: Path) -> None:
    """注入后：``project.clone`` 走同步沙箱克隆；``remote.agent_run`` 返回结果引用。"""
    from astra_worker import HandlerContext
    from astra_worker.tasks.project_clone import handle_project_clone
    from astra_worker.tasks.remote_agent_run import handle_remote_agent_run

    _sandbox, _storage, service = _build(session_factory, tmp_path)
    project = _make_project(service)

    class _Runner:
        def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
            assert payload["execution_id"] == "exec-1"
            return {
                "status": "SUCCEEDED",
                "result_commit": "b" * 40,
                "environment_digest": "c" * 64,
            }

    ctx = HandlerContext(
        providers=object(), services={"project_service": service, "remote_agent_run": _Runner()}
    )

    cloned = handle_project_clone(
        {"payload": {"project_id": project.id, "tenant_id": TENANT_A}}, ctx
    )
    assert cloned["project_id"] == project.id and cloned["cloned"] is True

    ran = handle_remote_agent_run({"payload": {"execution_id": "exec-1"}}, ctx)
    assert ran["status"] == "SUCCEEDED"
    assert ran["result_commit"] == "b" * 40
    assert ran["environment_digest"] == "c" * 64


# -- 工厂装配 ----------------------------------------------------------------


def test_factory_injects_project_storage(session_factory: object, tmp_path: Path) -> None:
    """``build_workspace_services(project_storage=...)`` 注入；缺省向后兼容（``None``）。"""
    storage = ProjectStorage(tmp_path / "root")
    full = build_workspace_services(session_factory, project_storage=storage)  # type: ignore[arg-type]
    assert full.projects.storage is storage

    legacy = build_workspace_services(session_factory)  # type: ignore[arg-type]
    assert legacy.projects.storage is None


# -- 静态：Git 仅经 Sandbox / 快照模块纯净 -----------------------------------


def test_service_modules_have_no_host_shell_or_runtime() -> None:
    """🔴 服务模块零 Host Shell / Runtime（纯净性守卫）。

    - 覆盖 ``git.py`` / ``project_service.py`` / ``environment_snapshot.py``；
    - 禁 ``subprocess`` / ``os``（**禁** Host 直连 git）；
    - ``environment_snapshot.py`` 禁 ``astra_runtime`` / ``fastapi``（L-1 / L-3）。
    """
    root = (
        Path(__file__).resolve().parents[3] / "packages" / "workspace" / "src" / "astra_workspace"
    )
    targets = {
        "git.py": {"subprocess", "os", "shutil"},
        "application/project_service.py": {"subprocess", "os"},
        "environment_snapshot.py": {"subprocess", "os", "astra_runtime", "fastapi", "starlette"},
    }
    for rel, forbidden in targets.items():
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not (forbidden & imported), f"{rel} 违规导入：{sorted(forbidden & imported)}"
