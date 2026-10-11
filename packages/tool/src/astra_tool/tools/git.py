"""``git`` Tool（设计 §2.5.2）：clone / status / diff / commit / branch，**必过 Sandbox**。

- 强制危险子命令拦截（force push / ``reset --hard`` / 内嵌凭证 / 写凭证 helper，D-03 / D-04）；
- 凭据走**按 run 签发的短期令牌**（§5 #17），**禁注入长期 PAT**——W4 不注入任何长期凭证。
"""

from __future__ import annotations

from typing import Any

from astra_core import ErrorCode

from ..base import BaseTool, ToolMetadata, ToolPermissionRequirement, ToolResult, ToolSpec
from ..security import check_git_command

__all__ = ["GitTool"]

#: 动作 → git 子命令映射。
_GIT_SUBCOMMANDS: dict[str, str] = {
    "clone": "clone",
    "status": "status",
    "diff": "diff",
    "commit": "commit",
    "branch": "branch",
}


class GitTool(BaseTool):
    """Git 操作工具（工作副本在沙箱 / Workspace 内）。"""

    SPEC = ToolSpec(
        metadata=ToolMetadata(
            name="git",
            display_name="Git",
            description="在沙箱内执行 git clone / status / diff / commit / branch",
            category="vcs",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["clone", "status", "diff", "commit", "branch"],
                },
                "args": {"type": "array", "items": {"type": "string"}},
                "timeout_ms": {"type": "integer", "minimum": 1},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        permission=ToolPermissionRequirement(action="WRITE"),
        requires_sandbox=True,
    )

    def run(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        """校验危险子命令后经沙箱执行 git。"""
        action = str(args["action"])
        subcommand = _GIT_SUBCOMMANDS.get(action)
        if subcommand is None:  # pragma: no cover - Schema enum 已拦截
            return ToolResult.failure(
                f"未知 git 动作：{action}", code=ErrorCode.VALIDATION_ERROR.value
            )

        extra = [str(item) for item in (args.get("args") or [])]
        check_git_command([subcommand, *extra])

        argv = ["git", subcommand, *extra]
        sandbox = ctx.require_sandbox()
        session = ctx.ensure_session()
        result = sandbox.exec(
            session,
            argv,
            timeout_ms=args.get("timeout_ms"),
            cwd=session.workdir,
        )
        if result.timed_out:
            return ToolResult.failure(
                "git 执行超时",
                code=ErrorCode.VALIDATION_ERROR.value,
                sandbox_session_id=session.id,
                duration_ms=result.duration_ms,
            )
        if result.exit_code != 0:
            return ToolResult.failure(
                result.stderr or f"git 退出码 {result.exit_code}",
                code=ErrorCode.INTERNAL_ERROR.value,
                sandbox_session_id=session.id,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
            )
        return ToolResult.success(
            result.stdout,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            sandbox_session_id=session.id,
        )
