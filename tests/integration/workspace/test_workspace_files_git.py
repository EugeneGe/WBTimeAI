"""Workspace Files / Environment / Git 用例集成测试（W7 / T2-38）。

覆盖（W7 开工前架构裁定 §2.2 / §10）：

- **Files**：经 ``Storage`` 抽象读写（``put`` / ``get`` / ``open`` / ``delete`` / ``list`` /
  ``exists`` / ``url``），对象键按工作区隔离；
- **Environment**：``env_vars`` **仅非敏感明文** + 敏感值**引用注入**；🔴 **敏感明文扫描**
  （落库的 ``env_vars`` **不含**明文密钥；解析仅内存）；
- **Git**：所有 git 命令**仅经 Sandbox**（``SandboxProvider.exec``）；静态断言 **不 import
  ``subprocess``**（禁 Host 直连）；
- **项目 / 克隆编排**：``ProjectService`` 同步（沙箱）/ 异步（派发器）两条路径。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from astra_core import DomainError, ErrorCode
from astra_database import session_scope
from astra_database.models.project import WorkspaceEnvironment as OrmWorkspaceEnvironment
from astra_domain import SandboxSession
from astra_sandbox import ExecResult
from astra_workspace import (
    EnvironmentService,
    FileService,
    GitService,
    ProjectService,
    build_workspace_services,
)

TENANT_A = "tenant-aaaa"

_PLAINTEXT_TOKEN = "ghp_supersecrettoken_1234567890"
_PLAINTEXT_PASSWORD = "hunter2-super-secret-pw"


# -- 测试替身（Protocol 结构化满足） -----------------------------------------


class _FakeSandbox:
    """记录调用的假 ``SandboxProvider``（断言 Git 经沙箱执行）。"""

    kind = "local_process"
    available = True

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, str] | None, str | None]] = []
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
        self.calls.append(
            (command if isinstance(command, str) else list(command), dict(env or {}), cwd)
        )
        return ExecResult(exit_code=0, stdout="ok")

    def put_file(
        self, session: SandboxSession, path: str, content: str
    ) -> None:  # pragma: no cover
        return None

    def get_file(self, session: SandboxSession, path: str) -> str:  # pragma: no cover
        return ""

    def destroy(self, session: SandboxSession) -> None:
        self.destroyed.append(session)


class _FakeCredentialResolver:
    """假凭证解密器（结构化满足 ``CredentialResolver``）。"""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def decrypt(self, credential_id: str) -> str:
        return self._mapping[credential_id]


class _FakeSecretProvider:
    """假机密读取器（结构化满足 ``SecretResolver``）。"""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._mapping.get(name, default)


# -- Files -------------------------------------------------------------------


@pytest.fixture()
def file_service(tmp_path: Path) -> FileService:
    from astra_storage import create_local_file_storage

    return FileService(create_local_file_storage(tmp_path / "storage"))


def test_files_roundtrip_via_storage(file_service: FileService) -> None:
    """经 ``Storage`` 的写 / 读 / 存在 / URL / 列表 / 删除往返。"""
    obj = file_service.put(
        workspace_id="ws-1", path="src/main.py", data=b"print('hi')", content_type="text/x-python"
    )
    assert obj.key == "workspaces/ws-1/src/main.py"
    assert file_service.exists(workspace_id="ws-1", path="src/main.py")
    assert file_service.get(workspace_id="ws-1", path="src/main.py") == b"print('hi')"
    assert file_service.url(workspace_id="ws-1", path="src/main.py").startswith("file://")
    with file_service.open(workspace_id="ws-1", path="src/main.py") as handle:
        assert handle.read() == b"print('hi')"

    listed = file_service.list(workspace_id="ws-1")
    assert [item.key for item in listed] == ["workspaces/ws-1/src/main.py"]

    file_service.delete(workspace_id="ws-1", path="src/main.py")
    assert not file_service.exists(workspace_id="ws-1", path="src/main.py")


def test_files_reject_path_escape(file_service: FileService) -> None:
    """路径越界（绝对 / ``..``）被拒。"""
    with pytest.raises(DomainError) as excinfo:
        file_service.put(workspace_id="ws-1", path="../escape.txt", data=b"x")
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR
    with pytest.raises(DomainError):
        FileService.build_key("ws-1", "/abs.txt")


# -- Environment -------------------------------------------------------------


def test_environment_non_sensitive_roundtrip(session_factory: object) -> None:
    """非敏感 ``env_vars`` 明文可落库并往返。"""
    service = EnvironmentService(session_factory)  # type: ignore[arg-type]
    env = service.create(
        tenant_id=TENANT_A,
        workspace_id="ws-1",
        name="dev",
        env_vars={"LOG_LEVEL": "debug", "WORKERS": 4},
        runtime={"python": "3.12"},
    )
    fetched = service.get(env.id, tenant_id=TENANT_A)
    assert fetched.env_vars == {"LOG_LEVEL": "debug", "WORKERS": 4}
    assert fetched.runtime == {"python": "3.12"}
    assert [e.name for e in service.list_for_workspace("ws-1", tenant_id=TENANT_A)] == ["dev"]


def test_environment_sensitive_plaintext_rejected(session_factory: object) -> None:
    """敏感键名给**明文** → 拒绝（强制引用）。"""
    service = EnvironmentService(session_factory)  # type: ignore[arg-type]
    with pytest.raises(DomainError) as excinfo:
        service.create(
            tenant_id=TENANT_A,
            workspace_id="ws-1",
            name="prod",
            env_vars={"GITHUB_TOKEN": _PLAINTEXT_TOKEN},
        )
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_environment_sensitive_reference_never_persists_plaintext(
    session_factory: object,
) -> None:
    """🔴 敏感值经**引用注入**：落库 ``env_vars`` **不含明文**；解析仅内存。"""
    resolver = _FakeCredentialResolver({"cred-1": _PLAINTEXT_TOKEN})
    secrets = _FakeSecretProvider({"DB_PASSWORD": _PLAINTEXT_PASSWORD})
    service = EnvironmentService(
        session_factory, credential_resolver=resolver, secret_provider=secrets  # type: ignore[arg-type]
    )
    env = service.create(
        tenant_id=TENANT_A,
        workspace_id="ws-1",
        name="prod",
        env_vars={
            "GITHUB_TOKEN": {"$ref": "credential:cred-1"},
            "DB_PASSWORD": {"$ref": "secret:DB_PASSWORD"},
            "LOG_LEVEL": "info",
        },
    )

    # 落库的 env_vars 仅含引用 + 非敏感明文，**无任何明文密钥**。
    with session_scope(session_factory) as session:  # type: ignore[arg-type]
        row = session.get(OrmWorkspaceEnvironment, env.id)
        assert row is not None
        raw = dict(row.env_vars or {})
    serialized = json.dumps(raw)
    assert _PLAINTEXT_TOKEN not in serialized, "明文 Token 泄漏到 env_vars！"
    assert _PLAINTEXT_PASSWORD not in serialized, "明文密码泄漏到 env_vars！"
    assert raw["GITHUB_TOKEN"] == {"$ref": "credential:cred-1"}
    assert raw["DB_PASSWORD"] == {"$ref": "secret:DB_PASSWORD"}
    assert raw["LOG_LEVEL"] == "info"

    # 解析（仅内存）返回真实明文。
    resolved = service.resolve_env(service.get(env.id, tenant_id=TENANT_A))
    assert resolved["GITHUB_TOKEN"] == _PLAINTEXT_TOKEN
    assert resolved["DB_PASSWORD"] == _PLAINTEXT_PASSWORD


def test_environment_missing_resolver_raises(session_factory: object) -> None:
    """未注入解析器时解析引用 → ``CONFIGURATION_ERROR``（不静默）。"""
    service = EnvironmentService(session_factory)  # type: ignore[arg-type]
    env = service.create(
        tenant_id=TENANT_A,
        workspace_id="ws-1",
        name="prod",
        env_vars={"GITHUB_TOKEN": {"$ref": "credential:cred-1"}},
    )
    with pytest.raises(DomainError) as excinfo:
        service.resolve_env(env)
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR


# -- Git（仅经 Sandbox） -----------------------------------------------------


def test_git_clone_runs_only_in_sandbox() -> None:
    """``GitService`` 所有命令**仅经 ``SandboxProvider.exec``**。"""
    sandbox = _FakeSandbox()
    git = GitService(sandbox)
    session = sandbox.create_session(workspace_id="ws-1")

    result = git.clone(session, "https://example.com/repo.git", "repo", base_ref="main")
    assert result.ok
    commands = [call[0] for call in sandbox.calls]
    assert ["git", "clone", "https://example.com/repo.git", "repo"] in commands
    assert ["git", "checkout", "main"] in commands
    # 所有命令均为 git 前缀且经沙箱（无 Host 直连）。
    assert all(cmd[0] == "git" for cmd in commands)


def test_git_module_does_not_use_subprocess() -> None:
    """🔴 静态断言：``git.py`` **不** import ``subprocess`` / ``os``（禁 Host 直连）。"""
    import ast

    source = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "workspace"
        / "src"
        / "astra_workspace"
        / "git.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"subprocess", "os", "shutil"}
    assert not (forbidden & imported), f"git.py 违规导入：{sorted(forbidden & imported)}"


# -- 项目 / 克隆编排 ---------------------------------------------------------


def test_project_service_crud_and_sync_clone(session_factory: object) -> None:
    """``ProjectService``：创建 / 读取 / 列表 + 同步克隆（经 Sandbox）。"""
    sandbox = _FakeSandbox()
    service = ProjectService(
        session_factory, GitService(sandbox), sandbox=sandbox  # type: ignore[arg-type]
    )
    project = service.create(
        tenant_id=TENANT_A,
        workspace_id="ws-1",
        name="demo",
        repo_url="https://example.com/repo.git",
        default_branch="main",
    )
    assert service.get(project.id, tenant_id=TENANT_A).name == "demo"
    assert [p.id for p in service.list_by_workspace("ws-1", tenant_id=TENANT_A)] == [project.id]

    outcome = service.clone(tenant_id=TENANT_A, project_id=project.id, base_ref="main")
    assert outcome.task_id is None
    assert outcome.result is not None and outcome.result.ok
    assert sandbox.created and sandbox.destroyed, "同步克隆须创建并在 finally 销毁沙箱会话"


def test_project_service_async_clone_dispatches_task(session_factory: object) -> None:
    """注入派发器时，``clone`` 走**异步**路径并返回 ``task_id``。"""

    class _Dispatcher:
        def __init__(self) -> None:
            self.seen: dict[str, Any] = {}

        def dispatch_clone(self, **kwargs: Any) -> str:
            self.seen = dict(kwargs)
            return "task-123"

    dispatcher = _Dispatcher()
    service = ProjectService(session_factory, task_dispatcher=dispatcher)  # type: ignore[arg-type]
    project = service.create(
        tenant_id=TENANT_A,
        workspace_id="ws-1",
        name="demo2",
        repo_url="https://example.com/repo.git",
    )
    outcome = service.clone(tenant_id=TENANT_A, project_id=project.id, base_ref="dev")
    assert outcome.task_id == "task-123"
    assert outcome.result is None
    assert dispatcher.seen["repo_url"] == "https://example.com/repo.git"
    assert dispatcher.seen["base_ref"] == "dev"


def test_project_service_requires_repo_url(session_factory: object) -> None:
    """无仓库地址 → 克隆报 ``VALIDATION_ERROR``。"""
    service = ProjectService(session_factory)  # type: ignore[arg-type]
    project = service.create(tenant_id=TENANT_A, workspace_id="ws-1", name="norepo")
    with pytest.raises(DomainError) as excinfo:
        service.clone(tenant_id=TENANT_A, project_id=project.id)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


# -- 工厂装配（向后兼容） ----------------------------------------------------


def test_factory_backward_compatible_and_injects(session_factory: object, tmp_path: Path) -> None:
    """``build_workspace_services`` 既兼容空调用，又能注入新装配位。"""
    legacy = build_workspace_services(session_factory)  # type: ignore[arg-type]
    assert legacy.workspaces is not None
    assert legacy.files is None and legacy.git is None  # 缺依赖 → None

    from astra_storage import create_local_file_storage

    sandbox = _FakeSandbox()
    full = build_workspace_services(
        session_factory,  # type: ignore[arg-type]
        storage=create_local_file_storage(tmp_path / "storage"),
        sandbox=sandbox,
        credential_resolver=_FakeCredentialResolver({"c": "v"}),
        secret_provider=_FakeSecretProvider({"S": "v"}),
    )
    assert full.files is not None
    assert full.git is not None
    assert full.projects is not None
    assert full.environment is not None
