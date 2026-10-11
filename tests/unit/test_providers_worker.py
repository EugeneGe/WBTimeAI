"""``Providers.worker_executor`` 装配单测（W1 / T2-02；设计 §2.9 / R-23；C-01 / D4）。

覆盖：local ⇒ ``InProcessBackgroundExecutor``；server（无 Redis）⇒ 占位回落
``UnsupportedBackgroundExecutor``（非静默）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from astra_config.providers import Providers, build_providers
from astra_config.settings import Settings


def _local_settings(tmp_path: Path) -> Settings:
    return Settings(
        mode="local",
        database_url=f"sqlite:///{(tmp_path / 'worker_assembly.db').as_posix()}",
        secret_key="unit-test-secret-key-0123456789abcdef",
        data_dir=str(tmp_path / "astra-data"),
    )


def test_providers_declares_worker_executor_slot() -> None:
    """``Providers`` 声明 ``worker_executor`` 槽位且默认可空。"""
    import dataclasses

    assert "worker_executor" in {f.name for f in dataclasses.fields(Providers)}
    probes = Providers(settings=_local_settings(Path(".")), database=None)
    assert probes.worker_executor is None


def test_local_worker_executor_is_inprocess(tmp_path: Path) -> None:
    """local 模式装配 ``InProcessBackgroundExecutor``。"""
    from astra_task import InProcessBackgroundExecutor

    providers = build_providers(_local_settings(tmp_path))
    try:
        assert isinstance(providers.worker_executor, InProcessBackgroundExecutor)
    finally:
        if providers.database is not None:
            providers.database.engine.dispose()


def test_server_worker_executor_falls_back_without_redis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """server 模式（无 Redis）⇒ 执行体占位回落（非静默）。"""
    import astra_config.providers as providers_module
    from astra_config.providers import DatabaseProvider
    from astra_task import UnsupportedBackgroundExecutor, UnsupportedTaskQueue

    monkeypatch.setattr(
        providers_module, "validate_mode_database_consistency", lambda settings: None
    )
    monkeypatch.setattr(
        providers_module,
        "_build_database",
        lambda settings: DatabaseProvider(engine=object(), session_factory=object()),
    )
    settings = Settings(
        mode="server",
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        secret_key="unit-test-secret-key-0123456789abcdef",
        data_dir=str(tmp_path / "astra-data"),
    )
    providers = build_providers(settings)
    assert isinstance(providers.worker_executor, UnsupportedBackgroundExecutor)
    assert isinstance(providers.task_queue, UnsupportedTaskQueue)
