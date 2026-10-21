/**
 * T2-07 · 三条**横切**判据（不属于某个 op，而属于"这 19 个 op 合在一起"）。
 *
 *  ① **J-10：两个 204 op 成功时零字节体**（且不带 `application/json` content-type）；
 *     失败时仍是四键错误壳。
 *  ② **J-6b 反例红线：19 op 一条都不挂 `requirePermission`** —— 用一个**没有任何权限码**
 *     的用户把 19 个 op 各打一遍，**不得出现 403**（401/404/422/200/201/204 都可以）。
 *     这是"没有多加守卫"的正面证明；只测"有权限的用户能过"证明不了它。
 *  ③ **路由清单守恒**：装配后恰好 `/healthz` + 19 个 op，**不多一条**。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ORG_ID, PROVIDER_ID, dataOf, errorOf, makeApp, request } from "./routes-harness.mjs";

/** 19 个 op 的最小可执行请求（用于 ② 的扫描）。 */
function operations(fixture, uniqueSuffix) {
  return [
    {
      id: "register",
      method: "POST",
      url: "/api/v1/auth/register",
      auth: false,
      payload: { username: `sweep${uniqueSuffix}`, email: `sweep${uniqueSuffix}@a.example`, password: "sweep-password-2026" },
    },
    { id: "login", method: "POST", url: "/api/v1/auth/login", auth: false, payload: { username: "sweeper", password: "alice-password-2026" } },
    { id: "refresh", method: "POST", url: "/api/v1/auth/refresh", auth: false, payload: { refresh_token: fixture.tokens.refresh_token } },
    { id: "logout", method: "POST", url: "/api/v1/auth/logout" },
    { id: "read-me", method: "GET", url: "/api/v1/users/me" },
    { id: "update-me", method: "PUT", url: "/api/v1/users/me", payload: { display_name: "Sweeper" } },
    { id: "devices", method: "GET", url: "/api/v1/users/me/devices" },
    { id: "logout-all", method: "POST", url: "/api/v1/users/me/logout-all" },
    { id: "list-organizations", method: "GET", url: "/api/v1/organizations" },
    { id: "get-organization", method: "GET", url: `/api/v1/organizations/${ORG_ID}` },
    { id: "check", method: "GET", url: "/api/v1/permissions/check?cap=marketplace:import" },
    { id: "list-tool-permissions", method: "GET", url: "/api/v1/tools/permissions?agent_id=sweep-agent" },
    { id: "grant", method: "POST", url: "/api/v1/tools/permissions", payload: { tool_id: "tool-sweep" } },
    { id: "revoke", method: "DELETE", url: "/api/v1/tools/permissions/99999999-9999-4999-8999-999999999999" },
    { id: "list-credentials", method: "GET", url: "/api/v1/models/credentials" },
    { id: "save-credential", method: "POST", url: "/api/v1/models/credentials", payload: { provider: "sweep", value: "sweep-value-0123456789" } },
    { id: "delete-credential", method: "DELETE", url: "/api/v1/models/credentials/99999999-9999-4999-8999-999999999999" },
    { id: "bind", method: "POST", url: `/api/v1/models/providers/${PROVIDER_ID}/credential`, payload: { credential_id: "99999999-9999-4999-8999-999999999999" } },
    { id: "unbind", method: "DELETE", url: `/api/v1/models/providers/${PROVIDER_ID}/credential` },
  ];
}

test("J-6b 反例红线：无任何权限码的用户打遍 19 op，**不得出现 403**（也不得 500）", async () => {
  // 夹具里的用户没有 membership ⇒ 权限码集合为空。若有人给某个 route 挂了
  // `requirePermission`，这里就会出现 403 —— 那正是"多加了守卫、破了与 py 的等价性"。
  const fixture = await makeApp({ username: "sweeper" });
  const results = [];
  const ops = operations(fixture, "1");

  for (const [index, op] of ops.entries()) {
    const response = await request(fixture, op.method, op.url, {
      ...(op.auth === false ? { auth: false } : {}),
      ...(op.payload === undefined ? {} : { payload: op.payload }),
    });
    results.push({ id: op.id, status: response.statusCode, body: response.body });

    assert.notEqual(
      response.statusCode,
      403,
      `op ${index + 1} ${op.id} 返回了 403 —— 说明它挂了权限守卫（J-6b 要求一条都不挂）`
    );
    assert.notEqual(response.statusCode, 500, `op ${index + 1} ${op.id} 返回了 500：${response.body}`);
  }

  assert.equal(results.length, 19, "必须覆盖 19 个 op");
  // 落一份快照进诊断，便于复核"哪些是 404 / 422（合法）"
  const summary = results.map((item) => `${item.id}=${item.status}`).join(" ");
  assert.ok(summary.length > 0);
  await fixture.close();
  console.log(`[routes-invariants] 无权限用户扫 19 op 的状态：${summary}`);
});

