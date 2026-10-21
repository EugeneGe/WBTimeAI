/**
 * T2-07 · 路由测试的共用夹具（**不是** test 文件 —— 文件名不带 `.test.mjs`）。
 *
 * 与 T2-04 的 `auth-harness.mjs` 同一套路：真库（`createSqliteDb` + 整份 DDL）+ 真
 * `buildApp()` + `app.inject()`（**不绑端口**，不产生真实网络依赖）。
 *
 * 注册用户走**真实 HTTP 路由**（`POST /api/v1/auth/register`）而不是直接插库：
 * 这样夹具本身就在证明"注册 → 拿到令牌 → 用令牌打后续 op"这条最关键的链路，
 * 而不是让测试跨过它去用内部对象。
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "@wbtime/config";
import { createSqliteDb } from "@wbtime/db/connection";

import { buildApp } from "../dist/app.js";

/** 仓库根（apps/api/tests → apps/api → apps → 根）。 */
export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

/** 测试主密钥（≥32 字节；**不是**任何真实部署的密钥）。 */
export const TEST_SECRET = "wbtime-test-secret-key-0123456789abcdef";

/** 主租户。 */
export const TENANT_ID = "11111111-1111-4111-8111-111111111111";

/** 第二个租户（只用于证明"跨租户 ⇒ 404 而不是 403"）。 */
export const OTHER_TENANT_ID = "22222222-2222-4222-8222-222222222222";

/** 其它租户下的组织（本租户**不该**看得见）。 */
export const OTHER_ORG_ID = "2b2b2b2b-0000-4000-8000-00000000000b";

/** 本租户组织。 */
export const ORG_ID = "1a1a1a1a-0000-4000-8000-00000000000a";

/** 本租户供应商（绑定 / 解绑 op 的靶子）。 */
export const PROVIDER_ID = "1c1c1c1c-0000-4000-8000-00000000000c";

const DDL = readFileSync(join(ROOT, "output", "ddl.sqlite.sql"), "utf8");

/** 只含"注册即可用"所需的最小配置。 */
export function testConfig(extra = {}) {
  return loadConfig({ WBTIME_AI_MODE: "local", WBTIME_AI_SECRET_KEY: TEST_SECRET, ...extra });
}

/**
 * 建一个装了 19 op 的应用并注册一个用户。
 *
 * @param {{username?: string, extraEnv?: Record<string,string>}} [options]
 * @returns 夹具对象（`app` / `connection` / `userId` / `authHeader` / `tokens` / `raw`）。
 */
export async function makeApp(options = {}) {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  seedTenants(connection.raw);

  const app = buildApp({
    config: testConfig(options.extraEnv ?? {}),
    enableLogging: false,
    database: connection.db,
    dialect: "sqlite",
    tenantId: TENANT_ID,
  });
  await app.ready();

  const username = options.username ?? "alice";
  const registered = await app.inject({
    method: "POST",
    url: "/api/v1/auth/register",
    payload: { username, email: `${username}@a.example`, password: "alice-password-2026" },
  });
  if (registered.statusCode !== 201) {
    throw new Error(`夹具注册失败：${registered.statusCode} ${registered.body}`);
  }
  const tokens = JSON.parse(registered.body).data;
  const userId = decodeSub(tokens.access_token);

  return {
    app,
    connection,
    raw: connection.raw,
    tokens,
    userId,
    authHeader: `Bearer ${tokens.access_token}`,
    close: async () => {
      await app.close();
      connection.close();
    },
  };
}

/** 两个租户 + 两个组织 + 一个供应商（供应商属于本租户）。 */
export function seedTenants(raw) {
  const insertTenant = raw.prepare("INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, ?)");
  insertTenant.run(TENANT_ID, "租户 A", "tenant-a", 1);
  insertTenant.run(OTHER_TENANT_ID, "租户 B", "tenant-b", 1);

  const insertOrg = raw.prepare(
    "INSERT INTO organization (id, tenant_id, name, slug) VALUES (?, ?, ?, ?)"
  );
  insertOrg.run(ORG_ID, TENANT_ID, "组织 A", "org-a");
  insertOrg.run(OTHER_ORG_ID, OTHER_TENANT_ID, "组织 B", "org-b");

  raw
    .prepare(
      "INSERT INTO model_provider (id, tenant_id, name, type, endpoint, status, config) " +
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    .run(PROVIDER_ID, TENANT_ID, "openai-main", "openai", "https://api.openai.com/v1", "ACTIVE", "{}");
}

/**
 * 发一个请求（统一带上 Bearer 与 JSON content-type）。
 *
 * @param {object} fixture {@link makeApp} 的产物。
 * @param {string} method HTTP 方法。
 * @param {string} url 路径（可含 query）。
 * @param {{payload?: unknown, headers?: Record<string,string>, auth?: boolean}} [options]
 */
export function request(fixture, method, url, options = {}) {
  const headers = {
    ...(options.auth === false ? {} : { authorization: fixture.authHeader }),
    ...(options.headers ?? {}),
  };
  if (options.payload !== undefined) headers["content-type"] = "application/json";
  return fixture.app.inject({
    method,
    url,
    headers,
    ...(options.payload === undefined ? {} : { payload: options.payload }),
  });
}

/** 从 JWT 里取 `sub`（不验签，只用于断言）。 */
export function decodeSub(token) {
  const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf8"));
  return payload.sub;
}

/** 解析成功壳并返回 `data`（同时断言壳的形状）。 */
export function dataOf(response) {
  const body = JSON.parse(response.body);
  if (body.code !== 0 || body.message !== "ok") {
    throw new Error(`期望成功壳，实测 ${response.statusCode} ${response.body}`);
  }
  if (!Object.hasOwn(body, "request_id")) throw new Error("成功壳缺 request_id");
  if (!Object.hasOwn(body, "data")) throw new Error("成功壳缺 data");
  return body.data;
}

/** 解析失败壳（同时断言四键齐备）。 */
export function errorOf(response) {
  const body = JSON.parse(response.body);
  for (const key of ["code", "message", "data", "request_id"]) {
    if (!Object.hasOwn(body, key)) throw new Error(`失败壳缺 ${key}：${response.body}`);
  }
  return body;
}
