"""远程工作站**部署档装配**验证（R5 / T2-63；设计 §3 #34 / D15；A-12 / A-13）。

两档（设计 §2.8.1 / §2.9）——**本地面 vs 服务器面**切分（Manual 为执行方式、**非**豁免）：

- **Community 档（``ASTRA_MODE=local``）——本地面必绿**：装配 SQLite / LocalFileStorage /
  LocalEventBus / InProcess TaskQueue / Scheduler，且核心 Provider **不得**为 ``UnsupportedXxx``
  占位（#34「``ASTRA_MODE=server`` 不允许核心 Provider 留 ``UnsupportedXxx``」的本地对应）。
- **Compose 档（``ASTRA_MODE=server``；PG / Redis / Worker / Docker）——服务器面挂账**：
  server 一致性校验（**需 PostgreSQL 连接串**）本地可证（不静默误配）；真实 PG / Redis /
  Worker / Docker 沙箱端到端归 T2-63 服务器验收（``docker`` 门控；``REQUIRE_DOCKER=1`` 强制实跑）。

🔴 应用层白名单检查**不可替代**网络层隔离；Docker / Compose 网络隔离断言见
``tests/security/test_remote_workspace_boundaries.py``（#42 / D19）与本文件服务器面。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from astra_config import get_settings
from astra_config.providers import build_providers, validate_mode_database_consistency
from astra_core import DomainError, ErrorCode
from astra_event.placeholder import UnsupportedEventBus
from astra_storage.placeholder import UnsupportedStorage
from astra_task.placeholder import UnsupportedScheduler, UnsupportedTaskQueue

_UNSUPPORTED = (UnsupportedStorage, UnsupportedEventBus, UnsupportedTaskQueue, UnsupportedScheduler)

#: Community 档必须**真实装配**的核心 Provider 槽位（非 ``UnsupportedXxx``）。
_CORE_SLOTS = ("storage", "event_bus", "task_queue", "scheduler", "worker_executor")


# -- Community 档（本地面） ---------------------------------------------------


def test_community_profile_assembles_concrete_core_providers(isolated_settings_env: Any) -> None:
    """Community 档：核心 Provider 均为**具体**实现（非 ``UnsupportedXxx`` 占位）。"""
    providers = build_providers(get_settings())

    assert providers.settings.mode == "local"
    for slot in _CORE_SLOTS:
        provider = getattr(providers, slot)
        assert provider is not None, f"{slot} 未装配"
        assert not isinstance(provider, _UNSUPPORTED), (
            f"{slot} 落入 UnsupportedXxx 占位：{type(provider)!r}"
        )


def test_community_profile_uses_sqlite_database(isolated_settings_env: Any) -> None:
    """Community 档数据库为 SQLite（本地单机，无 PG 依赖）。"""
    providers = build_providers(get_settings())
    url = str(providers.settings.database_url)
    assert url.startswith("sqlite"), url


def test_create_app_assembles_remote_services(client: Any) -> None:
    """Community 档经 ``create_app`` 装配远程 Task / 变更审阅服务（#34/#37/#41 的本地接口在位）。"""
    services = client.app.state.services
    assert getattr(services, "remote_tasks", None) is not None
    assert getattr(services, "change_review", None) is not None
    # F2/F3（R5A-01）：远程读取侧适配器由**组合根真实装配**（非测试后门注入）。
    assert services.remote_tasks._artifact_reader is not None  # noqa: SLF001 - 装配断言
    assert services.remote_tasks._git_refs_provider is not None  # noqa: SLF001 - 装配断言


# -- F1（R5A-03）：Compose egress 网络名一致性（静态防回归） ------------------


def test_compose_egress_network_name_matches_worker_env() -> None:
    """🔴 Compose 的 ``sandbox-egress`` 网络**显式命名**，且与 worker 注入名 / 默认常量一致。

    R5A-03：compose 默认把网络命名为 ``<project>_sandbox-egress``（本例 ``astra-ai_sandbox-egress``），
    而 worker 经 ``ASTRA_SANDBOX_EGRESS_NETWORK`` 注入的是字面 ``astra-sandbox-egress`` ——
    二者不一致时干净 ``docker compose up`` 下 allowlisted 沙箱接入失败。本静态测试锁定：
    网络 ``name`` / worker env / ``astra_config.defaults`` 三者同值。
    """
    import yaml

    from astra_config.defaults import DEFAULT_SANDBOX_EGRESS_NETWORK

    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    network = compose["networks"]["sandbox-egress"]
    assert network.get("name") == DEFAULT_SANDBOX_EGRESS_NETWORK
    assert network.get("internal") is True

    worker_env = compose["services"]["worker"]["environment"]
    assert worker_env["ASTRA_SANDBOX_EGRESS_NETWORK"] == DEFAULT_SANDBOX_EGRESS_NETWORK
    # egress-proxy 双网卡含该命名网络（引用同一 key）。
    assert "sandbox-egress" in compose["services"]["egress-proxy"]["networks"]


# -- F3（R5A-01b）：GitRefsProvider 适配（fake sandbox；仅经 Sandbox） ---------


