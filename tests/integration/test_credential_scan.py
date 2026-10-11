"""凭证明文扫描集成测试（W8 / T1-37；设计 §3-#4 ``I-P1-04`` / C-07）。

两类断言：

1. **静态扫描**：``packages`` / ``apps`` 源码中**无**硬编码真实凭证明文特征
   （``sk-…`` / ``AKIA…`` / PEM 私钥块）——排除 ``plugins/**`` 与 tests
   （测试以具辨识度假密钥验证「不泄漏」，属预期用法）；
2. **运行期不泄漏**：经 API 保存凭证时，**响应体 / 日志（caplog）均不含明文**，
   仅返回掩码（与 ``test_api_credentials`` 互补：此处以**扫描 + caplog** 强化）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 扫描根（业务代码；tests / plugins 显式排除）。
SCAN_ROOTS: tuple[Path, ...] = (REPO_ROOT / "packages", REPO_ROOT / "apps")

_EXCLUDED_PARTS: frozenset[str] = frozenset(
    {"plugins", "tests", "node_modules", ".venv", "__pycache__"}
)

#: 真实凭证明文特征（保守）。
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

#: 具辨识度明文（运行期泄漏断言用；不入源码扫描范围）。
_PLAINTEXT = "sk-live-SCAN-0123456789abcdef-DO-NOT-LEAK"


def _iter_source_files() -> Iterator[Path]:
    """遍历业务代码 ``.py``（显式排除 plugins / tests / 缓存）。"""
    for base in SCAN_ROOTS:
        for path in base.rglob("*.py"):
            if _EXCLUDED_PARTS & set(path.parts):
                continue
            yield path


def test_no_plaintext_credentials_in_source() -> None:
    """源码中无硬编码真实凭证明文特征。"""
    offenders: list[str] = []
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(REPO_ROOT)} ~ /{pattern.pattern}/")
    assert not offenders, "疑似硬编码凭证明文：\n" + "\n".join(offenders)


def test_credential_scan_is_not_vacuous() -> None:
    """正向断言：扫描集非空，且模式确能命中样例（防「扫了但模式失效」的假绿）。"""
    assert any(_iter_source_files()), "扫描集为空，凭证扫描可能失效"
    assert _CREDENTIAL_PATTERNS[0].search("token=sk-" + "A" * 24)
    assert _CREDENTIAL_PATTERNS[1].search("AKIA" + "A" * 16)
    assert _CREDENTIAL_PATTERNS[2].search("-----BEGIN RSA PRIVATE KEY-----")


def test_saving_credential_never_logs_or_returns_plaintext(
    client: Any, auth_headers: dict[str, str], caplog: Any
) -> None:
    """保存凭证：响应体与日志**均不含明文**，仅返回掩码。"""
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/v1/models/credentials",
            headers=auth_headers,
            json={"provider": "openai", "key_type": "api_key", "value": _PLAINTEXT},
        )
    assert response.status_code == 201, response.text
    body = response.json()["data"]
    assert body["masked_value"]
    assert _PLAINTEXT not in response.text
    assert _PLAINTEXT != body["masked_value"]
    # 日志（任意级别）不得出现明文。
    assert _PLAINTEXT not in caplog.text
