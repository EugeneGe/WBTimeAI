"""``ToolContext``（工具执行上下文，设计 §2.5.1）。

承载执行一次工具所需的租户 / 工作区 / Run 归属、**注入**的 ``SandboxProvider`` 句柄
（**非**由 Tool 自身创建，见 T1-15 实施要点）与权限 scope。

🔴 ``ToolContext.sandbox`` 为**注入**句柄：Tool **不创建** Sandbox。为避免 ``astra_tool``
   对 ``astra_sandbox`` 形成硬依赖，此处仅以 ``TYPE_CHECKING`` 引入类型（运行期鸭子类型）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from astra_domain import PermissionScope
from astra_domain.ports.egress import EgressPolicy

from .errors import sandbox_required

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期
    from astra_sandbox import SandboxProvider, SandboxSession

__all__ = ["ToolContext"]


@dataclass
class ToolContext:
    """工具执行上下文。

    Attributes:
        tenant_id: 所属租户标识。
        workspace_id: 归属工作区标识（可空）。
        run_id: 关联 Run 标识（可空）。
        workspace_root: 工作区根目录（filesystem 路径限定基准；可空）。
        agent_id: 调用方 Agent 标识（可空）。
        sandbox: **注入**的 ``SandboxProvider`` 句柄（可空）。
        sandbox_session: **注入**的 ``SandboxSession`` 句柄（可空；缺省时按需创建）。
        permission_scope: 该 Agent 对本工具的权限 scope（可空）。
        egress_policy: **注入**的出网策略（``astra_domain.ports.egress.EgressPolicy``；可空）。
            缺省时 HTTP Tool 退回**默认拒绝全部**语义（Phase 1 冻结，W1 / T2-03）。
        extra: 附加上下文。
    """

    tenant_id: str = ""
    workspace_id: str | None = None
    run_id: str | None = None
    workspace_root: str | None = None
    agent_id: str | None = None
    sandbox: SandboxProvider | None = None
    sandbox_session: SandboxSession | None = None
    permission_scope: PermissionScope | None = None
    egress_policy: EgressPolicy | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def require_sandbox(self) -> SandboxProvider:
        """返回注入的 SandboxProvider 句柄。

        Raises:
            DomainError: 未注入沙箱（``CONFIGURATION_ERROR``）。
        """
        if self.sandbox is None:
            raise sandbox_required("该工具须经 SandboxProvider 执行，但上下文未注入沙箱")
        return self.sandbox

    def ensure_session(self) -> SandboxSession:
        """返回已注入的沙箱会话；缺省时**按需创建**（不销毁，生命周期归 Runtime）。"""
        sandbox = self.require_sandbox()
        if self.sandbox_session is None:
            self.sandbox_session = sandbox.create_session(
                workspace_id=self.workspace_id,
                run_id=self.run_id,
                tenant_id=self.tenant_id or None,
                workdir=self.workspace_root,
            )
        return self.sandbox_session

    def workspace_path(self) -> Path:
        """返回工作区根目录（``Path``）。

        Raises:
            DomainError: 未配置 ``workspace_root``（``CONFIGURATION_ERROR``）。
        """
        if not self.workspace_root:
            from .errors import configuration_error

            raise configuration_error("未配置 workspace_root，无法限定 Workspace 路径")
        return Path(self.workspace_root).expanduser().resolve()
