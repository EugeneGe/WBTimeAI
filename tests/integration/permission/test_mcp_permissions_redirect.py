"""``/mcp/permissions`` 重指向 ``resource_permission`` 回归（W3/T2-13 补丁 · 裁定 §21.4 X1/X2）。

**端到端自证**（非仅接口 200）——经真实 ``POST /mcp/permissions``（传 ``mcp_tool_id``）授予
``ALLOW`` 后：

1. ``resource_permission`` 出现对应**实例级**行（``subject_type="agent"`` /
   ``resource_type="TOOL"`` / ``resource_id=<对应 tool 行 id>`` / ``effect="ALLOW"``）；
2. ``mcp_permission``（deprecated 默认策略模板）**无新增**行；
3. 运行期**唯一**判定链 ``astra_security.ResourcePermissionChecker`` 命中该行 → 非默认拒绝；
   revoke 后失效（回到默认拒绝）。

并验证 ``mcp_tool_id → tool 行 id`` 映射链路：``mcp_tool.id``（请求体口径）↔ ``tool.tool_ref["id"]``
↔ ``MCPToolAdapter.tool_id``（判定链口径）。

另覆盖 ``mcp_tool_id`` **未同步进 ``tool`` 表**的 fail-closed 分支（不写 ``resource_permission``、
落 deprecated 模板 + 告警、保留 ``/mcp/*`` 往返契约）。

抽象纪律：本文件不 import 适配器实现；判定链经 ``astra_security`` 真实实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from astra_database import (
    SqlResourcePermissionRepository,
    SqlToolRepository,
)
from astra_domain import ToolEffect
from astra_mcp import (
    MCPRegistry,
    SqlMCPPermissionRepository,
    SqlMCPServerRepository,
    SqlMCPToolRepository,
)
from astra_security import ResourcePermissionChecker

MCP_TOOL_IDS = ("echo", "sum")


@dataclass
class _Ctx:
    """运行期判定上下文替身（仅暴露判定链所需字段）。"""

    tenant_id: str
    agent_id: str | None
    permission_scope: Any = None


class _FakeToolSpec:
    """伪 MCP 工具规格（供 discover 测试）。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} tool"
        self.input_schema: dict[str, Any] = {"type": "object"}
        self.output_schema: dict[str, Any] = {}


class _FakeMCPClient:
    """伪 MCP 客户端（仅实现 ``list_tools``）。"""

    def list_tools(self) -> list[_FakeToolSpec]:
        return [_FakeToolSpec(name) for name in MCP_TOOL_IDS]


class _StubInvoker:
    """最小 ``MCPToolInvoker`` 桩（本测试**不**执行 MCP 工具）。"""

    def call(self, tool_name: str, arguments: Any) -> Any:  # noqa: ANN401
        raise AssertionError("本测试不执行 MCP 工具")


def _session_factory(client: Any) -> Any:
    """取与 API 共享同一 SQLite 的会话工厂。"""
    return client.app.state.services.providers.database.session_factory


def _create_agent(client: Any, headers: dict[str, str]) -> str:
    """创建 Agent，返回 id。"""
    response = client.post("/api/v1/agents", headers=headers, json={"name": "MCP Redirect Agent"})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _seed_synced_mcp_tool(
    client: Any, headers: dict[str, str], *, name: str
) -> tuple[str, str, str]:
    """经真实 API 注册 Server + 发现，并同步进 ``tool`` 表。

    返回 ``(tenant_id, mcp_tool_id, tool_name)``：``mcp_tool_id`` 是 ``mcp_tool`` 表 id
    （``/mcp/permissions`` 请求体口径）；``tool_name`` 为执行注册表命名
    ``mcp:<server>.<tool>``（可经 ``services.tool`` 取到适配器）。
    """
    services = client.app.state.services
    factory = _session_factory(client)

    created = client.post(
        "/api/v1/mcp/servers",
        headers=headers,
        json={"name": "local-fs", "transport": "stdio", "command": "mcp-fs"},
    )
    assert created.status_code == 201, created.text
    server = created.json()["data"]
    tenant_id = server["tenant_id"]

    services.mcp_client_factory = lambda _server: _FakeMCPClient()
    discovered = client.post(f"/api/v1/mcp/servers/{server['id']}/discover", headers=headers)
    assert discovered.status_code == 200, discovered.text
    tool_rows = discovered.json()["data"]
    target = next(tool for tool in tool_rows if tool["name"] == name)
    mcp_tool_id = target["id"]

    # 同步执行注册表（``mcp_tool`` → ``tool`` 表 + 适配器）。
    server_entity = SqlMCPServerRepository(factory).get(server["id"])
    tool_entities = SqlMCPToolRepository(factory).list_by_server(server["id"])
    registered = MCPRegistry().sync_to_tool_registry(
        services.tool,
        server_entity,
        tools=tool_entities,
        invoker_factory=lambda _srv, _tool: _StubInvoker(),
        tool_repository=SqlToolRepository(factory),
    )
    tool_name = f"mcp:{server['name']}.{name}"
    assert tool_name in registered, registered
    return tenant_id, mcp_tool_id, tool_name


