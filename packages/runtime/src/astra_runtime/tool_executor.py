"""``ToolExecutor``（经 ``PermissionChecker`` → ``Tool``，必要时经 Sandbox；设计 §2.5 / §2.7）。

- 解析工具（未注册 → ``FAILED`` / ``NOT_FOUND``）；
- **执行前**经注入的权限校验器逐次校验（``DENY`` → ``DENIED``，不执行）；
- 需沙箱的工具：注入 :class:`~astra_sandbox.SandboxProvider` 句柄（**唯一执行出口**，核心原则 ⑪）；
- 记录耗时；耗时超 ``tool_timeout_ms`` → ``FAILED`` + ``error=TOOL_TIMEOUT``（Run 可继续）。

🔴 本执行器**不写库**；持久化（``tool_call`` 行）由 ``ExecutionManager`` 经注入仓储完成。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from astra_core import DomainError, ErrorCode
from astra_domain import TOOL_CALL_STATUS_DENIED, TOOL_TYPE_BUILTIN, ToolEffect
from astra_domain import TOOL_CALL_STATUS_FAILED as FAILED_STATUS
from astra_domain import TOOL_CALL_STATUS_SUCCESS as SUCCESS_STATUS
from astra_domain.constants import DEFAULT_TOOL_TIMEOUT_MS
from astra_tool import ToolRegistry

from .model_executor import ToolCallRequest
from .permission_checker import RuntimePermissionChecker

__all__ = ["ToolExecutionResult", "ToolExecutor"]


@dataclass
class ToolExecutionResult:
    """一次工具执行的结果（供 ``ExecutionManager`` 落 ``tool_call`` 行）。"""

    status: str
    ok: bool
    tool_name: str = ""
    tool_id: str | None = None
    tool_type: str = TOOL_TYPE_BUILTIN
    tool_ref: dict[str, Any] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str | None = None
    error_code: str | None = None
    duration_ms: int = 0
    sandbox_session_id: str | None = None
    sandbox_session: Any = None
    timed_out: bool = False


class ToolExecutor:
    """工具执行器（权限校验 + 沙箱注入 + 超时判定）。"""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        permission_checker: RuntimePermissionChecker | None = None,
        sandbox_provider: Any = None,
        tool_timeout_ms: int = DEFAULT_TOOL_TIMEOUT_MS,
    ) -> None:
        self._registry = tool_registry
        self._checker = permission_checker or RuntimePermissionChecker()
        self._sandbox = sandbox_provider
        self._tool_timeout_ms = tool_timeout_ms

    @property
    def tool_timeout_ms(self) -> int:
        """单次工具调用超时（毫秒）。"""
        return self._tool_timeout_ms

    def execute(
        self,
        request: ToolCallRequest,
        *,
        ctx: Any,
        attempt: int = 1,
        tool_timeout_ms: int | None = None,
        permission_checker: RuntimePermissionChecker | None = None,
    ) -> ToolExecutionResult:
        """执行一次工具调用（不写库）。

        Args:
            request: 工具调用请求（名 + 入参）。
            ctx: 注入的 :class:`~astra_tool.ToolContext`。
            attempt: 尝试序号（仅记录用途）。
            tool_timeout_ms: 本次超时覆盖（``None`` 时用装配期默认，支持按 Agent 版本数据驱动）。
            permission_checker: **本次调用**的权限校验器覆盖（per-call）；``None`` 时回退装配期
                默认 :attr:`_checker`（deny-by-default）。Application 按 ``agent_id`` 解析后经
                ``RunContext`` / 本形参**per-run** 传入——**不写回** :attr:`_checker`（裁定 §4）。

        Returns:
            :class:`ToolExecutionResult`。
        """
        timeout_ms = self._tool_timeout_ms if tool_timeout_ms is None else int(tool_timeout_ms)
        # per-call 覆盖：仅用于本次调用，绝不写回共享单例 ``self._checker``（并发隔离，裁定 §4）。
        checker = permission_checker if permission_checker is not None else self._checker
        start = time.perf_counter()
        try:
            tool = self._registry.get(request.name)
        except DomainError as exc:
            return ToolExecutionResult(
                status=FAILED_STATUS,
                ok=False,
                tool_name=request.name,
                arguments=dict(request.arguments),
                error=exc.message,
                error_code=str(exc.code),
                duration_ms=_elapsed_ms(start),
            )

        action = tool.spec.permission.action
        effect = checker.check(ctx, tool, action)
        if effect is not ToolEffect.ALLOW:
            return ToolExecutionResult(
                status=TOOL_CALL_STATUS_DENIED,
                ok=False,
                tool_name=tool.spec.name,
                tool_id=getattr(tool, "tool_id", None),
                tool_type=getattr(tool.spec, "tool_type", TOOL_TYPE_BUILTIN),
                tool_ref=_tool_ref(tool),
                arguments=dict(request.arguments),
                error="权限拒绝",
                error_code=str(ErrorCode.PERMISSION_DENIED),
                duration_ms=_elapsed_ms(start),
            )

        if (
            tool.spec.requires_sandbox
            and getattr(ctx, "sandbox", None) is None
            and self._sandbox is not None
        ):
            ctx.sandbox = self._sandbox

        try:
            result = tool.execute(dict(request.arguments), ctx)
        except Exception as exc:  # noqa: BLE001 - 工具异常须落为失败结果
            return ToolExecutionResult(
                status=FAILED_STATUS,
                ok=False,
                tool_name=tool.spec.name,
                tool_id=getattr(tool, "tool_id", None),
                tool_type=getattr(tool.spec, "tool_type", TOOL_TYPE_BUILTIN),
                tool_ref=_tool_ref(tool),
                arguments=dict(request.arguments),
                error=str(exc),
                error_code=str(ErrorCode.INTERNAL_ERROR),
                duration_ms=_elapsed_ms(start),
                sandbox_session=getattr(ctx, "sandbox_session", None),
                sandbox_session_id=_session_id(getattr(ctx, "sandbox_session", None)),
            )

        duration_ms = _elapsed_ms(start)
        session = getattr(ctx, "sandbox_session", None)
        if duration_ms > timeout_ms:
            return ToolExecutionResult(
                status=FAILED_STATUS,
                ok=False,
                tool_name=tool.spec.name,
                tool_id=getattr(tool, "tool_id", None),
                tool_type=getattr(tool.spec, "tool_type", TOOL_TYPE_BUILTIN),
                tool_ref=_tool_ref(tool),
                arguments=dict(request.arguments),
                output=result.output,
                error="工具执行超时",
                error_code=str(ErrorCode.TOOL_TIMEOUT),
                duration_ms=duration_ms,
                sandbox_session=session,
                sandbox_session_id=_session_id(session),
                timed_out=True,
            )
        if result.ok:
            return ToolExecutionResult(
                status=SUCCESS_STATUS,
                ok=True,
                tool_name=tool.spec.name,
                tool_id=getattr(tool, "tool_id", None),
                tool_type=getattr(tool.spec, "tool_type", TOOL_TYPE_BUILTIN),
                tool_ref=_tool_ref(tool),
                arguments=dict(request.arguments),
                output=result.output,
                duration_ms=duration_ms,
                sandbox_session=session,
                sandbox_session_id=_session_id(session),
            )
        return ToolExecutionResult(
            status=FAILED_STATUS,
            ok=False,
            tool_name=tool.spec.name,
            tool_id=getattr(tool, "tool_id", None),
            tool_type=getattr(tool.spec, "tool_type", TOOL_TYPE_BUILTIN),
            tool_ref=_tool_ref(tool),
            arguments=dict(request.arguments),
            output=result.output,
            error=result.error or "工具执行失败",
            error_code=result.error_code or str(ErrorCode.INTERNAL_ERROR),
            duration_ms=duration_ms,
            sandbox_session=session,
            sandbox_session_id=_session_id(session),
        )


def _elapsed_ms(start: float) -> int:
    """返回自 ``start``（``perf_counter``）以来的毫秒数。"""
    return int((time.perf_counter() - start) * 1000)


def _session_id(session: Any) -> str | None:
    """从沙箱会话对象抽取 ``id``（可空）。"""
    if session is None:
        return None
    return getattr(session, "id", None)


def _tool_ref(tool: Any) -> dict[str, Any]:
    """构造工具引用 ``{kind, id, name, version}``。"""
    return {
        "kind": getattr(tool.spec, "tool_type", TOOL_TYPE_BUILTIN),
        "id": getattr(tool, "tool_id", None),
        "name": tool.spec.name,
        "version": getattr(tool, "version", None),
    }
