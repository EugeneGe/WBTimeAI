"""Agent 组值对象（设计 §2.4 / §2.7.1 / §2.7.2）。

纯标准库实现（零框架依赖，C-03）：

- :class:`AgentType` / :class:`AgentStatus` / :class:`AgentVersionStatus`：字符串枚举；
- :class:`ModelConfig`：``agent_version.model_config`` 的结构化承载；
- :class:`RuntimeConfig`：``agent_version.runtime_config`` 的结构化承载，
  含 ``context`` / ``execution`` / ``concurrency`` 段（§2.7.1 / §2.7.2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from astra_core import ValidationError

from ..constants import (
    AGENT_STATUS_ACTIVE,
    AGENT_STATUS_ARCHIVED,
    AGENT_STATUS_DRAFT,
    AGENT_TYPE_EVENT_AGENT,
    AGENT_TYPE_PRIMARY,
    AGENT_TYPE_SCHEDULED_AGENT,
    AGENT_TYPE_SUB_AGENT,
    AGENT_TYPE_WORKFLOW_AGENT,
    AGENT_VERSION_STATUS_DEPRECATED,
    AGENT_VERSION_STATUS_DRAFT,
    AGENT_VERSION_STATUS_PUBLISHED,
    DEFAULT_ALLOW_STREAM,
    DEFAULT_MAX_INPUT_TOKENS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_PARALLEL,
    DEFAULT_MAX_PARALLEL_TOOLS,
    DEFAULT_MAX_RETRY,
    DEFAULT_MAX_RUNS_PER_CONVERSATION,
    DEFAULT_MODEL_TIMEOUT_MS,
    DEFAULT_OVERFLOW_STRATEGY,
    DEFAULT_RESERVE_OUTPUT_TOKENS,
    DEFAULT_RETRY_ON,
    DEFAULT_RUN_TIMEOUT_MS,
    DEFAULT_TOOL_CHOICE,
    DEFAULT_TOOL_OUTPUT_MAX_CHARS,
    DEFAULT_TOOL_TIMEOUT_MS,
)

__all__ = [
    "AgentType",
    "AgentStatus",
    "AgentVersionStatus",
    "ModelConfig",
    "ContextConfig",
    "ExecutionPolicy",
    "ConcurrencyConfig",
    "PromptMergeConfig",
    "RuntimeConfig",
]

#: 默认 Skill 指令合成顺序（``after`` = Skill 追加于 Agent 之后）。
DEFAULT_SKILL_ORDER = "after"
#: 默认 Skill 指令分隔符。
DEFAULT_SKILL_SEPARATOR = "\n\n"
#: 默认冲突策略（Phase 3 预留；本阶段仅占位不生效）。
DEFAULT_PROMPT_ON_CONFLICT = "agent_wins"


def _ensure_value(enum_cls: type[StrEnum], value: Any, *, field_name: str) -> Any:
    """校验并归一化字符串枚举取值。"""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise ValidationError(
            f"{field_name} 取值非法",
            data={"field": field_name, "value": str(value)},
        ) from exc


class AgentType(StrEnum):
    """Agent 类型（设计 §2.4；Phase 1 主用 ``PRIMARY``，其余留位）。"""

    PRIMARY = AGENT_TYPE_PRIMARY
    SUB_AGENT = AGENT_TYPE_SUB_AGENT
    WORKFLOW_AGENT = AGENT_TYPE_WORKFLOW_AGENT
    SCHEDULED_AGENT = AGENT_TYPE_SCHEDULED_AGENT
    EVENT_AGENT = AGENT_TYPE_EVENT_AGENT

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | AgentType) -> AgentType:
        """校验并归一化 Agent 类型。"""
        return _ensure_value(cls, value, field_name="agent_type")


class AgentStatus(StrEnum):
    """Agent 生命周期状态（设计 §2.4）。"""

    DRAFT = AGENT_STATUS_DRAFT
    ACTIVE = AGENT_STATUS_ACTIVE
    ARCHIVED = AGENT_STATUS_ARCHIVED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | AgentStatus) -> AgentStatus:
        """校验并归一化 Agent 状态。"""
        return _ensure_value(cls, value, field_name="agent_status")


class AgentVersionStatus(StrEnum):
    """AgentVersion 状态（设计 §2.4）。"""

    DRAFT = AGENT_VERSION_STATUS_DRAFT
    PUBLISHED = AGENT_VERSION_STATUS_PUBLISHED
    DEPRECATED = AGENT_VERSION_STATUS_DEPRECATED

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """返回全部合法字面值。"""
        return tuple(member.value for member in cls)

    @classmethod
    def ensure(cls, value: str | AgentVersionStatus) -> AgentVersionStatus:
        """校验并归一化 AgentVersion 状态。"""
        return _ensure_value(cls, value, field_name="agent_version_status")


@dataclass
class ModelConfig:
    """``agent_version.model_config`` 的结构化承载（设计 §2.4）。

    Attributes:
        provider: 提供方标识（如 ``openai``）。
        model: 模型名（如 ``gpt-4o``）。
        temperature: 采样温度（``0.0`` ~ ``2.0``）。
        max_tokens: 最大输出 token（可空）。
        params: 其它提供方参数（原样透传）。
    """

    provider: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValidationError(
                "model_config.provider 不能为空",
                data={"field": "provider"},
            )
        if not self.model:
            raise ValidationError(
                "model_config.model 不能为空",
                data={"field": "model"},
            )
        if not 0.0 <= float(self.temperature) <= 2.0:
            raise ValidationError(
                "model_config.temperature 需在 0.0 ~ 2.0 之间",
                data={"field": "temperature", "value": self.temperature},
            )
        if self.max_tokens is not None and int(self.max_tokens) <= 0:
            raise ValidationError(
                "model_config.max_tokens 需为正整数",
                data={"field": "max_tokens", "value": self.max_tokens},
            )

    def to_dict(self) -> dict[str, Any]:
        """序列化为可落 JSON 列的字典。"""
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelConfig:
        """由字典构造（缺省字段取默认值）。"""
        return cls(
            provider=str(data.get("provider", "")),
            model=str(data.get("model", "")),
            temperature=float(data.get("temperature", 0.7)),
            max_tokens=data.get("max_tokens"),
            params=dict(data.get("params") or {}),
        )


@dataclass
class ContextConfig:
    """上下文窗口配置段（设计 §2.7.1，修订 R-08）。"""

    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS
    reserve_output_tokens: int = DEFAULT_RESERVE_OUTPUT_TOKENS
    overflow_strategy: str = DEFAULT_OVERFLOW_STRATEGY
    tool_output_max_chars: int = DEFAULT_TOOL_OUTPUT_MAX_CHARS

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "max_input_tokens": self.max_input_tokens,
            "reserve_output_tokens": self.reserve_output_tokens,
            "overflow_strategy": self.overflow_strategy,
            "tool_output_max_chars": self.tool_output_max_chars,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextConfig:
        """由字典构造。"""
        return cls(
            max_input_tokens=int(data.get("max_input_tokens", DEFAULT_MAX_INPUT_TOKENS)),
            reserve_output_tokens=int(
                data.get("reserve_output_tokens", DEFAULT_RESERVE_OUTPUT_TOKENS)
            ),
            overflow_strategy=str(data.get("overflow_strategy", DEFAULT_OVERFLOW_STRATEGY)),
            tool_output_max_chars=int(
                data.get("tool_output_max_chars", DEFAULT_TOOL_OUTPUT_MAX_CHARS)
            ),
        )


@dataclass
class ExecutionPolicy:
    """执行策略段（超时 / 重试 / 退避；设计 §2.7.2，修订 R-09）。"""

    model_timeout_ms: int = DEFAULT_MODEL_TIMEOUT_MS
    tool_timeout_ms: int = DEFAULT_TOOL_TIMEOUT_MS
    run_timeout_ms: int = DEFAULT_RUN_TIMEOUT_MS
    max_retry: int = DEFAULT_MAX_RETRY
    retry_on: tuple[str, ...] = DEFAULT_RETRY_ON
    backoff: dict[str, Any] = field(
        default_factory=lambda: {
            "strategy": "exponential",
            "base_ms": 1000,
            "max_ms": 30000,
            "jitter": True,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "model_timeout_ms": self.model_timeout_ms,
            "tool_timeout_ms": self.tool_timeout_ms,
            "run_timeout_ms": self.run_timeout_ms,
            "max_retry": self.max_retry,
            "retry_on": list(self.retry_on),
            "backoff": dict(self.backoff),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionPolicy:
        """由字典构造。"""
        backoff = data.get("backoff")
        return cls(
            model_timeout_ms=int(data.get("model_timeout_ms", DEFAULT_MODEL_TIMEOUT_MS)),
            tool_timeout_ms=int(data.get("tool_timeout_ms", DEFAULT_TOOL_TIMEOUT_MS)),
            run_timeout_ms=int(data.get("run_timeout_ms", DEFAULT_RUN_TIMEOUT_MS)),
            max_retry=int(data.get("max_retry", DEFAULT_MAX_RETRY)),
            retry_on=tuple(data.get("retry_on") or DEFAULT_RETRY_ON),
            backoff=dict(backoff) if backoff else ExecutionPolicy().backoff,
        )


@dataclass
class ConcurrencyConfig:
    """并发约束段（设计 §2.7.2，修订 R-31 部分前置）。"""

    max_parallel_tools: int = DEFAULT_MAX_PARALLEL_TOOLS
    max_runs_per_conversation: int = DEFAULT_MAX_RUNS_PER_CONVERSATION
    #: Workflow ``PARALLEL`` 分支并发上限（W4 裁定 §6.1 R5-b / §9-b）。
    #: 语义＝**Workflow 分支并发**，与 ``max_parallel_tools``（单 Run 内 tool 并发）
    #: **互不等价**，故**新增独立字段**而非复用。
    max_parallel: int = DEFAULT_MAX_PARALLEL

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "max_parallel_tools": self.max_parallel_tools,
            "max_runs_per_conversation": self.max_runs_per_conversation,
            "max_parallel": self.max_parallel,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConcurrencyConfig:
        """由字典构造（``max_parallel`` 缺省回退 ``DEFAULT_MAX_PARALLEL``，向后兼容）。"""
        return cls(
            max_parallel_tools=int(data.get("max_parallel_tools", DEFAULT_MAX_PARALLEL_TOOLS)),
            max_runs_per_conversation=int(
                data.get("max_runs_per_conversation", DEFAULT_MAX_RUNS_PER_CONVERSATION)
            ),
            max_parallel=int(data.get("max_parallel", DEFAULT_MAX_PARALLEL)),
        )


@dataclass
class PromptMergeConfig:
    """Skill 指令合成策略段（W2 裁定 R5 §5.4；数据驱动，随 ``agent_version``）。

    Attributes:
        skill_order: 合成顺序（``"after"`` = Skill 追加于 Agent ``system_prompt`` 之后；
            ``"before"`` = 前置）。默认 ``"after"``。
        skill_separator: 分段分隔符。默认 ``"\\n\\n"``。
        on_conflict: 冲突策略（``"agent_wins"`` 等；**Phase 3 预留**，本阶段仅占位不生效）。
    """

    skill_order: str = DEFAULT_SKILL_ORDER
    skill_separator: str = DEFAULT_SKILL_SEPARATOR
    on_conflict: str = DEFAULT_PROMPT_ON_CONFLICT

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "skill_order": self.skill_order,
            "skill_separator": self.skill_separator,
            "on_conflict": self.on_conflict,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptMergeConfig:
        """由字典构造（缺省字段取默认值；兼容旧 JSON）。"""
        return cls(
            skill_order=str(data.get("skill_order", DEFAULT_SKILL_ORDER)),
            skill_separator=str(data.get("skill_separator", DEFAULT_SKILL_SEPARATOR)),
            on_conflict=str(data.get("on_conflict", DEFAULT_PROMPT_ON_CONFLICT)),
        )


@dataclass
class RuntimeConfig:
    """``agent_version.runtime_config`` 的结构化承载。

    含 ``max_iterations`` / ``tool_choice`` / ``allow_stream`` / ``sandbox`` /
    ``context``（§2.7.1）/ ``execution``（§2.7.2）/ ``concurrency``（§2.7.2）/
    ``prompt``（Skill 指令合成策略，W2 裁定 R5）。
    """

    max_iterations: int = DEFAULT_MAX_ITERATIONS
    tool_choice: str = DEFAULT_TOOL_CHOICE
    allow_stream: bool = DEFAULT_ALLOW_STREAM
    sandbox: dict[str, Any] = field(default_factory=dict)
    context: ContextConfig = field(default_factory=ContextConfig)
    execution: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    prompt: PromptMergeConfig = field(default_factory=PromptMergeConfig)

    def __post_init__(self) -> None:
        if int(self.max_iterations) < 1:
            raise ValidationError(
                "runtime_config.max_iterations 需为正整数",
                data={"field": "max_iterations", "value": self.max_iterations},
            )

    def to_dict(self) -> dict[str, Any]:
        """序列化为可落 JSON 列的字典。"""
        return {
            "max_iterations": self.max_iterations,
            "tool_choice": self.tool_choice,
            "allow_stream": self.allow_stream,
            "sandbox": dict(self.sandbox),
            "context": self.context.to_dict(),
            "execution": self.execution.to_dict(),
            "concurrency": self.concurrency.to_dict(),
            "prompt": self.prompt.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeConfig:
        """由字典构造（缺省段取默认值；旧 JSON 无 ``prompt`` 段时向后兼容）。"""
        return cls(
            max_iterations=int(data.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
            tool_choice=str(data.get("tool_choice", DEFAULT_TOOL_CHOICE)),
            allow_stream=bool(data.get("allow_stream", DEFAULT_ALLOW_STREAM)),
            sandbox=dict(data.get("sandbox") or {}),
            context=ContextConfig.from_dict(data.get("context") or {}),
            execution=ExecutionPolicy.from_dict(data.get("execution") or {}),
            concurrency=ConcurrencyConfig.from_dict(data.get("concurrency") or {}),
            prompt=PromptMergeConfig.from_dict(data.get("prompt") or {}),
        )
