"""``filesystem`` Tool 路径限定（Workspace 内）单测。

覆盖：Workspace 内 read / list 正常；``..`` 逃逸、绝对越界、``permission_scope`` 白名单外
一律拒绝；write / delete **必过 Sandbox**。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from astra_core import DomainError
from astra_domain import PermissionScope
from astra_sandbox import LocalProcessSandboxProvider
from astra_tool import FilesystemTool, ToolContext


def _ctx(tmp_path: Path, **kwargs: object) -> ToolContext:
    return ToolContext(workspace_root=str(tmp_path), **kwargs)  # type: ignore[arg-type]


def test_read_within_workspace(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    result = FilesystemTool().execute({"action": "read", "path": "a.txt"}, _ctx(tmp_path))
    assert result.ok and result.output == "hello"


def test_list_within_workspace(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    result = FilesystemTool().execute({"action": "list", "path": "."}, _ctx(tmp_path))
    assert result.ok and result.output == ["a.txt", "b.txt"]


def test_parent_escape_denied(tmp_path: Path) -> None:
    with pytest.raises(DomainError):
        FilesystemTool().execute({"action": "read", "path": "../../etc/passwd"}, _ctx(tmp_path))


def test_absolute_outside_denied(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(DomainError):
        FilesystemTool().execute({"action": "read", "path": str(outside)}, _ctx(tmp_path))


def test_scope_whitelist_limits_access(tmp_path: Path) -> None:
    (tmp_path / "allowed").mkdir()
    (tmp_path / "allowed" / "x.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "s.txt").write_text("no", encoding="utf-8")
    ctx = _ctx(tmp_path, permission_scope=PermissionScope(paths=["allowed"]))

    allowed = FilesystemTool().execute({"action": "read", "path": "allowed/x.txt"}, ctx)
    assert allowed.ok and allowed.output == "ok"
    with pytest.raises(DomainError):
        FilesystemTool().execute({"action": "read", "path": "secret/s.txt"}, ctx)


def test_write_requires_sandbox(tmp_path: Path) -> None:
    with pytest.raises(DomainError):
        FilesystemTool().execute(
            {"action": "write", "path": "a.txt", "content": "x"}, _ctx(tmp_path)
        )


def test_write_and_delete_via_sandbox(tmp_path: Path) -> None:
    provider = LocalProcessSandboxProvider(workspace_root=str(tmp_path))
    ctx = _ctx(tmp_path, sandbox=provider)

    written = FilesystemTool().execute(
        {"action": "write", "path": "sub/a.txt", "content": "hello"}, ctx
    )
    assert written.ok
    assert (tmp_path / "sub" / "a.txt").read_text(encoding="utf-8") == "hello"

    read = FilesystemTool().execute({"action": "read", "path": "sub/a.txt"}, ctx)
    assert read.output == "hello"

    deleted = FilesystemTool().execute({"action": "delete", "path": "sub/a.txt"}, ctx)
    assert deleted.ok
    assert not (tmp_path / "sub" / "a.txt").exists()
