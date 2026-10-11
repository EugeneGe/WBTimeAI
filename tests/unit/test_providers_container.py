"""``Providers`` 容器扩展单测（T1-03 / 设计 §2.16 / D4；W6 裁定 Q10/A34）。

断言：
- ``Providers`` 声明全部 Phase 1 装配位（``model_providers`` / ``model_router`` /
  ``tool_registry`` / ``sandbox`` / ``runtime``），**默认**可空；
- ``build_providers`` 两模式均可构建；
- **W6 / A34**：``model_providers`` / ``model_router`` 工厂已落地（``build_model_providers`` /
  ``build_model_router``）→ **断言非空**；``runtime`` 装配位**仍** ``None``
  （``AgentRuntime`` 由组合根 ``AgentRuntime.build`` 装配，**不经** ``build_runtime``）。
- 装配仍**仅**在 ``build_providers`` 内进行（C-01）。
"""

from __future__ import annotations

from pathlib import Path

from astra_config.providers import Providers, build_providers
from astra_config.settings import Settings

#: Providers 新增装配位字段名（T1-03）。
_PHASE1_SLOTS = (
    "model_providers",
    "model_router",
    "tool_registry",
    "sandbox",
    "runtime",
)


def _local_settings(tmp_path: Path) -> Settings:
    return Settings(
        mode="local",
        database_url=f"sqlite:///{(tmp_path / 'providers_container.db').as_posix()}",
        secret_key="unit-test-secret-key-0123456789abcdef",
        data_dir=str(tmp_path / "astra-data"),
    )


def test_providers_container_declares_phase1_slots() -> None:
    """``Providers`` 数据类声明了全部 Phase 1 装配位，且默认可空。"""
    import dataclasses

    field_names = {field.name for field in dataclasses.fields(Providers)}
    for slot in _PHASE1_SLOTS:
        assert slot in field_names, f"Providers 缺少装配位：{slot}"

    probes = Providers(settings=_local_settings(Path(".")), database=None)
    for slot in _PHASE1_SLOTS:
        assert getattr(probes, slot) is None, f"{slot} 默认应为 None（占位可空）"


def test_local_build_exposes_slots_without_capability_packages(tmp_path: Path) -> None:
    """local 模式装配：核心 + Tool/Sandbox + **Model 工厂**均就位；``runtime`` 装配位仍 ``None``。

    W4 已落地 ``tool_registry`` / ``sandbox``；W6 / A34 落地 ``model_providers`` /
    ``model_router``（**断言非空**）；``runtime`` 装配位维持 ``None``（Runtime 由组合根
    ``AgentRuntime.build`` DI 装配，C-01 / A30）。
    """
    settings = _local_settings(tmp_path)
    providers = build_providers(settings)
    try:
        # 核心能力（Phase 0）就位。
        assert providers.database is not None
        assert providers.storage is not None
        assert providers.event_bus is not None
        assert providers.task_queue is not None
        assert providers.model_registry is not None
        assert providers.secrets is not None
        # W4：Tool 系统 + Sandbox 能力包已落地（C-01 装配点填充）。
        assert providers.tool_registry is not None
        assert providers.sandbox is not None
        # W6 / A34：Model 工厂已落地 → 断言非空。
        assert providers.model_providers is not None
        assert providers.model_router is not None
        # W6 / A30：runtime 装配位**仍** None（Runtime 由组合根按 DI 装配）。
        assert providers.runtime is None
    finally:
        if providers.database is not None:
            providers.database.engine.dispose()


def test_phase1_slots_are_none_for_server_placeholder_assembly(monkeypatch, tmp_path: Path) -> None:
    """server 占位装配（免 psycopg）：Model 工厂非空；``runtime`` 装配位仍 ``None`` 且不崩。"""
    import astra_config.providers as providers_module
    from astra_config.providers import DatabaseProvider

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
    # W4 已落地能力包装配非空；W6 / A34 Model 工厂非空；runtime 装配位仍可空。
    assert providers.tool_registry is not None
    assert providers.sandbox is not None
    assert providers.model_providers is not None
    assert providers.model_router is not None
    assert providers.runtime is None


def test_build_optional_returns_none_for_missing_package() -> None:
    """``_build_optional`` 对缺失的能力包返回 ``None``（延迟导入 + 可空）。"""
    from astra_config.providers import _build_optional

    result = _build_optional(
        _local_settings(Path(".")),
        module="astra_does_not_exist_capability",
        factory="build_anything",
    )
    assert result is None


def test_build_optional_returns_none_when_factory_absent() -> None:
    """模块存在但工厂函数缺失时返回 ``None``。"""
    from astra_config.providers import _build_optional

    result = _build_optional(
        _local_settings(Path(".")),
        module="astra_config.settings",
        factory="not_a_real_factory",
    )
    assert result is None
