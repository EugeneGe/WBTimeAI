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
