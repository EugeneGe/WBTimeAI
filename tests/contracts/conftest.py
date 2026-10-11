"""契约套件 fixture：从注册清单枚举已注册 Provider（录制回放，离线）。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from .support import CONTRACTED_PROVIDERS, build_provider


@pytest.fixture(params=CONTRACTED_PROVIDERS)
def provider_name(request: pytest.FixtureRequest) -> str:
    """参数化：每个已覆盖 Provider 名。"""
    return str(request.param)


@pytest.fixture()
def provider(provider_name: str) -> Iterator[Any]:
    """构造带录制回放客户端的 Provider 实例。"""
    instance = build_provider(provider_name)
    yield instance
    instance.close()
