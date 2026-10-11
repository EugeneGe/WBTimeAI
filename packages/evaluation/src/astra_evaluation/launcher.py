"""``AgentRunLauncher`` —— 创建 / 等待 / 取消逐例 ``agent_run`` 的**注入端口**（W9 裁定 R1）。

🔴 **端口在包内，真实 bridge 由组合根装配**：``astra_evaluation`` **不 import**
   ``astra_runtime`` / ``astra_agent``——逐例 ``agent_run`` 创建复用正式 Runtime / 权限 / Sandbox，
   由组合根以 :class:`AgentRunLauncher` 的**真实实现**注入（仿 ``_MarketplaceResourceImporter``
   范式）。从而能力包保持松耦合、可注入 fake 单测。

流程：``launch(...) -> RunHandle(run_id)`` 创建 Run；``await_result(handle) -> RunOutcome``
等待终态并取回输出 / 用量 / 工具调用快照；``cancel(run_id)`` 按 A-9 取消（传播到 runtime
取消路径）。

🔴 ``tool_error_count`` 口径（冻结 §5.3）：**只统计** ``tool_call.status=FAILED``；
   权限拒绝从 ``tool_call.status=DENIED`` **单独**读取（见 :func:`count_tool_errors` /
   :func:`count_tool_denials`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "TOOL_CALL_STATUS_FAILED",
    "TOOL_CALL_STATUS_DENIED",
    "RunHandle",
    "ToolCallView",
    "RunOutcome",
    "AgentRunLauncher",
    "count_tool_errors",
    "count_tool_denials",
]

#: 工具调用失败态（计入 ``tool_error_count``）。
TOOL_CALL_STATUS_FAILED = "FAILED"

#: 工具调用权限拒绝态（**不计入** ``tool_error_count``，单独读取）。
TOOL_CALL_STATUS_DENIED = "DENIED"


@dataclass(frozen=True)
class RunHandle:
    """逐例 ``agent_run`` 句柄（``launch`` 产物）。

    Attributes:
        run_id: 新建 ``agent_run`` 标识。
    """

    run_id: str


@dataclass(frozen=True)
class ToolCallView:
    """工具调用快照（供 ``tool_call_sequence`` 评分与 ``tool_error_count`` 口径）。

    Attributes:
        name: 工具名。
        status: 工具调用状态（``SUCCESS`` / ``FAILED`` / ``DENIED`` / ...）。
    """

    name: str
    status: str


@dataclass
class RunOutcome:
    """逐例 ``agent_run`` 终态快照（``await_result`` 产物）。

    Attributes:
        run_id: Run 标识。
        status: 终态（``SUCCESS | FAILED | CANCELLED``）。
        output: 最终输出文本（可空；``agent_run`` 无输出时为 ``None``）。
        error_type: 稳定 ``ErrorCode``（取消统一 ``CANCELLED``；可空）。
        duration_ms: 耗时（毫秒，可空）。
        token_usage: token 用量（JSON，可空）。
        cost: 成本（可空）。
        tool_calls: 工具调用序列（按发生顺序）。
    """

    run_id: str
    status: str
    output: str | None = None
    error_type: str | None = None
    duration_ms: int | None = None
    token_usage: dict[str, Any] | None = None
    cost: float | None = None
    tool_calls: list[ToolCallView] = field(default_factory=list)


@runtime_checkable
class AgentRunLauncher(Protocol):
    """逐例 ``agent_run`` 创建 / 等待 / 取消端口（组合根注入；**不 import runtime/agent**）。"""

    def launch(
        self,
        *,
        tenant_id: str,
        organization_id: str | None,
        workspace_id: str | None,
        agent_id: str,
        agent_version_id: str,
        input: Any,
        user_id: str | None = None,
    ) -> RunHandle:
        """创建一条 ``agent_run`` 并返回句柄（**固定** ``agent_version_id``；复用正式 Runtime）。"""
        ...

    def await_result(self, handle: RunHandle) -> RunOutcome:
        """等待 ``handle`` 对应 Run 到终态，返回结果快照。"""
        ...

    def cancel(self, run_id: str) -> None:
        """按 A-9 取消一个已启动的 Run（传播到 runtime 取消路径）。"""
        ...


def count_tool_errors(tool_calls: list[ToolCallView]) -> int:
    """``tool_error_count`` 口径（**冻结** §5.3）：**只**统计 ``status=FAILED`` 的次数。"""
    return sum(1 for call in tool_calls if call.status == TOOL_CALL_STATUS_FAILED)


def count_tool_denials(tool_calls: list[ToolCallView]) -> int:
    """权限拒绝计数（``status=DENIED``，**单独**读取，**不计入** ``tool_error_count``）。"""
    return sum(1 for call in tool_calls if call.status == TOOL_CALL_STATUS_DENIED)
