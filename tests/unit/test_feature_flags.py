"""Feature Flag 纯逻辑单元测试（T0-21 / 决策 D7）。

覆盖验收口径：
① 默认全开；② DB 覆盖生效；③ 配置覆盖优先级最高；④ 未知 flag → ``True``；
⑤ store 抛错 → 回退为空覆盖、不阻断。
"""

from __future__ import annotations

from collections.abc import Mapping

from astra_config import FEATURE_FLAGS, FeatureFlagService


class _FakeStore:
    """内存覆盖存储（模拟数据库）。"""

    def __init__(self, overrides: Mapping[str, bool]) -> None:
        self._overrides = dict(overrides)

    def load_overrides(self) -> Mapping[str, bool]:
        return dict(self._overrides)


class _BoomStore:
    """读取即抛错的存储（模拟表缺失 / 连接失败）。"""

    def load_overrides(self) -> Mapping[str, bool]:
        raise RuntimeError("feature_flag 表缺失")


def test_default_all_enabled() -> None:
    """① 未配置任何覆盖时，``all()`` 全 ``True``。"""
    service = FeatureFlagService()
    result = service.all()
    assert set(result) == set(FEATURE_FLAGS)
    assert all(result.values()) is True


def test_registry_defaults_are_all_true() -> None:
    """注册表默认值全为 ``True``（默认全开）。"""
    assert all(definition.default is True for definition in FEATURE_FLAGS.values())


def test_database_override_takes_effect() -> None:
    """② DB 覆盖生效（``enabled=false`` → 读取为 ``False``）。"""
    service = FeatureFlagService(store=_FakeStore({"workspace": False}))
    assert service.is_enabled("workspace") is False
    assert service.is_enabled("registration") is True


def test_config_override_has_highest_priority() -> None:
    """③ 配置覆盖优先级最高（覆盖 DB 与默认）。"""
    # 配置覆盖把 DB 关闭的 flag 重新打开。
    service = FeatureFlagService(
        store=_FakeStore({"workspace": False}),
        overrides={"workspace": True},
    )
    assert service.is_enabled("workspace") is True

    # 配置覆盖可独立关闭默认开启的 flag。
    service2 = FeatureFlagService(overrides={"credentials": False})
    assert service2.is_enabled("credentials") is False
    assert service2.is_enabled("registration") is True


def test_unknown_flag_defaults_to_true() -> None:
    """④ 未知 flag → ``True``（不抛异常）。"""
    service = FeatureFlagService()
    assert service.is_enabled("does-not-exist") is True


def test_store_error_falls_back_to_empty() -> None:
    """⑤ store 抛错 → 回退为空覆盖（全默认开）、不阻断。"""
    service = FeatureFlagService(store=_BoomStore())
    result = service.all()
    assert set(result) == set(FEATURE_FLAGS)
    assert all(result.values()) is True


def test_config_overrides_for_custom_flag_surface_in_all() -> None:
    """自定义（未注册）flag 的覆盖也应出现在 ``all()`` 观测面。"""
    service = FeatureFlagService(overrides={"custom_flag": False})
    result = service.all()
    assert result["custom_flag"] is False
    assert set(FEATURE_FLAGS).issubset(set(result))


def test_store_override_for_unregistered_flag_is_ignored_when_config_absent() -> None:
    """DB 中出现未注册 flag 时，读该名返回 DB 值（不抛）。"""
    service = FeatureFlagService(store=_FakeStore({"experimental": False}))
    assert service.is_enabled("experimental") is False