def test_parse_for_each_ref_maps_branches_and_tags() -> None:
    """``parse_for_each_ref``：``refs/heads`` → branch、``refs/tags`` → tag；其余跳过。"""
    from astra_workspace.git import parse_for_each_ref

    sha_a, sha_b, sha_c = "a" * 40, "b" * 40, "c" * 40
    output = (
        f"refs/heads/main|{sha_a}|commit\n"
        f"refs/tags/v1.0|{sha_b}|tag\n"
        f"refs/remotes/origin/main|{sha_c}|commit\n"
        "\n"
        "garbage-line\n"
    )
    assert parse_for_each_ref(output) == [
        ("main", sha_a, "branch"),
        ("v1.0", sha_b, "tag"),
    ]


def test_git_refs_provider_maps_and_destroys_session(tmp_path: Path) -> None:
    """``_SandboxGitRefsProvider``：仅经 Sandbox ``for-each-ref``；映射 + 会话 destroy + 跨租户空。"""
    from types import SimpleNamespace

    from astra_api.dependencies.services import _SandboxGitRefsProvider
    from astra_sandbox import ExecResult
    from astra_workspace import GitService, ProjectStorage

    sha_a, sha_b, sha_c = "a" * 40, "b" * 40, "c" * 40

    class _FakeSandbox:
        def __init__(self) -> None:
            self.created: list[object] = []
            self.destroyed: list[object] = []
            self.commands: list[list[str]] = []

        def create_session(self, **kwargs: Any) -> object:
            session = object()
            self.created.append(session)
            return session

        def exec(
            self,
            session: object,
            command: Any,
            *,
            timeout_ms: int | None = None,
            env: Any = None,
            cwd: str | None = None,
        ) -> ExecResult:
            self.commands.append(list(command))
            stdout = (
                f"refs/heads/main|{sha_a}|commit\n"
                f"refs/tags/v1.0|{sha_b}|tag\n"
                f"refs/remotes/origin/main|{sha_c}|commit\n"
            )
            return ExecResult(exit_code=0, stdout=stdout)

        def destroy(self, session: object) -> None:
            self.destroyed.append(session)

    class _FakeProjects:
        def __init__(self, project: Any) -> None:
            self._project = project

        def get(self, project_id: str) -> Any:
            return self._project

    tenant = "tenant-refs"
    sandbox = _FakeSandbox()
    provider = _SandboxGitRefsProvider(
        projects=_FakeProjects(SimpleNamespace(id="proj-1", tenant_id=tenant)),
        sandbox=sandbox,
        storage=ProjectStorage(tmp_path / "wsroot"),
        git_service=GitService(sandbox),
    )

    refs = provider.refs("proj-1", tenant_id=tenant)

    assert [(item.name, item.commit, item.kind) for item in refs] == [
        ("main", sha_a, "branch"),
        ("v1.0", sha_b, "tag"),
    ]
    assert sandbox.destroyed, "沙箱会话应被销毁（finally）"
    assert sandbox.commands and sandbox.commands[0][1] == "for-each-ref"

    # 跨租户 → 空元组（不泄漏存在性），且不新建会话。
    created_before = len(sandbox.created)
    assert provider.refs("proj-1", tenant_id="other-tenant") == ()
    assert len(sandbox.created) == created_before


# -- server 档一致性（本地可证：不静默误配） ---------------------------------


def test_server_mode_requires_postgres_url(
    isolated_settings_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ASTRA_MODE=server`` + SQLite 连接串 → ``CONFIGURATION_ERROR``（**不**静默误配 / 降级）。"""
    from astra_config.loader import reset_settings_cache

    monkeypatch.setenv("ASTRA_MODE", "server")
    # 保留 SQLite URL（isolated_settings_env 已设）→ 与 server 档不一致。
    reset_settings_cache()

    with pytest.raises(DomainError) as excinfo:
        validate_mode_database_consistency(get_settings())
    assert excinfo.value.code is ErrorCode.CONFIGURATION_ERROR
    reset_settings_cache()


# -- Compose 档（服务器面 · 挂账） -------------------------------------------


@pytest.mark.docker
def test_compose_profile_end_to_end_requires_server() -> None:
    """**#34 / D15 挂账**：Compose 档（PG / Redis / Worker / Docker）**仅在服务器**验证。

    本机无 PG / Redis / Docker 运行时 → 缺运行时 ``skip``；服务器 / CI
    （``ASTRA_TEST_REQUIRE_DOCKER=1``）**必须**实跑（**不**豁免），由指定环境责任人留证。
    """
    if os.environ.get("ASTRA_TEST_REQUIRE_DOCKER") == "1" or os.environ.get("ASTRA_TEST_PG_URL"):
        pytest.fail(
            "服务器 / Docker 环境下必须实跑 Compose 档装配与受限任务端到端（T2-63 服务器验收）"
        )
    pytest.skip(
        "挂账待服务器：Compose 档（PG / Redis / Worker / Docker Sandbox）端到端（#34 / D15）"
    )
