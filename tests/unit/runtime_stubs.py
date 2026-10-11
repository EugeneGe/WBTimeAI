"""Runtime 测试公共桩件（stub Provider / fake Tool / 装配辅助）。

非 ``test_*`` 命名，故不被 pytest 收集；供单测与集成测试共用。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from astra_domain import AgentVersion, SandboxSession, ToolPermission
from astra_model import ChatResult, ModelRegistry, ModelRouter, TokenCount
from astra_tool import (
    PermissionChecker,
    ToolMetadata,
    ToolPermissionRequirement,
    ToolResult,
    ToolSpec,
)


class StubModelProvider:
    """伪模型 Provider：按脚本顺序返回 ``content``（用尽后重复最后一条）。"""

    def __init__(self, responses: Sequence[str], *, model: str = "stub-1") -> None:
        self._responses = list(responses)
        self._model = model
        self.calls = 0

    def _next(self) -> str:
        index = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[index]

    def chat(self, messages: Sequence[Any], **options: Any) -> ChatResult:
        """返回脚本中的下一条内容。"""
        return ChatResult(content=self._next(), model=self._model)

    def stream(self, messages: Sequence[Any], **options: Any) -> Iterator[str]:
        """流式：逐块产出脚本内容。"""
        yield self._next()

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Any]:
        """返回空嵌入。"""
        return []

    def count_tokens(self, text: str, **options: Any) -> TokenCount:
        """粗糙 token 估算。"""
        return TokenCount(count=max(1, len(text) // 4), model=self._model)


class EchoTool:
    """伪工具：返回固定输出（可配置失败 / 需沙箱）。"""

    def __init__(
        self,
        *,
        name: str = "echo",
        output: Any = "ok",
        ok: bool = True,
        error: str | None = None,
        error_code: str | None = None,
        requires_sandbox: bool = False,
        action: str = "EXECUTE",
    ) -> None:
        self.tool_id: str | None = None
        self.version: str | None = None
        self.spec = ToolSpec(
            metadata=ToolMetadata(name=name, display_name=name),
            input_schema={},
            permission=ToolPermissionRequirement(action=action),
            requires_sandbox=requires_sandbox,
        )
        self._output = output
        self._ok = ok
        self._error = error
        self._error_code = error_code

    def execute(self, args: Mapping[str, Any], ctx: Any) -> ToolResult:
        """返回预置结果（需沙箱时先 ``ensure_session`` 以模拟容器使用）。"""
        if (
            self.spec.requires_sandbox
            and ctx is not None
            and getattr(ctx, "sandbox", None) is not None
        ):
            ctx.ensure_session()
        if self._ok:
            return ToolResult.success(self._output)
        return ToolResult.failure(self._error or "工具失败", code=self._error_code)


def tool_call_content(name: str, arguments: dict[str, Any] | None = None) -> str:
    """构造模型「工具调用」文本（JSON 约定）。"""
    import json

    return json.dumps({"tool_calls": [{"name": name, "arguments": dict(arguments or {})}]})


def build_model_router(provider: Any, *, name: str = "stub") -> ModelRouter:
    """把 Provider 注册进 ``ModelRegistry`` 并构造 ``ModelRouter``。"""
    registry = ModelRegistry()
    registry.register(name, provider)
    return ModelRouter(registry)


class ErrorModelProvider:
    """伪模型 Provider：``chat`` 恒抛 ``DomainError``（模拟模型侧失败）。"""

    def __init__(self, *, code: Any = None, message: str = "model down") -> None:
        from astra_core import ErrorCode

        self._code = code or ErrorCode.INTERNAL_ERROR
        self._message = message
        self.calls = 0

    def chat(self, messages: Sequence[Any], **options: Any) -> ChatResult:
        """恒抛 ``DomainError``。"""
        from astra_core import DomainError

        self.calls += 1
        raise DomainError(self._message, code=self._code)

    def stream(self, messages: Sequence[Any], **options: Any) -> Iterator[str]:
        """恒抛 ``DomainError``。"""
        from astra_core import DomainError

        raise DomainError(self._message, code=self._code)

    def embeddings(self, texts: Sequence[str], **options: Any) -> list[Any]:
        """返回空嵌入。"""
        return []

    def count_tokens(self, text: str, **options: Any) -> TokenCount:
        """返回零计数。"""
        return TokenCount(count=0)


class FakeSandboxProvider:
    """伪沙箱 Provider（记录 create_session / destroy 次数；``destroy`` 幂等）。"""

    def __init__(self) -> None:
        self.created = 0
        self.destroyed = 0
        self.sessions: list[Any] = []

    @property
    def kind(self) -> str:
        """提供方种类。"""
        return "local_process"

    @property
    def available(self) -> bool:
        """恒可用。"""
        return True

    def create_session(
        self,
        *,
        workspace_id: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
        image: str | None = None,
        workdir: str | None = None,
    ) -> SandboxSession:
        """创建一个会话并记录。"""
        self.created += 1
        session = SandboxSession(
            run_id=run_id,
            workspace_id=workspace_id,
            workdir=workdir or "",
        )
        self.sessions.append(session)
        return session

    def exec(self, session: Any, command: Any, **options: Any):  # noqa: ANN201
        """返回成功执行结果。"""
        from astra_sandbox import ExecResult

        return ExecResult(exit_code=0)

    def put_file(self, session: Any, path: str, content: str) -> None:
        """无操作。"""
        return None

    def get_file(self, session: Any, path: str) -> str:
        """返回空串。"""
        return ""

    def destroy(self, session: Any) -> None:
        """销毁会话（幂等：重复调用只计一次要求，但不抛错）。"""
        self.destroyed += 1


def allow_tool(name: str, *, action: str = "EXECUTE") -> PermissionChecker:
    """构造放行指定工具 / 动作的 ``PermissionChecker``。"""
    return PermissionChecker(
        permissions=[ToolPermission(tool_id=name, action=action, effect="ALLOW")]
    )


def make_agent_version(
    *,
    system_prompt: str = "SYS",
    model: str = "stub-1",
    provider: str = "stub",
    max_iterations: int = 5,
    runtime_overrides: dict[str, Any] | None = None,
) -> AgentVersion:
    """构造一个内存 ``AgentVersion``（含 runtime_config）。"""
    runtime_config: dict[str, Any] = {"max_iterations": max_iterations}
    if runtime_overrides:
        runtime_config.update(runtime_overrides)
    return AgentVersion(
        agent_id="agent-1",
        version="v1",
        system_prompt=system_prompt,
        model_config={"provider": provider, "model": model, "temperature": 0.0},
        runtime_config=runtime_config,
        status="PUBLISHED",
        created_by="user-1",
    )


def build_session_factory(db_path: Path):
    """构造一个已建全部 ORM 表的 SQLite 会话工厂。"""
    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_database import Base, create_session_factory
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    return create_session_factory(engine), engine
