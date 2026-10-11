"""``build_providers`` 双模式装配单测（W2 收口）——设计 §3-#3/#4。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from astra_config.providers import build_providers
from astra_config.settings import Settings
from astra_core import NotImplementedYetError


@pytest.fixture()
def local_settings(tmp_path: Path) -> Settings:
    db_file = tmp_path / "providers_w2.db"
    return Settings(
        mode="local",
        database_url=f"sqlite:///{db_file.as_posix()}",
        secret_key="test-secret",
        data_dir=str(tmp_path / "astra-data"),
    )


def test_local_builds_all_providers(local_settings: Settings) -> None:
    providers = build_providers(local_settings)
    try:
        assert providers.database is not None
        assert providers.storage is not None
        assert providers.event_bus is not None
        assert providers.task_queue is not None
        assert providers.scheduler is not None
        assert providers.model_registry is not None
        assert providers.secrets is not None
    finally:
        providers.database.engine.dispose()


def test_local_storage_does_not_create_dir(local_settings: Settings) -> None:
    providers = build_providers(local_settings)
    try:
        assert not Path(local_settings.data_dir, "storage").exists()
    finally:
        providers.database.engine.dispose()


def test_server_placeholders_raise(local_settings: Settings) -> None:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        pytest.skip("psycopg 未安装，跳过 server 模式装配用例")

    from astra_event import UserRegistered

    server_settings = Settings(
        mode="server",
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        secret_key="test-secret",
        data_dir=str(local_settings.data_dir),
    )
    providers = build_providers(server_settings)
    with pytest.raises(NotImplementedYetError):
        providers.storage.put("k", b"v")
    with pytest.raises(NotImplementedYetError):
        providers.event_bus.publish(UserRegistered.create(user_id="u"))
    with pytest.raises(NotImplementedYetError):
        providers.task_queue.size()
    with pytest.raises(NotImplementedYetError):
        providers.scheduler.start()
    # model_registry / secrets 两模式一致（真实交付物）。
    assert providers.model_registry is not None
    assert providers.secrets is not None


def test_server_assembly_without_psycopg(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """免 psycopg 的 server 装配覆盖：桩掉驱动校验与数据库构建。"""
    import astra_config.providers as providers_module
    from astra_config.providers import DatabaseProvider
    from astra_event import UserRegistered

    # 最小侵入：绕过 psycopg 一致性校验 + 用轻量对象替代真实引擎。
    monkeypatch.setattr(
        providers_module, "validate_mode_database_consistency", lambda settings: None
    )
    monkeypatch.setattr(
        providers_module,
        "_build_database",
        lambda settings: DatabaseProvider(engine=object(), session_factory=object()),
    )

    server_settings = Settings(
        mode="server",
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        secret_key="test-secret",
        data_dir=str(tmp_path / "astra-data"),
    )

    # 其它用例（API lifespan）经 configure_logging 的 dictConfig 可能禁用既有 logger，
    # 此处显式恢复该 logger，确保占位 WARNING 可被 caplog 捕获（monkeypatch 自动还原）。
    provider_logger = logging.getLogger("astra_config.providers")
    monkeypatch.setattr(provider_logger, "disabled", False)
    monkeypatch.setattr(provider_logger, "propagate", True)

    with caplog.at_level(logging.WARNING, logger="astra_config.providers"):
        providers = build_providers(server_settings)

    # 占位对象：接口齐备、首次调用抛错（非静默降级）。
    with pytest.raises(NotImplementedYetError):
        providers.storage.put("k", b"v")
    with pytest.raises(NotImplementedYetError):
        providers.event_bus.publish(UserRegistered.create(user_id="u"))
    with pytest.raises(NotImplementedYetError):
        providers.task_queue.size()
    with pytest.raises(NotImplementedYetError):
        providers.scheduler.start()

    # model_registry / secrets 两模式一致（真实交付物）。
    assert providers.model_registry is not None
    assert providers.secrets is not None

    # 装配时输出 4 条结构化占位 WARNING。
    placeholder_warnings = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "provider.placeholder"
    ]
    assert len(placeholder_warnings) == 4


def test_placeholder_objects_raise_directly() -> None:
    """直接构造占位对象并断言抛错（不依赖 psycopg）。"""
    from astra_event import UnsupportedEventBus
    from astra_event.events import SystemStarted
    from astra_storage import UnsupportedStorage
    from astra_task import UnsupportedScheduler, UnsupportedTaskQueue

    with pytest.raises(NotImplementedYetError):
        UnsupportedStorage(feature="S3", available_in="Phase 1").exists("k")
    with pytest.raises(NotImplementedYetError):
        UnsupportedEventBus(feature="Redis", available_in="Team").publish(
            SystemStarted.create(mode="server")
        )
    with pytest.raises(NotImplementedYetError):
        UnsupportedTaskQueue(feature="Redis", available_in="Team").dequeue()
    with pytest.raises(NotImplementedYetError):
        UnsupportedScheduler(feature="分布式", available_in="Team").start()
