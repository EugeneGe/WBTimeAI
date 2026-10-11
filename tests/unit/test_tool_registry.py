"""``ToolRegistry`` 单测（注册 / 获取 / 列举 / 覆盖 / 入参 Schema 校验）。"""

from __future__ import annotations

from typing import Any

import pytest
from astra_core import DomainError, ValidationError
from astra_tool import (
    BUILTIN_TOOL_CLASSES,
    BaseTool,
    ToolContext,
    ToolMetadata,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    build_tool_registry,
)


class EchoTool(BaseTool):
    """测试用回显工具。"""

    SPEC = ToolSpec(
        metadata=ToolMetadata(name="echo", display_name="Echo", category="test"),
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    def run(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        return ToolResult.success(args["text"])


def test_register_get_list() -> None:
    registry = ToolRegistry()
    tool = EchoTool()
    registry.register("echo", tool)
    assert registry.get("echo") is tool
    assert registry.names() == ["echo"]
    assert registry.list() == [tool]
    assert "echo" in registry
    assert len(registry) == 1


def test_override_on_duplicate() -> None:
    registry = ToolRegistry()
    first, second = EchoTool(), EchoTool()
    registry.register("echo", first)
    registry.register("echo", second)
    assert registry.get("echo") is second


def test_duplicate_without_override_raises() -> None:
    registry = ToolRegistry()
    registry.register("echo", EchoTool())
    with pytest.raises(DomainError):
        registry.register("echo", EchoTool(), override=False)


def test_unregister_is_idempotent() -> None:
    registry = ToolRegistry()
    registry.register("echo", EchoTool())
    registry.unregister("echo")
    registry.unregister("echo")
    assert len(registry) == 0


def test_get_missing_raises() -> None:
    with pytest.raises(DomainError):
        ToolRegistry().get("missing")


def test_builtin_registry_has_five_tools() -> None:
    registry = build_tool_registry(None)
    assert registry.names() == sorted(["filesystem", "shell", "git", "http", "python"])
    assert len(BUILTIN_TOOL_CLASSES) == 5


def test_input_schema_validation() -> None:
    tool = EchoTool()
    assert tool.execute({"text": "hi"}, ToolContext()).output == "hi"
    with pytest.raises(ValidationError):
        tool.execute({}, ToolContext())  # 缺必填
    with pytest.raises(ValidationError):
        tool.execute({"text": 123}, ToolContext())  # 类型不符
    with pytest.raises(ValidationError):
        tool.execute({"text": "hi", "extra": 1}, ToolContext())  # 未声明字段
