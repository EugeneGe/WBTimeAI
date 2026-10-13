"""``astra doctor`` 注册表接线自检集成用例（V0.4.1 · J-1）。

覆盖：

1. **正常 PASS（local 社区模式）**：``check_registry_wiring`` 返回 ``ok``
   （🔴 无 Docker / dist 的降级为**正常态**，不得判 ``fail``）；
2. **挂载**：``_collect_checks()`` 含 ``registry_wiring`` 项且为 ``ok``；
3. **负向**：空注册表 / 占位实现 → ``fail``（防 R5A-01 · R5A-02 复发）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from astra_cli import doctor_checks


def _local_settings() -> object:
    """取隔离环境下的生效配置。"""
    from astra_config import get_settings

    return get_settings()


# -- 1. 正常 PASS ------------------------------------------------------------


def test_registry_wiring_passes_in_local_mode(isolated_settings_env: Path) -> None:
    """local 社区模式（无 Docker / dist）→ ``registry_wiring`` 为 ``ok``。"""
    settings = _local_settings()
    name, status, detail = doctor_checks.check_registry_wiring(settings)
    assert name == "registry_wiring"
    assert status == "ok", f"local 模式应 PASS（降级为正常态），实得：{status} / {detail}"
    # 结构描述应含 model / tool 注册表条目数（非空断言的可读证据）。
    assert "model_registry=" in detail and "tool_registry=" in detail


def test_collect_checks_mounts_registry_wiring(isolated_settings_env: Path) -> None:
    """``doctor`` 自检挂载了 ``registry_wiring`` 项，且 local 模式为 ``ok``。"""
    from astra_cli.commands.doctor import _collect_checks

    results = {check.name: check for check in _collect_checks()}
    assert "registry_wiring" in results, "doctor 未挂载 registry_wiring 自检项"
    assert results["registry_wiring"].status == "ok"


# -- 2. 负向：空注册表 / 占位实现 → FAIL ------------------------------------


def test_registry_wiring_fails_on_empty_registry(
    isolated_settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """装配出**空注册表** → ``check_registry_wiring`` 返回 ``fail``。"""
    import astra_config.providers as providers_mod
    from astra_model import ModelRegistry

    settings = _local_settings()

    def fake_build_providers(_settings: object) -> object:
        # 空 model / tool 注册表（装配期应为非空）。
        return providers_mod.Providers(
            settings=settings,  # type: ignore[arg-type]
            model_registry=ModelRegistry(),
            tool_registry=ModelRegistry(),
        )

    monkeypatch.setattr(providers_mod, "build_providers", fake_build_providers)

    name, status, detail = doctor_checks.check_registry_wiring(settings)
    assert name == "registry_wiring"
    assert status == "fail", f"空注册表应判 fail，实得：{status} / {detail}"
    assert "model_registry" in detail or "tool_registry" in detail


def test_registry_wiring_fails_on_placeholder(
    isolated_settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注册表槽位为 ``UnsupportedXxx`` 占位 → ``check_registry_wiring`` 返回 ``fail``。"""
    import astra_config.providers as providers_mod
    from astra_model import ModelRegistry
    from astra_storage import UnsupportedStorage

    settings = _local_settings()

    def fake_build_providers(_settings: object) -> object:
        return providers_mod.Providers(
            settings=settings,  # type: ignore[arg-type]
            model_registry=ModelRegistry(),
            tool_registry=UnsupportedStorage(feature="S3", available_in="Team"),
        )

    monkeypatch.setattr(providers_mod, "build_providers", fake_build_providers)

    name, status, detail = doctor_checks.check_registry_wiring(settings)
    assert name == "registry_wiring"
    assert status == "fail", f"占位实现应判 fail，实得：{status} / {detail}"
    assert "占位" in detail


# -- 3. 结构评估纯函数（可独立构造） ----------------------------------------


def test_evaluate_registry_wiring_flags_available_but_empty() -> None:
    """「恒空却自称 available」→ 计入问题（出口非占位维度）。"""
    from types import SimpleNamespace

    from astra_model import ModelRegistry

    class _FakeEmptyRegistry(ModelRegistry):
        """空注册表桩：自称 ``available`` 却无条目。"""

        available = True

    class _NonEmptyRegistry:
        """非空注册表桩（供结构评估用）。"""

        def names(self) -> list[str]:
            """返回一条条目。"""
            return ["stub"]

    providers = SimpleNamespace(
        model_registry=_FakeEmptyRegistry(),
        tool_registry=_NonEmptyRegistry(),
        skill_registry=None,
        mcp_registry=None,
    )

    problems, _detail = doctor_checks.evaluate_registry_wiring(providers)
    assert any("available" in problem for problem in problems), problems
