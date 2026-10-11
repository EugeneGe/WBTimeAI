"""``ToolExecutor`` per-call 权限校验器单测（W8 / A36 裁定 §5.2-①）。

验证机制③（``ToolExecutor.execute`` 增可选 per-call ``permission_checker``）：

- **per-call 覆盖**：传 ALLOW 校验器 → 覆盖装配期默认（deny）→ 工具**放行**；
- **回退默认**：不传 → 回退装配期默认（无规则 = deny-by-default）→ ``DENIED``；
- **隔离断言**：per-call 校验器**不写回** :attr:`ToolExecutor._checker`（并发隔离，裁定 §4）；
- **双向覆盖**：装配期 ALLOW → per-call DENY → ``DENIED``（覆盖是「替换」而非「或」）。
"""

from __future__ import annotations

from astra_domain import (
    TOOL_CALL_STATUS_DENIED,
    TOOL_CALL_STATUS_SUCCESS,
    ToolEffect,
    ToolPermission,
)
from astra_runtime import RuntimePermissionChecker, ToolCallRequest, ToolExecutor
from astra_tool import PermissionChecker, ToolContext, ToolRegistry

from tests.unit.runtime_stubs import EchoTool, allow_tool


def _make_executor(
    *, default: RuntimePermissionChecker | None = None, name: str = "echo"
) -> tuple[ToolExecutor, EchoTool]:
    """构造一个只注册 ``echo`` 工具的 :class:`ToolExecutor`。"""
    tool = EchoTool(name=name, output={"echoed": True})
    registry = ToolRegistry()
    registry.register(name, tool)
    executor = ToolExecutor(tool_registry=registry, permission_checker=default)
    return executor, tool


def _request(name: str = "echo") -> ToolCallRequest:
    """构造一次工具调用请求。"""
    return ToolCallRequest(name=name, arguments={"x": 1})


def _ctx() -> ToolContext:
    """构造一个最小工具执行上下文。"""
    return ToolContext(tenant_id="tenant-1", agent_id="agent-1")


def _deny_all() -> RuntimePermissionChecker:
    """无任何规则的校验器（deny-by-default）。"""
    return RuntimePermissionChecker(PermissionChecker())


def _deny_tool(name: str) -> RuntimePermissionChecker:
    """显式 DENY 指定工具的校验器。"""
    return RuntimePermissionChecker(
        PermissionChecker(
            permissions=[ToolPermission(tool_id=name, action="EXECUTE", effect="DENY")]
        )
    )


def test_per_call_checker_overrides_default_deny() -> None:
    """默认 deny（无规则）→ per-call ALLOW 覆盖 → 工具放行（SUCCESS）。"""
    executor, _tool = _make_executor(default=_deny_all())

    result = executor.execute(
        _request(),
        ctx=_ctx(),
        permission_checker=RuntimePermissionChecker(allow_tool("echo")),
    )

    assert result.status == TOOL_CALL_STATUS_SUCCESS
    assert result.ok is True
    assert result.output == {"echoed": True}


def test_without_per_call_checker_falls_back_to_default_deny() -> None:
    """不传 per-call → 回退装配期默认（无规则）→ ``DENIED``。"""
    executor, _tool = _make_executor(default=_deny_all())

    result = executor.execute(_request(), ctx=_ctx())

    assert result.status == TOOL_CALL_STATUS_DENIED
    assert result.ok is False
    assert result.error_code == "PERMISSION_DENIED"


def test_per_call_checker_is_not_written_back_to_singleton() -> None:
    """隔离断言：per-call 校验器**不写回** :attr:`ToolExecutor._checker`（并发隔离）。"""
    default = _deny_all()
    executor, _tool = _make_executor(default=default)
    assert executor._checker is default  # noqa: SLF001 - 隔离探针（裁定 §4）
    assert default.delegate._rules == {}  # noqa: SLF001 - 装配期默认无规则（deny）

    # 传 per-call ALLOW 覆盖一次 → 放行。
    allowed = RuntimePermissionChecker(allow_tool("echo"))
    assert (
        executor.execute(_request(), ctx=_ctx(), permission_checker=allowed).status
        == TOOL_CALL_STATUS_SUCCESS
    )

    # 单例私有校验器**未被改写**：仍是原对象、仍无规则。
    assert executor._checker is default  # noqa: SLF001
    assert executor._checker.delegate._rules == {}  # noqa: SLF001
    # 且 per-call 校验器自身**未**被污染（独立规则 dict）。
    assert allowed.delegate._rules == {("echo", "EXECUTE"): ToolEffect.ALLOW.value}

    # 再不带 per-call 调用 → 仍回退默认 deny（证明未串写）。
    assert executor.execute(_request(), ctx=_ctx()).status == TOOL_CALL_STATUS_DENIED


def test_per_call_checker_can_deny_even_when_default_allows() -> None:
    """双向覆盖：装配期 ALLOW → per-call DENY → ``DENIED``（覆盖 = 替换）。"""
    executor, _tool = _make_executor(default=RuntimePermissionChecker(allow_tool("echo")))

    # 不带 per-call → 走默认 ALLOW → SUCCESS。
    assert executor.execute(_request(), ctx=_ctx()).status == TOOL_CALL_STATUS_SUCCESS

    # 带 per-call DENY → 覆盖默认 → DENIED。
    result = executor.execute(_request(), ctx=_ctx(), permission_checker=_deny_tool("echo"))
    assert result.status == TOOL_CALL_STATUS_DENIED


def test_two_distinct_per_call_checkers_do_not_interfere() -> None:
    """两次调用分别传不同 checker，互不影响（per-call 作用域隔离）。"""
    executor, _tool = _make_executor(default=_deny_all())

    allowed = RuntimePermissionChecker(allow_tool("echo"))
    denied = _deny_all()

    first = executor.execute(_request(), ctx=_ctx(), permission_checker=allowed)
    second = executor.execute(_request(), ctx=_ctx(), permission_checker=denied)
    third = executor.execute(_request(), ctx=_ctx(), permission_checker=allowed)

    assert first.status == TOOL_CALL_STATUS_SUCCESS
    assert second.status == TOOL_CALL_STATUS_DENIED
    assert third.status == TOOL_CALL_STATUS_SUCCESS


def test_default_none_executor_is_deny_by_default() -> None:
    """未注入装配期校验器（``None``）→ 缺省仍 deny-by-default。"""
    executor, _tool = _make_executor(default=None)
    assert executor.execute(_request(), ctx=_ctx()).status == TOOL_CALL_STATUS_DENIED
