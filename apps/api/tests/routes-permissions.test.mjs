/**
 * T2-07 · 权限族 4 op（§1 表 11–14）。
 *
 * 四个重点：
 *  ① `GET /permissions/check` **无码也是 200**（J-6a）—— 判定结果是答案，不是异常；
 *  ② `source` 是**判定结果的一部分**（R-29 三态：`default_deny` / `explicit_grant` /
 *     `wildcard_admin`），不是"外部权限源"占位符；三态在本文件各命中一次；
 *  ③ `POST /tools/permissions` 落的是 `resource_permission` 行（tool_id ↔ resource_id）；
 *  ④ `DELETE` 是 **204 零字节体**（J-10），且删除不存在的 id ⇒ 404 `NOT_FOUND`。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ADMIN_PERMISSION, PermissionCatalog, seedPermissions } from "@wbtime/db";

import { TENANT_ID, dataOf, errorOf, makeApp, request } from "./routes-harness.mjs";

/**
 * 给「已注册用户」播种一条 `ACTIVE` 成员关系 + 一个持有指定权限码的角色。
 *
 * 复用**生产**字典种子（`seedPermissions`）与只读字典通道（`PermissionCatalog`）——
 * 与 `rbac-resolver.test.mjs` 的 `grant()` 同一套路，只是把三层合流的三张
 * （`role` / `membership` / `role_permission`）用真 SQL 串起来。**不为测试改生产分支**：
 * 判定仍然走 `authenticate()` → `loadPrincipal()` → `decideCapability()` 的真实链路。
 *
 * @param {object} fixture `makeApp()` 的产物（需 `connection.db` / `raw` / `userId`）。
 * @param {readonly string[]} codes 该角色持有的权限码（可含通配 `*`）。
 * @param {{roleName: string}} options 角色名（同租户内唯一）。
 * @returns {Promise<void>}
 */
