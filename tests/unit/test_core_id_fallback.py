"""UUIDv7 回退路径单测（uuid-utils 缺失时的纯 Python 实现）。"""

from __future__ import annotations

from uuid import RFC_4122, UUID

import astra_core.id as id_module


def test_pure_python_uuid7_version_and_variant() -> None:
    value = id_module._pure_python_uuid7()
    assert value.version == 7
    assert value.variant == RFC_4122


def test_generate_id_falls_back_when_uuid_utils_unavailable(
    monkeypatch,
) -> None:
    # 模拟 uuid-utils 缺失（不真正卸载全局模块，避免影响其它测试）。
    monkeypatch.setattr(id_module, "_HAS_UUID_UTILS", False)
    monkeypatch.setattr(id_module, "_uuid7_impl", None)

    generated = [id_module.generate_id() for _ in range(200)]

    assert all(len(identifier) == 36 for identifier in generated)
    assert all(UUID(identifier).version == 7 for identifier in generated)
    assert len(set(generated)) == 200
