"""密钥泄漏扫描集成测试（W6；设计 §2U / 安全基线；C-07）。

对仓库源码做**保守**的静态扫描，确保：

- ``packages/`` / ``apps/`` 下**无**硬编码真实密钥（OpenAI / AWS / 私钥块等）；
- ``.env.example`` 仅含**占位**密钥（非真实凭据）；
- ``.env.example`` 声明 W6 新增配置项（``ASTRA_RUN_TIMEOUT_MS`` /
  ``ASTRA_SSE_HEARTBEAT_SECONDS``）。

扫描范围特指**源码目录**（不含测试夹具——测试中以 ``sk-live-...`` 等具辨识度的假密钥
验证「不泄漏」，属预期用法）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 真实密钥的保守特征（测试夹具的假密钥不在扫描目录内）。
_SECRET_PATTERNS = (
    re.compile(r"sk-live-[A-Za-z0-9]{12,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
)

_SCAN_DIRS = ("packages", "apps")


def _iter_source_files() -> Iterator[Path]:
    for base in _SCAN_DIRS:
        for path in (REPO_ROOT / base).rglob("*.py"):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            yield path


def test_no_hardcoded_secrets_in_source() -> None:
    """源码中无硬编码真实密钥特征。"""
    offenders: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(REPO_ROOT)} ~ /{pattern.pattern}/")
    assert not offenders, f"疑似硬编码密钥：{offenders}"


def test_env_example_uses_placeholder_and_declares_w6_settings() -> None:
    """``.env.example`` 密钥为占位；且声明 W6 新增配置项。"""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    match = re.search(r"^ASTRA_SECRET_KEY=(.*)$", text, re.MULTILINE)
    assert match is not None, ".env.example 缺少 ASTRA_SECRET_KEY"
    placeholder = match.group(1).strip().lower()
    assert placeholder, "ASTRA_SECRET_KEY 不得为空"
    # 占位符须显著「非真实密钥」。
    assert any(token in placeholder for token in ("change-me", "replace", "example", "changeme"))
    for pattern in _SECRET_PATTERNS:
        assert not pattern.search(text), ".env.example 含疑似真实密钥"

    # W6 / T1-31：新增配置项须在示例中声明。
    assert "ASTRA_RUN_TIMEOUT_MS=900000" in text
    assert "ASTRA_SSE_HEARTBEAT_SECONDS=15" in text
