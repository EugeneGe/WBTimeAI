/**
 * T2-07 · 用户族 + 组织族（§1 表 5–10）。
 *
 * 判据面：成功码、响应键集合（与契约一致由 alignment 测试守）、以及 **I-1 的 404 语义**
 * —— `GET /organizations/{别的租户的 id}` 必须是 404 `ORGANIZATION_NOT_FOUND`，
 * **不是 403**（303 会把"这个 id 存在但你看不到"告诉调用方）。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ORG_ID,
  OTHER_ORG_ID,
  dataOf,
  errorOf,
  makeApp,
  request,
} from "./routes-harness.mjs";

test("⑤ GET /users/me ⇒ 200，UserResponse 八键齐备且 is_active=true", async () => {
  const fixture = await makeApp({ username: "ivan" });
  const response = await request(fixture, "GET", "/api/v1/users/me");

  assert.equal(response.statusCode, 200, response.body);
  const data = dataOf(response);
  assert.deepEqual(Object.keys(data).sort(), [
    "created_at",
    "display_name",
    "email",
    "id",
    "is_active",
    "is_superuser",
    "tenant_id",
    "username",
  ]);
  assert.equal(data.id, fixture.userId);
  assert.equal(data.username, "ivan");
  assert.equal(data.is_active, true);
  assert.equal(data.is_superuser, false);
  assert.equal(Object.hasOwn(data, "password_hash"), false, "响应绝不能带口令哈希");
  await fixture.close();
});

test("⑥ PUT /users/me ⇒ 200；可改 display_name，也可显式置 null 清空", async () => {
  const fixture = await makeApp({ username: "judy" });

  const set = await request(fixture, "PUT", "/api/v1/users/me", {
    payload: { display_name: "Judy Q" },
  });
  assert.equal(set.statusCode, 200);
  assert.equal(dataOf(set).display_name, "Judy Q");

  const clear = await request(fixture, "PUT", "/api/v1/users/me", { payload: { display_name: null } });
  assert.equal(clear.statusCode, 200);
  assert.equal(dataOf(clear).display_name, null, "显式 null 必须真的清空");
  await fixture.close();
});

test("⑦ GET /users/me/devices ⇒ 200 数组，DeviceResponse 七键（含 created_at）", async () => {
  const fixture = await makeApp({ username: "karl" });
  const response = await request(fixture, "GET", "/api/v1/users/me/devices");

  assert.equal(response.statusCode, 200, response.body);
  const devices = dataOf(response);
  assert.equal(Array.isArray(devices), true);
  assert.equal(devices.length, 1, "注册即建一条会话");
  assert.deepEqual(Object.keys(devices[0]).sort(), [
    "created_at",
    "device",
    "expires_at",
    "id",
    "ip_address",
    "revoked_at",
    "user_agent",
  ]);
  assert.equal(devices[0].revoked_at, null);
  assert.match(devices[0].expires_at, /^\d{4}-\d{2}-\d{2}T/, "时间必须是 ISO-8601");
  await fixture.close();
});

test("⑧ POST /users/me/logout-all ⇒ 200 MessageResponse，之后 refresh 全部失效", async () => {
  const fixture = await makeApp({ username: "laura" });

  const response = await request(fixture, "POST", "/api/v1/users/me/logout-all");
  assert.equal(response.statusCode, 200);
  assert.deepEqual(Object.keys(dataOf(response)), ["message"]);

  const refresh = await request(fixture, "POST", "/api/v1/auth/refresh", {
    auth: false,
    payload: { refresh_token: fixture.tokens.refresh_token },
  });
  assert.equal(refresh.statusCode, 401);
  assert.equal(errorOf(refresh).code, "AUTH_TOKEN_REVOKED");
  await fixture.close();
});

test("⑨ GET /organizations ⇒ 200 且只含本租户组织", async () => {
  const fixture = await makeApp({ username: "mike" });
  const response = await request(fixture, "GET", "/api/v1/organizations");

  assert.equal(response.statusCode, 200);
  const organizations = dataOf(response);
  assert.equal(organizations.length, 1, "只该看到本租户的 1 个组织");
  assert.equal(organizations[0].id, ORG_ID);
  assert.deepEqual(Object.keys(organizations[0]).sort(), ["id", "name", "slug", "tenant_id"]);
  await fixture.close();
});

test("⑩ GET /organizations/{id} ⇒ 200；**跨租户 ⇒ 404 而不是 403**（I-1）", async () => {
  const fixture = await makeApp({ username: "nina" });

  const own = await request(fixture, "GET", `/api/v1/organizations/${ORG_ID}`);
  assert.equal(own.statusCode, 200);
  assert.equal(dataOf(own).id, ORG_ID);

  const crossTenant = await request(fixture, "GET", `/api/v1/organizations/${OTHER_ORG_ID}`);
  assert.equal(crossTenant.statusCode, 404, "跨租户必须 404（403 会泄露该 id 存在）");
  const body = errorOf(crossTenant);
  assert.equal(body.code, "ORGANIZATION_NOT_FOUND");
  // 失败壳不得带"资源存在性"线索
  assert.deepEqual(body.data, { organization_id: OTHER_ORG_ID });

  const missing = await request(
    fixture,
    "GET",
    "/api/v1/organizations/99999999-9999-4999-8999-999999999999"
  );
  assert.equal(missing.statusCode, 404);
  assert.equal(errorOf(missing).code, "ORGANIZATION_NOT_FOUND");
  await fixture.close();
});

test("用户族 / 组织族：无令牌一律 401（不是 404、不是 403）", async () => {
  const fixture = await makeApp({ username: "oscar" });
  for (const [method, url] of [
    ["GET", "/api/v1/users/me"],
    ["PUT", "/api/v1/users/me"],
    ["GET", "/api/v1/users/me/devices"],
    ["POST", "/api/v1/users/me/logout-all"],
    ["GET", "/api/v1/organizations"],
    ["GET", `/api/v1/organizations/${ORG_ID}`],
  ]) {
    const response = await request(fixture, method, url, {
      auth: false,
      ...(method === "PUT" ? { payload: {} } : {}),
    });
    assert.equal(response.statusCode, 401, `${method} ${url} 无令牌必须 401`);
    assert.equal(errorOf(response).code, "UNAUTHORIZED");
  }
  await fixture.close();
});
