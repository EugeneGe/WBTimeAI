/**
 * T2-04 · 认证测试的共用夹具（**不是** test 文件 —— 文件名刻意不带 `.test.mjs`）。
 *
 * 为什么单独成文件：J-4 / J-5 都要"真库 + 真服务"，各自复制一份 `freshDb()` 的
 * 结果就是两份会漂移的夹具。这里只做三件事：建库灌 DDL、种租户/用户、装配服务。
 *
 * 真库策略与 `packages/db/tests/identity-repos.test.mjs` 同源：`node --experimental-sqlite`
 * + `createSqliteDb`（生产代码的连接工厂）+ 整份 `output/ddl.sqlite.sql` ⇒ 真 SQL。
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createSqliteDb } from "@wbtime/db/connection";

import { AuthService } from "../dist/modules/auth/service.js";

/** 仓库根（apps/api/tests → apps/api → apps → 根）。 */
export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

const DDL_PATH = join(ROOT, "output", "ddl.sqlite.sql");
const DDL = readFileSync(DDL_PATH, "utf8");

/** 用于签名的测试密钥（≥32 字节；**不是**任何真实部署的密钥）。 */
export const TEST_SECRET = "wbtime-test-secret-key-0123456789abcdef";

/** 默认测试租户。 */
export const TENANT_ID = "11111111-1111-4111-8111-111111111111";

/** 建内存库并灌整份 SQLite DDL。 */
export function freshDb() {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  return connection;
}

/** 种一条 tenant 行（`is_active` 可控 —— 计划 §2 的"租户停用 ⇒ 401"要用）。 */
export function seedTenant(raw, { id = TENANT_ID, slug = "tenant-a", isActive = 1 } = {}) {
  raw
    .prepare("INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, ?)")
    .run(id, `租户 ${slug}`, slug, isActive);
  return id;
}

/**
 * 装配一个 `AuthService`（sqlite 档 + 固定时钟）。
 *
 * @param {{db: unknown, now?: () => Date, tenantId?: string, maxAttempts?: number, lockSeconds?: number, sessionTtlSeconds?: number}} options
 */
export function makeService(options) {
  return new AuthService({
    db: options.db,
    dialect: "sqlite",
    tenantId: options.tenantId ?? TENANT_ID,
    secretKey: TEST_SECRET,
    ...(options.now ? { now: options.now } : {}),
    ...(options.maxAttempts === undefined ? {} : { maxAttempts: options.maxAttempts }),
    ...(options.lockSeconds === undefined ? {} : { lockSeconds: options.lockSeconds }),
    ...(options.sessionTtlSeconds === undefined
      ? {}
      : { sessionTtlSeconds: options.sessionTtlSeconds }),
  });
}

/**
 * 断言一个被拒的调用：`code` 与 HTTP 状态**同时**比。
 *
 * 只比 code 会漏掉"码对但状态错"（例如 423 被映射成 401），而状态恰是 J-5 的判据。
 *
 * @param {() => Promise<unknown>} thunk 触发调用。
 * @param {{code: string, status: number}} expected 期望的码与状态。
 * @param {string} [label] 断言标签（失败信息里带上便于定位）。
 */
export async function expectRejected(thunk, expected, label = "") {
  try {
    await thunk();
  } catch (error) {
    const actualCode = error?.code;
    const actualStatus = error?.statusCode ?? error?.status;
    if (actualCode !== expected.code || actualStatus !== expected.status) {
      throw new Error(
        `${label}：期望 ${expected.code}(${expected.status})，实测 ${String(actualCode)}(${String(
          actualStatus
        )}) —— ${String(error?.message)}`
      );
    }
    return error;
  }
  throw new Error(`${label}：期望被拒（${expected.code}），实际调用成功了`);
}
