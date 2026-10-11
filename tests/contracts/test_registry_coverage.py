"""注册表扫描断言（T1-14 / 总纲 §13.2）。

- 已注册 Provider 集合必须与契约套件覆盖清单**双向一致**（新增 Provider 未纳入即失败）；
- 每个已注册 Provider 必须有录制回放 cassette；
- **SDK/HTTP 导入只在 ``astra_model.providers``**（Runtime 永不直接依赖模型 SDK）。
"""

from __future__ import annotations

import re
from pathlib import Path

import astra_model
from astra_model import ModelRegistry
from astra_model.providers import BUILTIN_PROVIDER_NAMES, register_builtin_providers

from .support import CASSETTES_DIR, CONTRACTED_PROVIDERS

_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", re.MULTILINE)

#: 仅允许出现在 ``providers/`` 内的模型 SDK / HTTP 客户端顶层导入。
_SDK_MODULES = {"httpx", "openai", "anthropic", "google", "aiohttp", "requests"}


def test_builtin_registration_matches_contract_coverage() -> None:
    registry = register_builtin_providers(ModelRegistry())
    assert set(registry.names()) == set(CONTRACTED_PROVIDERS)
    assert set(BUILTIN_PROVIDER_NAMES) == set(CONTRACTED_PROVIDERS)


def test_every_registered_provider_has_cassette() -> None:
    registry = register_builtin_providers(ModelRegistry())
    for name in registry.names():
        assert (CASSETTES_DIR / name / "chat.json").is_file(), f"{name} 缺少录制回放 cassette"


def test_sdk_imports_confined_to_providers_package() -> None:
    package_root = Path(astra_model.__file__).resolve().parent
    offenders: list[str] = []
    for path in package_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if path.relative_to(package_root).parts[0] == "providers":
            continue
        text = path.read_text(encoding="utf-8")
        modules = {
            (match.group(1) or match.group(2) or "").split(".")[0]
            for match in _IMPORT_RE.finditer(text)
        }
        bad = _SDK_MODULES & modules
        if bad:
            offenders.append(f"{path.name}: {sorted(bad)}")
    assert not offenders, f"SDK/HTTP 导入越界（应仅在 providers/）：{offenders}"