async function grantCapabilities(fixture, codes, options) {
  const roleName = options.roleName;
  await seedPermissions(fixture.connection.db, "sqlite");

  const roleId = `role-${roleName}`;
  const permissionIds = [];
  const catalog = new PermissionCatalog(fixture.connection.db, "sqlite");
  for (const code of codes) {
    const permission = await catalog.findByCode(code);
    assert.ok(permission !== null, `字典种子缺 ${code}`);
    permissionIds.push(permission.id);
  }

  fixture.raw
    .prepare("INSERT INTO role (id, tenant_id, name, description, is_system) VALUES (?, ?, ?, ?, ?)")
    .run(roleId, TENANT_ID, roleName, `夹具角色 ${roleName}`, 1);
  fixture.raw
    .prepare(
      "INSERT INTO membership (id, tenant_id, user_id, organization_id, role_id, status) " +
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    .run(`membership-${roleName}`, TENANT_ID, fixture.userId, null, roleId, "ACTIVE");
  const insertRolePermission = fixture.raw.prepare(
    "INSERT INTO role_permission (id, role_id, permission_id) VALUES (?, ?, ?)"
  );
  for (const permissionId of permissionIds) {
    insertRolePermission.run(`rp-${roleName}-${permissionId}`, roleId, permissionId);
  }
}

test("⑪ GET /permissions/check ⇒ 200，四字段恒在（无码也是 200，J-6a）", async () => {
  const fixture = await makeApp({ username: "paul" });

  const granted = await request(fixture, "GET", "/api/v1/permissions/check?cap=marketplace:import");
  assert.equal(granted.statusCode, 200, "check 绝不能因为「没有权限」而返 4xx");
  const body = dataOf(granted);
  assert.deepEqual(Object.keys(body).sort(), [
    "allowed",
    "capability",
    "effect",
    "reason",
    "source",
  ]);
  assert.equal(body.capability, "marketplace:import");
  assert.equal(body.allowed, false, "新注册用户没有 ACTIVE 成员关系 ⇒ 无码");
  assert.equal(body.effect, "DENY");
  assert.equal(body.reason, "permission_not_granted");
  // R-29：`default_deny` 是 py oracle 实测值（`"source":"default_deny"`）。
  // 曾经的 `assert.equal(body.source, null)` 把"丢弃判定结果"锁成了预期行为。
  assert.equal(body.source, "default_deny");

  // 通配 `*` 也不该被"顺手"判成有权限
  const wildcard = await request(fixture, "GET", "/api/v1/permissions/check?cap=*");
  assert.equal(wildcard.statusCode, 200);
  assert.equal(dataOf(wildcard).allowed, false);

  const missing = await request(fixture, "GET", "/api/v1/permissions/check");
  assert.equal(missing.statusCode, 422, "缺 cap 是校验失败（422），不是 400");
  assert.equal(errorOf(missing).code, "VALIDATION_ERROR");
  await fixture.close();
});

test("⑪ R-29 · `source` 三态各命中一次（default_deny / explicit_grant / wildcard_admin）", async () => {
  // 一个夹具走完三态：先无码（default_deny），再授具体码（explicit_grant），
  // 最后追加通配角色（wildcard_admin）。顺序有依赖，**不能**并行造主体。
  const fixture = await makeApp({ username: "r29" });
  const probe = (cap) => request(fixture, "GET", `/api/v1/permissions/check?cap=${cap}`);

  /** `source` 命中序列（末尾断言"恰好三态各一次"）。 */
  const hits = [];

  // ① default_deny —— 没有任何 ACTIVE 成员关系
  const before = dataOf(await probe("marketplace:import"));
  assert.equal(before.allowed, false);
  assert.equal(before.reason, "permission_not_granted");
  assert.equal(before.source, "default_deny");
  hits.push(before.source);

  // ② explicit_grant —— 角色持有具体码（**不是**通配）
  await grantCapabilities(fixture, ["marketplace:import"], { roleName: "r29-editor" });
  const explicit = dataOf(await probe("marketplace:import"));
  assert.equal(explicit.allowed, true, "持有 ACTIVE 成员关系 + 具体码 ⇒ 放行");
  assert.equal(explicit.effect, "ALLOW", "`effect` 与 `allowed` 必须同步");
  assert.equal(explicit.reason, "permission_granted");
  assert.equal(explicit.source, "explicit_grant");
  hits.push(explicit.source);

  // 具体码**只**覆盖它自己：另一个码仍是 default_deny（证明 source 不是"有角色就 explicit"）
  const other = dataOf(await probe("evaluation:run"));
  assert.equal(other.allowed, false);
  assert.equal(other.source, "default_deny");

  // ③ wildcard_admin —— 第二个角色持有通配 `*`
  await grantCapabilities(fixture, [ADMIN_PERMISSION], { roleName: "r29-admin" });
  const wildcard = dataOf(await probe("evaluation:run"));
  assert.equal(wildcard.allowed, true, "通配 `*` 覆盖任意具体码");
  assert.equal(wildcard.reason, "wildcard_admin", "通配优先于具体码（reason 与 source 同源）");
  assert.equal(wildcard.source, "wildcard_admin");
  hits.push(wildcard.source);

  // 闭环：三态各命中一次，没有第四种取值
  assert.deepEqual(hits, ["default_deny", "explicit_grant", "wildcard_admin"]);
  assert.equal(new Set(hits).size, 3, "三态必须互不相同");
  await fixture.close();
});

test("⑫⑬⑭ tools/permissions：列表 → 授予 201 → 重授 409 → 删除 204 → 再删 404", async () => {
  const fixture = await makeApp({ username: "quinn" });
  const agentId = "aaaaaaaa-1111-4111-8111-00000000000a";

  const empty = await request(fixture, "GET", `/api/v1/tools/permissions?agent_id=${agentId}`);
  assert.equal(empty.statusCode, 200);
  assert.deepEqual(dataOf(empty), []);

  const granted = await request(fixture, "POST", "/api/v1/tools/permissions", {
    payload: { tool_id: "tool-1", agent_id: agentId, action: "EXECUTE", effect: "ALLOW" },
  });
  assert.equal(granted.statusCode, 201, granted.body);
  const row = dataOf(granted);
  assert.deepEqual(Object.keys(row).sort(), [
    "action",
    "agent_id",
    "agent_version_id",
    "created_at",
    "effect",
    "id",
    "scope",
    "tenant_id",
    "tool_id",
  ]);
  assert.equal(row.tool_id, "tool-1");
  assert.equal(row.agent_id, agentId);
  assert.equal(row.action, "EXECUTE");
  assert.equal(row.effect, "ALLOW");
  assert.equal(row.agent_version_id, null, "该列不存在 ⇒ 恒 null（已登记遗留）");

  const duplicate = await request(fixture, "POST", "/api/v1/tools/permissions", {
    payload: { tool_id: "tool-1", agent_id: agentId, action: "EXECUTE" },
  });
  assert.equal(duplicate.statusCode, 409, "同主体同工具同动作重复授予 ⇒ 409（不是 500）");
  assert.equal(errorOf(duplicate).code, "CONFLICT");

  const listed = await request(fixture, "GET", `/api/v1/tools/permissions?agent_id=${agentId}`);
  assert.equal(listed.statusCode, 200);
  assert.equal(dataOf(listed).length, 1);
  assert.equal(dataOf(listed)[0].id, row.id);

  const removed = await request(fixture, "DELETE", `/api/v1/tools/permissions/${row.id}`);
  assert.equal(removed.statusCode, 204);
  assert.equal(removed.body, "", "204 必须零字节体（J-10）");

  const again = await request(fixture, "DELETE", `/api/v1/tools/permissions/${row.id}`);
  assert.equal(again.statusCode, 404);
  assert.equal(errorOf(again).code, "NOT_FOUND");

  // 跨租户不可见 ⇒ 同样是 404（不是 403）
  const crossTenant = await request(
    fixture,
    "DELETE",
    "/api/v1/tools/permissions/99999999-9999-4999-8999-999999999999"
  );
  assert.equal(crossTenant.statusCode, 404);
  await fixture.close();
});

test("缺 agent_id 查询参数 ⇒ 422（契约把该参数标为 required）", async () => {
  const fixture = await makeApp({ username: "rita" });
  const response = await request(fixture, "GET", "/api/v1/tools/permissions");
  assert.equal(response.statusCode, 422);
  assert.equal(errorOf(response).code, "VALIDATION_ERROR");
  await fixture.close();
});

test("权限族：无令牌一律 401", async () => {
  const fixture = await makeApp({ username: "sam" });
  for (const [method, url] of [
    ["GET", "/api/v1/permissions/check?cap=marketplace:import"],
    ["GET", "/api/v1/tools/permissions?agent_id=x"],
    ["POST", "/api/v1/tools/permissions"],
    ["DELETE", "/api/v1/tools/permissions/99999999-9999-4999-8999-999999999999"],
  ]) {
    const response = await request(fixture, method, url, { auth: false, ...(method === "POST" ? { payload: {} } : {}) });
    assert.equal(response.statusCode, 401, `${method} ${url} 无令牌必须 401`);
  }
  await fixture.close();
});
