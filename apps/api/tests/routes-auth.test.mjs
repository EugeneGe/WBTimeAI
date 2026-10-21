/**
 * T2-07 · 认证族 4 op 的**真实 HTTP** 行为（含 L-3 密钥闸）。
 *
 * 判据面：成功码（201/200）、`TokenResponse` 四键、`request_id == X-Request-Id`、
 * 失败壳四键、刷新轮换、登出幂等、以及 **`requireSecretKey` 真接线**（密钥缺失 / 31 字节
 * ⇒ `CONFIGURATION_ERROR`）。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { ConfigError } from "@wbtime/config";

import { buildApp } from "../dist/app.js";
import { DEFAULT_TENANT_ID } from "../dist/app.js";
import { dataOf, errorOf, makeApp, request, TENANT_ID, testConfig } from "./routes-harness.mjs";

test("① POST /auth/register ⇒ 201，回 TokenResponse 四键，request_id == X-Request-Id", async () => {
  const fixture = await makeApp({ username: "bob" });
  const response = await request(fixture, "POST", "/api/v1/auth/register", {
    auth: false,
    payload: { username: "carol", email: "carol@a.example", password: "carol-password-2026" },
  });

  assert.equal(response.statusCode, 201, response.body);
  const data = dataOf(response);
  assert.deepEqual(Object.keys(data).sort(), [
    "access_token",
    "expires_in",
    "refresh_token",
    "token_type",
  ]);
  assert.equal(data.token_type, "bearer");
  assert.equal(data.expires_in, 900);
  assert.equal(
    response.headers["x-request-id"],
    JSON.parse(response.body).request_id,
    "体 == 头（request_id 必须同源）"
  );
  await fixture.close();
});

test("② POST /auth/login ⇒ 200；错口令 ⇒ 401 AUTH_INVALID_CREDENTIALS", async () => {
  const fixture = await makeApp({ username: "dave" });

  const ok = await request(fixture, "POST", "/api/v1/auth/login", {
    auth: false,
    payload: { username: "dave", password: "alice-password-2026" },
  });
  assert.equal(ok.statusCode, 200);
  assert.ok(dataOf(ok).access_token);

  const bad = await request(fixture, "POST", "/api/v1/auth/login", {
    auth: false,
    payload: { username: "dave", password: "wrong-password" },
  });
  assert.equal(bad.statusCode, 401);
  assert.equal(errorOf(bad).code, "AUTH_INVALID_CREDENTIALS");
  await fixture.close();
});

test("③ POST /auth/refresh ⇒ 200 轮换；旧 refresh 二次使用 ⇒ 401 AUTH_TOKEN_REVOKED", async () => {
  const fixture = await makeApp({ username: "erin" });

  const refreshed = await request(fixture, "POST", "/api/v1/auth/refresh", {
    auth: false,
    payload: { refresh_token: fixture.tokens.refresh_token },
  });
  assert.equal(refreshed.statusCode, 200);
  const rotated = dataOf(refreshed);
  assert.notEqual(rotated.refresh_token, fixture.tokens.refresh_token, "必须换发新 refresh");

  const reuse = await request(fixture, "POST", "/api/v1/auth/refresh", {
    auth: false,
    payload: { refresh_token: fixture.tokens.refresh_token },
  });
  assert.equal(reuse.statusCode, 401);
  assert.equal(errorOf(reuse).code, "AUTH_TOKEN_REVOKED");
  await fixture.close();
});

test("④ POST /auth/logout ⇒ 200 MessageResponse；连打两次都成功（幂等）；无令牌 ⇒ 401", async () => {
  const fixture = await makeApp({ username: "frank" });

  const first = await request(fixture, "POST", "/api/v1/auth/logout");
  assert.equal(first.statusCode, 200);
  assert.deepEqual(Object.keys(dataOf(first)), ["message"]);

  const second = await request(fixture, "POST", "/api/v1/auth/logout");
  assert.equal(second.statusCode, 200, "同一 access 连打 2 次必须都 200（解码不查 session）");

  const noToken = await request(fixture, "POST", "/api/v1/auth/logout", { auth: false });
  assert.equal(noToken.statusCode, 401);
  assert.equal(errorOf(noToken).code, "UNAUTHORIZED");
  await fixture.close();
});

test("注册重名 ⇒ 409 USER_ALREADY_EXISTS；口令过短 ⇒ 422 VALIDATION_ERROR", async () => {
  const fixture = await makeApp({ username: "grace" });

  const duplicate = await request(fixture, "POST", "/api/v1/auth/register", {
    auth: false,
    payload: { username: "grace", email: "other@a.example", password: "another-password-2026" },
  });
  assert.equal(duplicate.statusCode, 409);
  assert.equal(errorOf(duplicate).code, "USER_ALREADY_EXISTS");

  const tooShort = await request(fixture, "POST", "/api/v1/auth/register", {
    auth: false,
    payload: { username: "henry", email: "henry@a.example", password: "12345" },
  });
  assert.equal(tooShort.statusCode, 422, "schema 的 minLength=6 应先于 service 生效");
  assert.equal(errorOf(tooShort).code, "VALIDATION_ERROR");
  await fixture.close();
});

// ---------------------------------------------------------------------------
// L-3 / R-22 · requireSecretKey 真接线
// ---------------------------------------------------------------------------

test("L-3 · 密钥缺失 ⇒ 装配失败 CONFIGURATION_ERROR（不是运行期 TypeError）", async () => {
  const { createSqliteDb } = await import("@wbtime/db/connection");
  const connection = createSqliteDb(":memory:");

  const config = testConfig();
  // 造一个"没有密钥"的配置（`loadConfig` 允许 null，故这里直接构造同形状对象）
  const withoutSecret = { ...config, secretKey: null };

  assert.throws(
    () =>
      buildApp({
        config: withoutSecret,
        enableLogging: false,
        database: connection.db,
        dialect: "sqlite",
        tenantId: TENANT_ID,
      }),
    (error) => {
      assert.ok(error instanceof ConfigError, `期望 ConfigError，实测 ${String(error)}`);
      assert.equal(error.code, "CONFIGURATION_ERROR");
      assert.match(error.message, /WBTIME_AI_SECRET_KEY/);
      return true;
    }
  );
  connection.close();
});

test("L-3 · 密钥只有 31 字节 ⇒ 装配失败 CONFIGURATION_ERROR（TokenService 不校长度，故必须在这里挡）", async () => {
  const { createSqliteDb } = await import("@wbtime/db/connection");
  const connection = createSqliteDb(":memory:");

  const config = testConfig();
  const shortKey = "0123456789abcdef0123456789abcde"; // 31 字节
  assert.equal(Buffer.byteLength(shortKey, "utf8"), 31, "夹具必须是 31 字节");

  assert.throws(
    () =>
      buildApp({
        config: { ...config, secretKey: shortKey },
        enableLogging: false,
        database: connection.db,
        dialect: "sqlite",
        tenantId: TENANT_ID,
      }),
    (error) => {
      assert.ok(error instanceof ConfigError, `期望 ConfigError，实测 ${String(error)}`);
      assert.equal(error.code, "CONFIGURATION_ERROR");
      assert.match(error.message, /31 字节/);
      return true;
    }
  );
  connection.close();
});

test("L-3 · main.ts 的启动路径同样拦截（requireSecretKey 在 start 里）", async () => {
  const { start } = await import("../dist/main.js");
  const config = { ...testConfig(), secretKey: null };
  await assert.rejects(() => start(config), (error) => {
    assert.ok(error instanceof ConfigError);
    assert.equal(error.code, "CONFIGURATION_ERROR");
    return true;
  });
});

test("默认租户常量存在（单租户过渡方案，租户自举归 V0.6.0）", () => {
  assert.match(DEFAULT_TENANT_ID, /^[0-9a-f-]{36}$/);
});
