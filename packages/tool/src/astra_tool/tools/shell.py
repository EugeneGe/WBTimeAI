"""``shell`` Tool（设计 §2.5.2）：执行命令，**必过 Sandbox**（禁 Host 直执行）。"""

from __future__ import annotations

import shlex
from typing import Any

from astra_core import ErrorCode

from ..base import BaseTool, ToolMetadata, ToolPermissionRequirement, ToolResult, ToolSpec
from ..security import check_command

__all__ = ["ShellTool"]


class ShellTool(BaseTool):
    """Shell 命令执行工具（唯一执行出口为 ``SandboxProvider``）。"""

    SPEC = ToolSpec(
        metadata=ToolMetadata(
            name="shell",
            display_name="Shell",
            description="在沙箱内执行 shell 命令（禁 Host 直执行）",
            category="system",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": ["string", "array"],
                },
                "timeout_ms": {"type": "integer", "minimum": 1},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        permission=ToolPermissionRequirement(action="EXECUTE"),
        requires_sandbox=True,
    )

    def run(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        """校验危险命令后经沙箱执行。"""
        command = args["command"]
        check_command(command)

        argv = self._to_argv(command)
        if not argv:
            return ToolResult.failure("命令为空", code=ErrorCode.VALIDATION_ERROR.value)

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
                "命令执行超时",
                code=ErrorCode.VALIDATION_ERROR.value,
                sandbox_session_id=session.id,
                duration_ms=result.duration_ms,
            )
        if result.exit_code != 0:
            return ToolResult.failure(
                result.stderr or f"命令退出码 {result.exit_code}",
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

    @staticmethod
    def _to_argv(command: Any) -> list[str]:
        """把命令归一化为 argv（字符串按 ``shlex`` 拆分，不落 shell）。"""
        if isinstance(command, str):
            return shlex.split(command)
        if isinstance(command, (list, tuple)):
            return [str(part) for part in command]
        return []
