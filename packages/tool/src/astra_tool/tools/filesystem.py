"""``filesystem`` Tool（设计 §2.5.2）。

- ``read`` / ``list``：**不过沙箱**，但**限定 Workspace 内**（路径逃逸防护）；
- ``write`` / ``delete``：**必过 Sandbox**（``SandboxProvider`` 为唯一执行出口）；
- ``permission_scope.paths`` 白名单在动作级进一步收敛可访问路径。
"""

from __future__ import annotations

import sys
from typing import Any

from astra_core import ErrorCode

from ..base import BaseTool, ToolMetadata, ToolPermissionRequirement, ToolResult, ToolSpec
from ..security import resolve_within_workspace

__all__ = ["FilesystemTool"]

_READ_ACTIONS = frozenset({"read", "list"})
_SANDBOX_ACTIONS = frozenset({"write", "delete"})

_DELETE_CODE = (
    "import os, sys\n"
    "p = sys.argv[1]\n"
    "if os.path.isdir(p):\n"
    "    import shutil\n"
    "    shutil.rmtree(p)\n"
    "elif os.path.exists(p):\n"
    "    os.remove(p)\n"
)


class FilesystemTool(BaseTool):
    """Workspace 内文件读写工具（路径限定 + 写/删过沙箱）。"""

    SPEC = ToolSpec(
        metadata=ToolMetadata(
            name="filesystem",
            display_name="文件系统",
            description="在 Workspace 目录内 read / list / write / delete 文件",
            category="system",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "list", "write", "delete"],
                },
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
                "encoding": {"type": "string"},
            },
            "required": ["action", "path"],
            "additionalProperties": False,
        },
        permission=ToolPermissionRequirement(action="READ"),
        # read / list 不过沙箱；write / delete 在动作内**强制**过沙箱。
        requires_sandbox=False,
    )

    def run(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        """执行文件系统动作。"""
        action = str(args["action"])
        raw_path = str(args["path"])
        scope = getattr(ctx, "permission_scope", None)
        allowed_paths = list(scope.paths) if scope is not None else []

        target = resolve_within_workspace(
            raw_path,
            workspace_root=ctx.workspace_path(),
            allowed_paths=allowed_paths,
            must_exist=action in _READ_ACTIONS,
        )

        if action == "read":
            text = target.read_text(encoding=str(args.get("encoding") or "utf-8"))
            return ToolResult.success(text, path=str(target))

        if action == "list":
            entries = sorted(child.name for child in target.iterdir())
            return ToolResult.success(entries, path=str(target))

        if action == "write":
            content = args.get("content")
            if content is None:
                return ToolResult.failure(
                    "write 动作缺少 content", code=ErrorCode.VALIDATION_ERROR.value
                )
            return self._write(target, str(content), ctx)

        if action == "delete":
            return self._delete(target, ctx)

        return ToolResult.failure(  # pragma: no cover - Schema enum 已拦截
            f"未知动作：{action}", code=ErrorCode.VALIDATION_ERROR.value
        )

    def _write(self, target: Any, content: str, ctx: Any) -> ToolResult:
        """经 Sandbox 写入文件。"""
        sandbox = ctx.require_sandbox()
        session = ctx.ensure_session()
        relative = target.relative_to(ctx.workspace_path()).as_posix()
        sandbox.put_file(session, relative, content)
        return ToolResult.success(
            {"path": str(target), "bytes": len(content.encode("utf-8"))},
            sandbox_session_id=session.id,
        )

    def _delete(self, target: Any, ctx: Any) -> ToolResult:
        """经 Sandbox 删除文件 / 目录。"""
        sandbox = ctx.require_sandbox()
        session = ctx.ensure_session()
        relative = target.relative_to(ctx.workspace_path()).as_posix()
        result = sandbox.exec(
            session, [sys.executable, "-c", _DELETE_CODE, relative], cwd=session.workdir
        )
        if result.exit_code != 0:
            return ToolResult.failure(
                result.stderr or "删除失败",
                code=ErrorCode.INTERNAL_ERROR.value,
                sandbox_session_id=session.id,
            )
        return ToolResult.success({"path": str(target)}, sandbox_session_id=session.id)
