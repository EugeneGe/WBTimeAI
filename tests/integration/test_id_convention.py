"""ID 唯一入口约定扫描断言（决策 D2）。

断言：
1. ``generate_id`` 定义于 ``astra_core.id``；
2. ``packages`` / ``apps`` 源码中**不存在** ``uuid4`` 用法（唯一 ID 入口约束）。

扫描基于 ``tokenize``（仅统计标识符 token），因此**不会**误命中字符串 / 注释 /
文档中出现的 ``uuid4`` 字样，只捕获真实代码里的 ``uuid4`` / ``uuid.uuid4``。
"""

from __future__ import annotations

import io
import tokenize
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = (REPO_ROOT / "packages", REPO_ROOT / "apps")

#: 违规标识符：``uuid4``（同时覆盖 ``uuid.uuid4`` 的属性访问）。
_FORBIDDEN_IDENTIFIER = "uuid4"


def _iter_python_files(base: Path) -> Iterator[Path]:
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        yield path


def _uses_forbidden_identifier(text: str) -> bool:
    """基于 token 判断源码是否真实使用了 ``uuid4``。"""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type == tokenize.NAME and token.string == _FORBIDDEN_IDENTIFIER:
                return True
    except (tokenize.TokenError, IndentationError):
        # 无法解析的文件不视为违规（避免误报）。
        return False
    return False


def test_generate_id_defined_in_core_id() -> None:
    id_module = REPO_ROOT / "packages" / "core" / "src" / "astra_core" / "id.py"
    assert id_module.is_file()
    assert "def generate_id(" in id_module.read_text(encoding="utf-8")


def test_no_uuid4_usage_outside_unique_entrypoint() -> None:
    offenders: list[str] = []
    for base in SCAN_DIRS:
        for path in _iter_python_files(base):
            text = path.read_text(encoding="utf-8")
            if _uses_forbidden_identifier(text):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"检测到 uuid4 用法，违反 D2 唯一 ID 入口：{offenders}"


#: Phase 1 新增 / 扩展包（须确认被唯一 ID 入口约束覆盖）。
PHASE1_PACKAGES: tuple[str, ...] = (
    "agent",
    "conversation",
    "runtime",
    "sandbox",
    "tool",
    "model",
    "event",
)


def test_phase1_packages_are_present_and_scanned() -> None:
    """正向断言：Phase 1 新包存在且**确实被扫描**，逐包无 ``uuid4``（防假绿）。"""
    for package in PHASE1_PACKAGES:
        package_dir = REPO_ROOT / "packages" / package
        assert package_dir.is_dir(), f"Phase 1 包缺失：packages/{package}"
        files = list(_iter_python_files(package_dir))
        assert files, f"packages/{package} 未扫描到任何 .py（扫描集为空）"
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in files
            if _uses_forbidden_identifier(path.read_text(encoding="utf-8"))
        ]
        assert not offenders, f"packages/{package} 出现 uuid4（违反 D2）：{offenders}"