test("J-10：两个 204 op 成功时**零字节体**，且不带 application/json", async () => {
  const fixture = await makeApp({ username: "zero" });

  // 准备：一条 resource_permission 行 + 一条 credential 行
  const permission = dataOf(
    await request(fixture, "POST", "/api/v1/tools/permissions", {
      payload: { tool_id: "tool-zero" },
    })
  );
  const credential = dataOf(
    await request(fixture, "POST", "/api/v1/models/credentials", {
      payload: { provider: "openai", value: "zero-body-0123456789" },
    })
  );

  for (const [label, url] of [
    ["revoke_permission", `/api/v1/tools/permissions/${permission.id}`],
    ["delete_credential", `/api/v1/models/credentials/${credential.id}`],
  ]) {
    const response = await request(fixture, "DELETE", url);
    assert.equal(response.statusCode, 204, `${label} 必须 204`);
    assert.equal(response.body, "", `${label} 的 body 必须是空串（J-10 零字节体）`);
    assert.equal(
      Buffer.byteLength(response.body, "utf8"),
      0,
      `${label} 的 body 字节数必须为 0`
    );
    const contentType = response.headers["content-type"];
    assert.equal(
      contentType === undefined || !String(contentType).includes("application/json"),
      true,
      `${label} 的 content-type 不得是 json（实测 ${String(contentType)}）`
    );
  }
  await fixture.close();
});

test("J-10 反面：204 失败时仍是四键错误壳（不是空体）", async () => {
  const fixture = await makeApp({ username: "zero2" });
  const response = await request(
    fixture,
    "DELETE",
    "/api/v1/tools/permissions/99999999-9999-4999-8999-999999999999"
  );
  assert.equal(response.statusCode, 404);
  const body = errorOf(response);
  assert.equal(body.code, "NOT_FOUND");
  assert.notEqual(response.body, "", "失败响应必须有壳，不能是空体");
  await fixture.close();
});

test("路由清单守恒：`/healthz` + 19 op，一条不多一条不少", async () => {
  const fixture = await makeApp({ username: "inventory" });

  // ① **正向**：19 个 op 的 (method, path) 逐条存在（`hasRoute` 是 Fastify 的公开 API，
  //    比解析打印树可靠）。参数位写成 Fastify 的 `:param` 形式。
  const expected = [
    ["POST", "/api/v1/auth/register"],
    ["POST", "/api/v1/auth/login"],
    ["POST", "/api/v1/auth/refresh"],
    ["POST", "/api/v1/auth/logout"],
    ["GET", "/api/v1/users/me"],
    ["PUT", "/api/v1/users/me"],
    ["GET", "/api/v1/users/me/devices"],
    ["POST", "/api/v1/users/me/logout-all"],
    ["GET", "/api/v1/organizations"],
    ["GET", "/api/v1/organizations/:organization_id"],
    ["GET", "/api/v1/permissions/check"],
    ["GET", "/api/v1/tools/permissions"],
    ["POST", "/api/v1/tools/permissions"],
    ["DELETE", "/api/v1/tools/permissions/:permission_id"],
    ["GET", "/api/v1/models/credentials"],
    ["POST", "/api/v1/models/credentials"],
    ["DELETE", "/api/v1/models/credentials/:credential_id"],
    ["POST", "/api/v1/models/providers/:provider_id/credential"],
    ["DELETE", "/api/v1/models/providers/:provider_id/credential"],
  ];
  assert.equal(expected.length, 19);
  for (const [method, url] of expected) {
    assert.equal(fixture.app.hasRoute({ method, url }), true, `缺少路由 ${method} ${url}`);
  }
  assert.equal(fixture.app.hasRoute({ method: "GET", url: "/healthz" }), true);

  // ② **反向**：注册的**方法总数**恰为 20（19 op + healthz）。
  //    为什么不逐条比对打印树：`printRoutes` 输出的是前缀树，参数段只是 `/:id` 子行，
  //    重建完整路径要靠缩进猜层数 —— 那种解析本身就会成为新的脆弱点。
  //    Fastify 默认 `exposeHeadRoutes: true`，GET 会隐含一个 HEAD，故统计时排除 HEAD。
  const printed = fixture.app.printRoutes({ commonPrefix: false });
  let methodCount = 0;
  for (const line of printed.split("\n")) {
    const methods = /\(([A-Z, ]+)\)/.exec(line)?.[1];
    if (methods === undefined) continue;
    methodCount += methods
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item !== "" && item !== "HEAD").length;
  }
  assert.equal(methodCount, 20, `注册的方法总数应为 20（19 op + /healthz），实测 ${methodCount}`);

  // ③ 契约外路由族一个都不许有（U-3 / R-26 已裁定不纳入）
  for (const [method, url] of [
    ["GET", "/api/v1/settings/credentials"],
    ["POST", "/api/v1/settings/credentials"],
    ["GET", "/api/v1/workspaces"],
  ]) {
    assert.equal(fixture.app.hasRoute({ method, url }), false, `出现契约外路由：${method} ${url}`);
  }
  await fixture.close();
});

test("体 == 头：成功与失败的 request_id 都等于 X-Request-Id", async () => {
  const fixture = await makeApp({ username: "header" });

  const ok = await request(fixture, "GET", "/api/v1/users/me");
  assert.equal(JSON.parse(ok.body).request_id, ok.headers["x-request-id"]);

  const bad = await request(fixture, "GET", "/api/v1/organizations/99999999-9999-4999-8999-999999999999");
  assert.equal(bad.statusCode, 404);
  assert.equal(JSON.parse(bad.body).request_id, bad.headers["x-request-id"]);
  await fixture.close();
});
