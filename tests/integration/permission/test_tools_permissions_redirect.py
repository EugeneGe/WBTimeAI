"""``/tools/permissions`` 写路径重指向 ``resource_permission`` 回归（W3 / T2-13 补丁 · 裁定 §20）。

**端到端自证**（非仅接口 200）：经真实 ``POST /tools/permissions`` 授予 ``ALLOW`` 后——

1. ``resource_permission`` 出现对应**实例级**行（``subject_type="agent"`` /
   ``resource_type="TOOL"`` / ``resource_id=tool_id`` / ``effect="ALLOW"``）；
2. ``tool_permission``（deprecated 默认策略模板）**无新增**行（不再被运行期路由写入）；
3. 运行期**唯一**判定链 ``astra_security.ResourcePermissionChecker`` 命中该行 → 非默认拒绝。

对齐 ``tests/integration/test_run_permission_wiring.py`` 的「真实 API 授权 → 运行期放行」链路。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astra_database import SqlResourcePermissionRepository, SqlToolPermissionRepository
from astra_domain import ToolEffect
from astra_security import ResourcePermissionChecker

from tests.e2e.fixtures.wiring import seed_builtin_tool

TOOL_NAME = "shell"


@dataclass
class _Ctx:
    """运行期判定上下文替身（仅暴露判定链所需字段）。"""

    tenant_id: str
    agent_id: str | None
    permission_scope: Any = None


def _session_factory(client: Any) -> Any:
    """取与 API 共享同一 SQLite 的会话工厂。"""
    return client.app.state.services.providers.database.session_factory


def _create_agent(client: Any, headers: dict[str, str]) -> str:
    """创建 Agent，返回 id。"""
    response = client.post("/api/v1/agents", headers=headers, json={"name": "Redirect Agent"})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def test_grant_redirects_write_to_resource_permission(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """授予 ``ALLOW`` → 落 ``resource_permission``（实例级），``tool_permission`` 无新增。"""
    factory = _session_factory(client)
    agent_id = _create_agent(client, auth_headers)
    tool_id = seed_builtin_tool(client.app.state.services, name=TOOL_NAME)

    tool_permissions_before = {
        p.id for p in SqlToolPermissionRepository(factory).list_by_agent(agent_id)
    }

    granted = client.post(
        "/api/v1/tools/permissions",
        headers=auth_headers,
        json={"tool_id": tool_id, "action": "EXECUTE", "effect": "ALLOW", "agent_id": agent_id},
    )
    assert granted.status_code == 201, granted.text
    body = granted.json()["data"]
    permission_id = body["id"]
    tenant_id = body["tenant_id"]

    # ① 落 resource_permission（实例级 ALLOW）。
    rules = SqlResourcePermissionRepository(factory).list_for_subject(tenant_id, "agent", agent_id)
    matched = [
        rule
        for rule in rules
        if rule.resource_type == "TOOL"
        and rule.resource_id == tool_id
        and rule.action == "EXECUTE"
        and rule.effect == "ALLOW"
    ]
    assert len(matched) == 1, [r.resource_id for r in rules]
    assert matched[0].id == permission_id

    # ② deprecated ``tool_permission`` 无新增（不再被运行期路由写入）。
    tool_permissions_after = {
        p.id for p in SqlToolPermissionRepository(factory).list_by_agent(agent_id)
    }
    assert tool_permissions_after == tool_permissions_before

    # ③ 运行期唯一判定链命中 → 非默认拒绝（真实装配的注册表工具已被归一 tool_id）。
    checker = ResourcePermissionChecker(repository=SqlResourcePermissionRepository(factory))
    runtime_tool = client.app.state.services.tool.get(TOOL_NAME)
    assert (
        checker.check(_Ctx(tenant_id=tenant_id, agent_id=agent_id), runtime_tool, "EXECUTE")
        is ToolEffect.ALLOW
    )

    # ④ list / revoke 亦经 resource_permission（同源）。
    listed = client.get(
        "/api/v1/tools/permissions", headers=auth_headers, params={"agent_id": agent_id}
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == permission_id for item in listed.json()["data"])

    revoked = client.delete(f"/api/v1/tools/permissions/{permission_id}", headers=auth_headers)
    assert revoked.status_code == 204, revoked.text
    assert SqlResourcePermissionRepository(factory).get(permission_id) is None


def test_grant_response_contract_unchanged(client: Any, auth_headers: dict[str, str]) -> None:
    """响应壳字段（id/tenant_id/agent_id/tool_id/action/effect/scope）契约不变。"""
    agent_id = _create_agent(client, auth_headers)
    tool_id = seed_builtin_tool(client.app.state.services, name=TOOL_NAME)

    granted = client.post(
        "/api/v1/tools/permissions",
        headers=auth_headers,
        json={
            "tool_id": tool_id,
            "action": "EXECUTE",
            "effect": "ALLOW",
            "scope": {"paths": ["/tmp"]},
            "agent_id": agent_id,
            "agent_version_id": "ignored-version",
        },
    )
    assert granted.status_code == 201, granted.text
    data = granted.json()["data"]
    assert data["tool_id"] == tool_id
    assert data["agent_id"] == agent_id
    assert data["action"] == "EXECUTE"
    assert data["effect"] == "ALLOW"
    assert data["scope"] == {"paths": ["/tmp"]}
    # ``agent_version_id`` 无对应列，按裁定 §20.2 恒回填 ``None``（与 0010 回填口径一致）。
    assert data["agent_version_id"] is None
