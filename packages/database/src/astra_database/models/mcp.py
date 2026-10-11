"""MCP 组 ORM 表（设计 §2.4 / §2.15.1；W2 / T2-10）。

- :class:`McpServer`：MCP Server 配置（``transport`` / ``endpoint`` / ``command`` /
  ``env_ref`` / ``credential_id``；唯一键 ``(tenant_id, name)``）；
- :class:`McpTool`：**发现目录**（``tools/list`` 结果落此表；唯一键
  ``(mcp_server_id, name)``）——与 ``tool`` 表（**执行注册表**）语义区分（R-22 / R9）;
- :class:`McpPermission`：MCP Tool **默认策略模板**（W2 不作运行期判定源，R9 §9.3）。

🔴 本模块落在 ``astra_database``（ORM 允许位置）；域实体在 ``astra_mcp.domain``。
🔴 凭证**仅存引用**（``credential_id`` 复用 Phase 0 ``credential`` 表），明文不落库（C-07）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from astra_common.time import utcnow
from astra_core import generate_id
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin
from ..types import GUID, JSONType

__all__ = ["McpServer", "McpTool", "McpPermission"]


class McpServer(Base, TimestampMixin):
    """MCPServer：MCP Server 配置（设计 §2.4）。"""

    __tablename__ = "mcp_server"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_mcp_server_tenant_name"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    # 组织归属（Phase 2 · W7 / T2-40 · 迁移 0016 加列 + 回填；A-7）。
    organization_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("organization.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("workspace.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    transport: Mapped[str] = mapped_column(String(20), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    command: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    args: Mapped[list[Any] | None] = mapped_column(JSONType(), nullable=True)
    env_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    credential_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("credential.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)


class McpTool(Base):
    """MCPTool：MCP Server 的**发现目录**（``tools/list`` 结果；设计 §2.4）。"""

    __tablename__ = "mcp_tool"
    __table_args__ = (UniqueConstraint("mcp_server_id", "name", name="uq_mcp_tool_server_name"),)

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    mcp_server_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("mcp_server.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)


class McpPermission(Base, TimestampMixin):
    """MCPPermission：MCP Tool **默认策略模板**（不作运行期判定源；设计 §2.4 / R9 §9.3）。"""

    __tablename__ = "mcp_permission"
    __table_args__ = (
        UniqueConstraint(
            "mcp_tool_id", "agent_id", "action", name="uq_mcp_permission_tool_agent_action"
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=generate_id)
    tenant_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("tenant.id"), nullable=False, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent.id"), nullable=True, index=True
    )
    agent_version_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("agent_version.id"), nullable=True, index=True
    )
    mcp_tool_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("mcp_tool.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    effect: Mapped[str] = mapped_column(String(20), nullable=False)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
