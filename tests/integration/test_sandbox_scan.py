"""唯一执行出口扫描断言（``I-P1-11``，W4 架构裁定 Q2）。

口径（机械可执行）：

- **扫描 target**：``packages/tool/**`` + ``packages/runtime/**``（T1-19 原文范围）；
- **allowlist（显式排除）**：
  - ``packages/sandbox/**``——“**唯一合法执行出口**”：``LocalProcessSandboxProvider`` 必须
    使用 ``subprocess``、``DockerSandboxProvider`` 必须 ``import docker``。把出口扫成违规 =
    把出口当违禁，逻辑自毁；
  - ``apps/cli/**``——``astra doctor`` 以 ``subprocess.run(["docker","info"])`` **探测** Docker，
    属允许的诊断用途（非执行路径）；
- **forbidden**：``subprocess``（任意导入）/ ``os.system`` / ``os.popen``（调用点）/
  ``docker``（顶层导入，含 ``docker.from_env``）——**按正则**（导入行 + 调用点），不得仅按子串匹配；
- **正向断言**：``packages/sandbox`` **确实存在** ``subprocess`` / ``docker`` 使用点，
  以防「扫了但没出口」的假绿。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = REPO_ROOT / "packages"

#: 扫描目标（源包名）。
TARGET_PACKAGES: tuple[str, ...] = ("tool", "runtime")

#: allowlist 理由见模块 docstring。
_EXCLUDED_PACKAGES: frozenset[str] = frozenset({"sandbox"})

_IMPORT_SUBPROCESS = re.compile(r"^\s*(?:from\s+subprocess\b|import\s+subprocess\b)", re.MULTILINE)
_IMPORT_DOCKER = re.compile(r"^\s*(?:from\s+docker\b|import\s+docker\b)", re.MULTILINE)
_CALL_OS = re.compile(r"\bos\.(?:system|popen)\s*\(")
_CALL_DOCKER = re.compile(r"\bdocker\.from_env\s*\(")

_FORBIDDEN = (
    (_IMPORT_SUBPROCESS, "subprocess 导入"),
    (_IMPORT_DOCKER, "docker 顶层导入"),
    (_CALL_OS, "os.system/os.popen 调用"),
    (_CALL_DOCKER, "docker.from_env 调用"),
)


def _iter_python_files(base: Path) -> Iterator[Path]:
    """遍历 ``.py`` 文件（跳过 ``__pycache__`` / ``.venv``）。"""
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        yield path


def test_packages_have_no_direct_execution() -> None:
    """全 ``packages/**``（**显式排除** allowlist）内无直调 subprocess / os.system / docker。

    W4 架构裁定 Q2 §2.1「建议扩至全部 ``packages/**``（除 allowlist）」——比 T1-19 原文
    （仅 ``tool`` + ``runtime``）**更强**，形成「唯一执行出口」强断言：除 ``packages/sandbox``
    （唯一合法出口）外，任何包都不得直调宿主进程。

    ``TARGET_PACKAGES`` 作为**必须覆盖的子集**显式断言在扫描集内（防误删）。
    """
    # 排除项不得与被强制覆盖的子集冲突。
    assert set(TARGET_PACKAGES).isdisjoint(_EXCLUDED_PACKAGES)

    scanned = [
        pkg.name
        for pkg in sorted(PACKAGES.iterdir())
        if pkg.is_dir() and pkg.name not in _EXCLUDED_PACKAGES
    ]
    for target in TARGET_PACKAGES:
        # 尚未落地的包（W5 的 ``runtime``）允许缺席；已存在则必须被扫描覆盖。
        if (PACKAGES / target).is_dir():
            assert target in scanned, f"扫描集必须覆盖 packages/{target}（T1-19 原文范围）"

    violations: list[str] = []
    for package in scanned:
        for path in _iter_python_files(PACKAGES / package):
            text = path.read_text(encoding="utf-8")
            for regex, label in _FORBIDDEN:
                if regex.search(text):
                    violations.append(f"{path.relative_to(REPO_ROOT)} → {label}")
    assert not violations, "发现直接执行点（应统一经 SandboxProvider）：\n" + "\n".join(violations)


def test_sandbox_exclusion_is_not_vacuous() -> None:
    """正向断言：``packages/sandbox``（被 allowlist 排除的**唯一执行出口**）确实存在执行点。"""
    sandbox_src = PACKAGES / "sandbox" / "src" / "astra_sandbox"
    assert sandbox_src.is_dir(), "packages/sandbox 应存在（唯一合法执行出口）"

    local_text = (sandbox_src / "local_process_provider.py").read_text(encoding="utf-8")
    assert _IMPORT_SUBPROCESS.search(local_text), "LocalProcess 应存在 subprocess 使用点（出口）"

    docker_text = "\n".join(
        (sandbox_src / name).read_text(encoding="utf-8")
        for name in ("docker_provider.py", "availability.py")
        if (sandbox_src / name).is_file()
    )
    assert _IMPORT_DOCKER.search(docker_text), "Docker/availability 应存在 docker 使用点（出口）"


def test_cli_docker_probe_is_allowlisted() -> None:
    """``apps/cli`` doctor 以 ``docker`` **探测**（合法诊断，allowlist 理由见此断言）。"""
    cli_module = REPO_ROOT / "apps" / "cli" / "src" / "astra_cli" / "doctor_checks.py"
    assert cli_module.is_file(), "apps/cli doctor_checks.py 应存在"
    assert "docker" in cli_module.read_text(encoding="utf-8")