def test_grant_redirects_write_to_resource_permission(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """授予 ``ALLOW`` → 落 ``resource_permission``（实例级），``mcp_permission`` 无新增。"""
    services = client.app.state.services
    factory = _session_factory(client)
    agent_id = _create_agent(client, auth_headers)
    tenant_id, mcp_tool_id, tool_name = _seed_synced_mcp_tool(client, auth_headers, name="echo")

    # 映射链路证据：``mcp_tool_id`` ↔ ``tool.tool_ref["id"]`` ↔ 适配器 ``tool_id``。
    adapter = services.tool.get(tool_name)
    tool_row_id = adapter.tool_id
    tool_row = SqlToolRepository(factory).get(tool_row_id)
    assert tool_row is not None
    assert tool_row.source == "mcp"
    assert tool_row.tool_ref["kind"] == "mcp"
    assert tool_row.tool_ref["id"] == mcp_tool_id

    mcp_permissions_before = {
        p.id for p in SqlMCPPermissionRepository(factory).list_by_tool(mcp_tool_id)
    }

    granted = client.post(
        "/api/v1/mcp/permissions",
        headers=auth_headers,
        json={
            "mcp_tool_id": mcp_tool_id,
            "action": "EXECUTE",
            "effect": "ALLOW",
            "agent_id": agent_id,
        },
    )
    assert granted.status_code == 201, granted.text
    body = granted.json()["data"]
    permission_id = body["id"]
    assert body["mcp_tool_id"] == mcp_tool_id
    assert body["agent_id"] == agent_id
    assert body["action"] == "EXECUTE"
    assert body["effect"] == "ALLOW"
    # ``agent_version_id`` 无对应列，恒回填 ``None``（与 0010 回填口径一致）。
    assert body["agent_version_id"] is None

    # ① 落 resource_permission（实例级 ALLOW，resource_id = 对应 tool 行 id）。
    rules = SqlResourcePermissionRepository(factory).list_by_resource(
        tenant_id, "TOOL", tool_row_id
    )
    matched = [
        rule
        for rule in rules
        if rule.subject_type == "agent"
        and rule.subject_id == agent_id
        and rule.action == "EXECUTE"
        and rule.effect == "ALLOW"
    ]
    assert len(matched) == 1, [rule.resource_id for rule in rules]
    assert matched[0].id == permission_id

    # ② deprecated ``mcp_permission`` 无新增（不再被运行期路由写入）。
    mcp_permissions_after = {
        p.id for p in SqlMCPPermissionRepository(factory).list_by_tool(mcp_tool_id)
    }
    assert mcp_permissions_after == mcp_permissions_before

    # ③ 运行期唯一判定链命中 → 非默认拒绝（适配器 tool_id == 授权 resource_id）。
    checker = ResourcePermissionChecker(repository=SqlResourcePermissionRepository(factory))
    assert (
        checker.check(_Ctx(tenant_id=tenant_id, agent_id=agent_id), adapter, "EXECUTE")
        is ToolEffect.ALLOW
    )

    # ④ list 亦经 resource_permission（同源、同一映射口径）。
    listed = client.get(
        "/api/v1/mcp/permissions", headers=auth_headers, params={"mcp_tool_id": mcp_tool_id}
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == permission_id for item in listed.json()["data"])

    # ⑤ revoke 后失效（回默认拒绝）。
    services.mcp_permission_service.revoke(
        permission_id, tenant_id=granted.json()["data"]["tenant_id"]
    )
    assert SqlResourcePermissionRepository(factory).get(permission_id) is None
    assert (
        checker.check(_Ctx(tenant_id=tenant_id, agent_id=agent_id), adapter, "EXECUTE")
        is ToolEffect.DENY
    )


def test_unmapped_mcp_tool_is_fail_closed_and_roundtrips(
    client: Any,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``mcp_tool_id`` 未同步进 ``tool`` 表 → fail-closed（不写运行期判定源）+ 告警 + 契约往返。"""
    import logging

    # P2.7-B：显式隔离 logger——in-process ``alembic fileConfig`` 会把既有 logger 置
    # ``disabled=True``（跨用例顺序依赖污染），monkeypatch 自动还原；**不削弱断言强度**。
    _logger = logging.getLogger("astra_mcp.services")
    monkeypatch.setattr(_logger, "disabled", False)
    monkeypatch.setattr(_logger, "propagate", True)

    factory = _session_factory(client)
    agent_id = _create_agent(client, auth_headers)

    with caplog.at_level(logging.WARNING, logger="astra_mcp.services"):
        granted = client.post(
            "/api/v1/mcp/permissions",
            headers=auth_headers,
            json={
                "mcp_tool_id": "mcp-tool-unmapped",
                "action": "EXECUTE",
                "effect": "ALLOW",
                "agent_id": agent_id,
            },
        )
    assert granted.status_code == 201, granted.text
    permission_id = granted.json()["data"]["id"]

    # fail-closed：未落运行期**唯一**判定源。
    assert SqlResourcePermissionRepository(factory).get(permission_id) is None
    # 结构化告警（勿静默吞没）。
    assert "mcp.permission.unmapped_tool" in caplog.text

    # deprecated 默认策略模板：保留 ``/mcp/*`` 往返契约。
    assert len(SqlMCPPermissionRepository(factory).list_by_tool("mcp-tool-unmapped")) == 1
    listed = client.get(
        "/api/v1/mcp/permissions",
        headers=auth_headers,
        params={"mcp_tool_id": "mcp-tool-unmapped"},
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == permission_id for item in listed.json()["data"])
