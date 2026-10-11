"""Tool 统一接口（设计 §2.5.1）。

- :class:`ToolMetadata`：``name`` / ``display_name`` / ``description`` / ``category``；
- :class:`ToolPermissionRequirement`：默认权限要求（资源 ``TOOL`` × 动作 × scope）；
- :class:`ToolSpec`：工具静态描述（metadata + I/O JSON Schema + 默认权限 + requires_sandbox）；
- :class:`ToolResult`：执行结果；
- :class:`Tool`：工具 Protocol（``spec`` + ``execute``）；
- :class:`BaseTool`：模板方法基类（执行前校验入参）。

🔴 ``astra_tool`` 属**抽象包**：零 ORM、零框架依赖（不 import ``fastapi`` / ``sqlalchemy`` /
   ``alembic`` / ``astra_database``）。Shell / Python / Git 类工具**必过 Sandbox**，本包内
   禁止 subprocess / os.system / docker.from_env（由 test_sandbox_scan.py 兜底）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable

from astra_domain import TOOL_ACTION_READ, TOOL_TYPE_BUILTIN

from .schema import validate_input, validate_output

__all__ = [
    "TOOL_RESOURCE",
    "ToolMetadata",
    "ToolPermissionRequirement",
    "ToolSpec",
    "ToolResult",
    "Tool",
    "BaseTool",
]

#: 权限资源抽象（《需求设计》§34：资源 × 动作）。
TOOL_RESOURCE = "TOOL"


@dataclass(frozen=True)
class ToolMetadata:
    """工具元信息（设计 §2.5.1 ``metadata``）。

    Attributes:
        name: 工具名（唯一，如 ``filesystem``）。
        display_name: 展示名。
        description: 描述。
        category: 分类（如 ``system`` / ``vcs`` / ``network``）。
    """

    name: str
    display_name: str = ""
    description: str = ""
    category: str = ""


@dataclass(frozen=True)
class ToolPermissionRequirement:
    """默认权限要求（资源 ``TOOL`` × 动作 × scope）。

    Attributes:
        resource: 资源抽象（Phase 1 恒为 ``TOOL``）。
        action: 动作（``ToolAction`` 字面值：``EXECUTE`` / ``READ`` / ``WRITE``）。
        scope: 附加 scope 约束（JSON 结构）。
    """

    resource: str = TOOL_RESOURCE
    action: str = TOOL_ACTION_READ
    scope: Mapping[str, Any] = field(default_factory=dict)

    def permission_code(self, tool_name: str) -> str:
        """返回权限码 ``tool:<name>.<action>``（设计 §2.5.3）。"""
        return f"tool:{tool_name}.{self.action.lower()}"


@dataclass
class ToolSpec:
    """工具静态描述（设计 §2.5.1）。

    Attributes:
        metadata: 元信息。
        input_schema: 入参 JSON Schema（执行前校验）。
        output_schema: 出参 JSON Schema（可选校验，空 = 不校验）。
        permission: 默认权限要求。
        requires_sandbox: 是否须经 ``SandboxProvider`` 执行。
        tool_type: 工具类型（Phase 1 恒为 ``builtin``）。
    """

    metadata: ToolMetadata
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    permission: ToolPermissionRequirement = field(default_factory=ToolPermissionRequirement)
    requires_sandbox: bool = False
    tool_type: str = TOOL_TYPE_BUILTIN

    @property
    def name(self) -> str:
        """工具名（``metadata.name`` 便捷访问）。"""
        return self.metadata.name


@dataclass
class ToolResult:
    """工具执行结果。

    Attributes:
        ok: 是否成功。
        output: 结构化输出（成功时）。
        error: 错误信息（失败时）。
        error_code: 错误码（``ErrorCode`` 字面值，失败时）。
        duration_ms: 执行耗时（毫秒）。
        metadata: 附加元数据（如 ``sandbox_session_id``）。
    """

    ok: bool = True
    output: Any = None
    error: str | None = None
    error_code: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, output: Any = None, /, **metadata: Any) -> ToolResult:
        """构造成功结果。"""
        return cls(ok=True, output=output, metadata=dict(metadata))

    @classmethod
    def failure(cls, error: str, /, *, code: str | None = None, **metadata: Any) -> ToolResult:
        """构造失败结果。"""
        return cls(ok=False, error=error, error_code=code, metadata=dict(metadata))


@runtime_checkable
class Tool(Protocol):
    """工具统一接口（设计 §2.5.1）。

    Phase 2 的 MCP Tool / Connector 以**同一接口**注册（设计 §2.5.1 预留）。
    """

    @property
    def spec(self) -> ToolSpec:
        """工具静态描述。"""
        ...

    def execute(self, args: Mapping[str, Any], ctx: Any) -> ToolResult:
        """执行工具。

        Args:
            args: 入参（须通过 ``spec.input_schema`` 校验）。
            ctx: 执行上下文（:class:`astra_tool.context.ToolContext`）。

        Returns:
            :class:`ToolResult`。
        """
        ...


class BaseTool(ABC):
    """工具模板方法基类：执行前校验入参、执行后可选校验出参。

    子类须声明类属性 :attr:`SPEC` 并实现 :meth:`run`。
    """

    #: 子类覆盖：工具静态描述。
    SPEC: ClassVar[ToolSpec]

    @property
    def spec(self) -> ToolSpec:
        """工具静态描述。"""
        return self.SPEC

    def execute(self, args: Mapping[str, Any], ctx: Any) -> ToolResult:
        """校验入参 → 执行 :meth:`run` → 可选校验出参。"""
        payload = dict(args)
        validate_input(self.SPEC.input_schema, payload, name=self.SPEC.name)
        result = self.run(payload, ctx)
        if result.ok and self.SPEC.output_schema:
            validate_output(self.SPEC.output_schema, result.output, name=self.SPEC.name)
        return result

    @abstractmethod
    def run(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        """执行具体逻辑（入参已通过 Schema 校验）。"""
        raise NotImplementedError
