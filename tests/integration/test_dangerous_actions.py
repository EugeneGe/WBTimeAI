"""《首批危险动作清单》逐条参数化 DENY（``I-P1-10``）。

数据来源：``docs/设计/验收证据/manual-checklists/phase1-dangerous-actions.md``（D-01~D-19）。
D-01~D-17 映射到 ``astra_tool.security`` 模式拦截；D-18 / D-19 映射到沙箱资源 / 超时约束。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from astra_core import DomainError, ErrorCode
from astra_sandbox import LocalProcessSandboxProvider
from astra_tool import FilesystemTool, ToolContext
from astra_tool.security import (
    check_command,
    check_egress,
    check_git_command,
    check_python_code,
    validate_scope_paths,
)


def _read(path: str) -> Callable[[Path], None]:
    """构造「filesystem.read 指定路径」动作。"""

    def _call(tmp_path: Path) -> None:
        ctx = ToolContext(workspace_root=str(tmp_path))
        FilesystemTool().execute({"action": "read", "path": path}, ctx)

    return _call


def _rebinding_resolver() -> object:
    state = {"n": 0}

    def resolver(host: str) -> list[str]:
        state["n"] += 1
        return ["93.184.216.34"] if state["n"] == 1 else ["127.0.0.1"]

    return resolver


_DENY_CASES: list[tuple[str, Callable[[Path], object]]] = [
    ("D-01", lambda tmp: check_command("rm -rf /")),
    ("D-02", lambda tmp: check_command(":(){ :|:& };:")),
    ("D-03", lambda tmp: check_git_command(["push", "--force"])),
    ("D-04", lambda tmp: check_git_command(["config", "--global", "credential.helper", "store"])),
    ("D-05", lambda tmp: check_command("psql -c 'DROP DATABASE prod'")),
    ("D-06", _read("/etc/passwd")),
    ("D-07", _read(str(Path.home() / ".ssh" / "id_rsa"))),
    ("D-08", _read("../../etc/passwd")),
    ("D-09", _read("/var/log/syslog")),
    ("D-10", lambda tmp: validate_scope_paths(["/etc/**"], workspace_root=tmp)),
    (
        "D-11",
        lambda tmp: check_egress(
            "http://169.254.169.254/latest/meta-data", allowlist=["169.254.169.254"]
        ),
    ),
    (
        "D-12",
        lambda tmp: check_egress(
            "http://rebind.example.com/",
            allowlist=["rebind.example.com"],
            resolver=_rebinding_resolver(),
        ),
    ),
    ("D-13", lambda tmp: check_egress("https://example.com/")),
    ("D-14", lambda tmp: check_command("ls; rm -rf /")),
    ("D-15", lambda tmp: check_command("sudo rm -rf /")),
    (
        "D-16",
        lambda tmp: check_git_command(
            ["remote", "set-url", "origin", "https://x-access-token:ghp_x@github.com"]
        ),
    ),
    (
        "D-17",
        lambda tmp: check_python_code("open('k','w').write(os.environ['ASTRA_SECRET_KEY'])"),
    ),
]


@pytest.mark.security
@pytest.mark.parametrize(
    "case_id, action",
    [pytest.param(case[0], case[1], id=case[0]) for case in _DENY_CASES],
)
def test_dangerous_action_denied(
    case_id: str, action: Callable[[Path], object], tmp_path: Path
) -> None:
    with pytest.raises(DomainError) as excinfo:
        action(tmp_path)
    assert excinfo.value.code in {ErrorCode.PERMISSION_DENIED, ErrorCode.VALIDATION_ERROR}


# -- D-18 / D-19：沙箱资源与超时约束 ---------------------------------------


@pytest.mark.security
def test_d18_unbounded_output_truncated(tmp_path: Path) -> None:
    """D-18：无界输出被截断（资源耗尽缓解）。"""
    provider = LocalProcessSandboxProvider(workspace_root=str(tmp_path), max_output_chars=1000)
    session = provider.create_session()
    result = provider.exec(session, [sys.executable, "-c", "print('x' * 100000)"])
    assert len(result.stdout) <= 1000
    provider.destroy(session)


@pytest.mark.security
def test_d19_sleep_timeout_truncated(tmp_path: Path) -> None:
    """D-19：``sleep`` 超时 → 强制终止 + ``duration_ms`` 截断。"""
    provider = LocalProcessSandboxProvider(workspace_root=str(tmp_path))
    session = provider.create_session()
    result = provider.exec(
        session, [sys.executable, "-c", "import time; time.sleep(5)"], timeout_ms=300
    )
    assert result.timed_out is True
    assert result.exit_code == 124
    provider.destroy(session)


def test_checklist_ids_fully_covered() -> None:
    """断言 D-01~D-19 全部被参数化覆盖（防漏测）。"""
    covered = [case[0] for case in _DENY_CASES] + ["D-18", "D-19"]
    assert sorted(covered) == [f"D-{index:02d}" for index in range(1, 20)]
