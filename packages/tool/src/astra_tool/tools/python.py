"""``python`` Tool（设计 §2.5.2）：沙箱内解释器执行代码片段，**必过 Sandbox**。"""

from __future__ import annotations

import sys
from typing import Any

from astra_core import ErrorCode

from ..base import BaseTool, ToolMetadata, ToolPermissionRequirement, ToolResult, ToolSpec
from ..security import check_python_code

__all__ = ["PythonTool"]


class PythonTool(BaseTool):
    """Python 代码执行工具（在沙箱内以解释器执行）。"""

    SPEC = ToolSpec(
        metadata=ToolMetadata(
            name="python",
            display_name="Python",
            description="在沙箱内执行 Python 代码片段",
            category="system",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "minLength": 1},
                "timeout_ms": {"type": "integer", "minimum": 1},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
        permission=ToolPermissionRequirement(action="EXECUTE"),
        requires_sandbox=True,
    )

    def run(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        """校验危险代码后经沙箱执行。"""
        code = str(args["code"])
        check_python_code(code)

        sandbox = ctx.require_sandbox()
        session = ctx.ensure_session()
        result = sandbox.exec(
            session,
            [sys.executable, "-c", code],
            timeout_ms=args.get("timeout_ms"),
            cwd=session.workdir,
        )
        if result.timed_out:
            return ToolResult.failure(
                "代码执行超时",
                code=ErrorCode.VALIDATION_ERROR.value,
                sandbox_session_id=session.id,
                duration_ms=result.duration_ms,
            )
        if result.exit_code != 0:
            return ToolResult.failure(
                result.stderr or f"代码退出码 {result.exit_code}",
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
