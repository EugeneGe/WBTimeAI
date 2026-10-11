"""工具安全测试（I-P1-19 / N-P1-05）：路径逃逸 / SSRF / 非法 scope（mark security）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain import PermissionScope
from astra_tool import FilesystemTool, ToolContext
from astra_tool.security import (
    check_egress,
    resolve_within_workspace,
    validate_scope_paths,
)

pytestmark = pytest.mark.security


def _ctx(tmp_path: Path, **kwargs: object) -> ToolContext:
    return ToolContext(workspace_root=str(tmp_path), **kwargs)  # type: ignore[arg-type]


def _make_rebinding_resolver() -> object:
    """DNS rebinding：首解析公网、二次解析内网。"""
    state = {"n": 0}

    def resolver(host: str) -> list[str]:
        state["n"] += 1
        return ["93.184.216.34"] if state["n"] == 1 else ["127.0.0.1"]

    return resolver


# -- 路径逃逸 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["../../etc/passwd", "../secrets.txt", "/etc/passwd", "/var/log/syslog"],
)
def test_path_escape_denied(path: str, tmp_path: Path) -> None:
    with pytest.raises(DomainError) as excinfo:
        FilesystemTool().execute({"action": "read", "path": path}, _ctx(tmp_path))
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED


def test_symlink_escape_denied(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建符号链接")
    with pytest.raises(DomainError):
        FilesystemTool().execute({"action": "read", "path": "link.txt"}, _ctx(tmp_path))


def test_scope_glob_outside_workspace_rejected(tmp_path: Path) -> None:
    with pytest.raises(DomainError) as excinfo:
        validate_scope_paths(["/etc/**"], workspace_root=tmp_path)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_scope_dotdot_rejected() -> None:
    with pytest.raises(DomainError) as excinfo:
        validate_scope_paths(["../escape/**"])
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR


def test_resolve_within_workspace_ok(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("x", encoding="utf-8")
    resolved = resolve_within_workspace("ok.txt", workspace_root=tmp_path, must_exist=True)
    assert resolved == (tmp_path / "ok.txt").resolve()


# -- SSRF -------------------------------------------------------------------


def test_metadata_endpoint_denied() -> None:
    with pytest.raises(DomainError) as excinfo:
        check_egress(
            "http://169.254.169.254/latest/meta-data",
            allowlist=["169.254.169.254"],
        )
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
    ],
)
def test_private_ip_literal_denied(url: str) -> None:
    host = url.split("//", 1)[1].split("/", 1)[0].strip("[]")
    with pytest.raises(DomainError):
        check_egress(url, allowlist=[host])


def test_dns_rebinding_denied() -> None:
    with pytest.raises(DomainError) as excinfo:
        check_egress(
            "http://rebind.example.com/",
            allowlist=["rebind.example.com"],
            resolver=_make_rebinding_resolver(),
        )
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED


def test_egress_default_deny_all() -> None:
    with pytest.raises(DomainError):
        check_egress("https://example.com/")


def test_egress_allowlisted_public_host_ok() -> None:
    pinned = check_egress(
        "https://example.com/",
        allowlist=["example.com"],
        resolver=lambda host: ["93.184.216.34"],
    )
    assert pinned == "93.184.216.34"


def test_http_tool_default_deny() -> None:
    from astra_tool import HttpTool

    with pytest.raises(DomainError):
        HttpTool().execute({"url": "https://example.com/"}, ToolContext())


def test_scope_restricts_filesystem_glob(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "other.txt").write_text("no", encoding="utf-8")
    ctx = _ctx(tmp_path, permission_scope=PermissionScope(paths=["sub/**"]))
    assert FilesystemTool().execute({"action": "read", "path": "sub/a.txt"}, ctx).ok
    with pytest.raises(DomainError):
        FilesystemTool().execute({"action": "read", "path": "other.txt"}, ctx)
