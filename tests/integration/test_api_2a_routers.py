"""2a API 骨架集成测试（W3 / T2-17；设计 §2.12；验收 ``I-P2-22`` / ``I-P2-16`` 部分）。

覆盖：

- ``/skills`` CRUD + 版本 + 发布；
- ``/mcp/servers`` 注册 / 列表 / 详情 / 删除 + ``/discover`` **落 ``mcp_tool``** + ``/tools`` +
  ``/permissions``；
- ``/plugins`` 已装 / 安装 / 卸载；
- ``/audit`` 基础消费（统一响应壳）；
- 响应遵循统一响应壳（``{data, request_id}``）。
"""

from __future__ import annotations

from typing import Any


def _data(response: Any) -> Any:
    """从统一响应壳取 ``data``。"""
    assert "data" in response.json(), response.text
    return response.json()["data"]


# -- /skills ----------------------------------------------------------------


def test_skills_crud_and_publish(client: Any, auth_headers: dict[str, str]) -> None:
    """Skill 创建 / 列表 / 详情 / 更新 / 版本 / 发布。"""
    created = client.post(
        "/api/v1/skills",
        headers=auth_headers,
        json={"name": "code-review", "description": "review skill"},
    )
    assert created.status_code == 201, created.text
    skill = _data(created)
    assert skill["name"] == "code-review"
    assert skill["status"] == "DRAFT"
    skill_id = skill["id"]

    listed = client.get("/api/v1/skills", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == skill_id for item in _data(listed))

    detail = client.get(f"/api/v1/skills/{skill_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert _data(detail)["name"] == "code-review"

    updated = client.put(
        f"/api/v1/skills/{skill_id}",
        headers=auth_headers,
        json={"display_name": "Code Review", "category": "quality"},
    )
    assert updated.status_code == 200
    assert _data(updated)["display_name"] == "Code Review"
    assert _data(updated)["category"] == "quality"

    version = client.post(
        f"/api/v1/skills/{skill_id}/versions",
        headers=auth_headers,
        json={"version": "1.0.0", "instructions": "do review"},
    )
    assert version.status_code == 201, version.text
    assert _data(version)["status"] == "DRAFT"

    versions = client.get(f"/api/v1/skills/{skill_id}/versions", headers=auth_headers)
    assert versions.status_code == 200
    assert len(_data(versions)) == 1

    published = client.post(f"/api/v1/skills/{skill_id}/publish", headers=auth_headers)
    assert published.status_code == 200, published.text
    assert _data(published)["status"] == "PUBLISHED"


def test_skill_cross_tenant_returns_404(
    client: Any, auth_headers: dict[str, str], other_tenant_headers: dict[str, str]
) -> None:
    """跨租户访问 Skill → 404（隔离不变量 I-1）。"""
    created = client.post("/api/v1/skills", headers=auth_headers, json={"name": "private-skill"})
    skill_id = _data(created)["id"]

    forbidden = client.get(f"/api/v1/skills/{skill_id}", headers=other_tenant_headers)
    assert forbidden.status_code == 404, forbidden.text


# -- /mcp -------------------------------------------------------------------


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
        return [_FakeToolSpec("echo"), _FakeToolSpec("sum")]


def test_mcp_server_lifecycle_and_discover(client: Any, auth_headers: dict[str, str]) -> None:
    """MCP Server 注册 / 列表 / 详情 / 发现（落 mcp_tool）/ 工具目录 / 删除。"""
    created = client.post(
        "/api/v1/mcp/servers",
        headers=auth_headers,
        json={"name": "local-fs", "transport": "stdio", "command": "mcp-fs"},
    )
    assert created.status_code == 201, created.text
    server = _data(created)
    assert server["name"] == "local-fs"
    assert "endpoint" in server
    server_id = server["id"]

    listed = client.get("/api/v1/mcp/servers", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == server_id for item in _data(listed))

    # 发现：覆写组合根的 client 工厂为伪客户端（避免真实建连）。
    client.app.state.services.mcp_client_factory = lambda _server: _FakeMCPClient()
    discovered = client.post(f"/api/v1/mcp/servers/{server_id}/discover", headers=auth_headers)
    assert discovered.status_code == 200, discovered.text
    tools = _data(discovered)
    assert {tool["name"] for tool in tools} == {"echo", "sum"}
    assert all(tool["mcp_server_id"] == server_id for tool in tools)

    # 工具目录：落库可见。
    catalog = client.get("/api/v1/mcp/tools", headers=auth_headers, params={"server_id": server_id})
    assert catalog.status_code == 200
    assert {tool["name"] for tool in _data(catalog)} == {"echo", "sum"}

    # 删除。
    deleted = client.delete(f"/api/v1/mcp/servers/{server_id}", headers=auth_headers)
    assert deleted.status_code == 204


def test_mcp_permissions_roundtrip(client: Any, auth_headers: dict[str, str]) -> None:
    """MCP 授权新增 / 列表。"""
    created = client.post(
        "/api/v1/mcp/permissions",
        headers=auth_headers,
        json={"mcp_tool_id": "mcp-tool-1", "action": "EXECUTE", "effect": "ALLOW"},
    )
    assert created.status_code == 201, created.text
    assert _data(created)["effect"] == "ALLOW"

    listed = client.get(
        "/api/v1/mcp/permissions", headers=auth_headers, params={"mcp_tool_id": "mcp-tool-1"}
    )
    assert listed.status_code == 200
    assert len(_data(listed)) == 1


# -- /plugins ---------------------------------------------------------------


def test_plugins_install_list_uninstall(client: Any, auth_headers: dict[str, str]) -> None:
    """插件安装 / 列表 / 卸载。"""
    installed = client.post(
        "/api/v1/plugins",
        headers=auth_headers,
        json={"name": "demo-plugin", "version": "0.1.0", "kind": "tool"},
    )
    assert installed.status_code == 201, installed.text
    plugin = _data(installed)
    assert plugin["name"] == "demo-plugin"
    assert plugin["status"] == "installed"

    listed = client.get("/api/v1/plugins", headers=auth_headers)
    assert listed.status_code == 200
    assert any(item["id"] == plugin["id"] for item in _data(listed))

    deleted = client.delete(f"/api/v1/plugins/{plugin['id']}", headers=auth_headers)
    assert deleted.status_code == 204


# -- /audit -----------------------------------------------------------------


def test_audit_list_returns_shell(client: Any, auth_headers: dict[str, str]) -> None:
    """``GET /audit`` 返回统一响应壳（列表，可为空）。"""
    response = client.get("/api/v1/audit", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert isinstance(_data(response), list)
