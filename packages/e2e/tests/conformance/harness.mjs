/**
 * T2-06 · I-1 跨租户 404 套件的**夹具装配**（`tenant-404.cases.mjs` 的唯一接缝）。
 *
 * 契约（骨架文件 §夹具契约，逐字实现）：
 *
 *   export async function createHarness(): Promise<{
 *     app: { inject(req), hasRoute({ method, url }) },   // 已 ready 的 TS 后端实例
 *     authFor(tenant: "a" | "b"): { authorization: string },
 *     resourceId(family: string, tenant: "a" | "b"): string,
 *     snapshot(caseId: string): Promise<unknown>,
 *   }>
 *
 * 装配形态（与 `apps/api` 的 T2-04/T2-07 测试同一装配面，不是第二套后端）：
 *
 *   * 数据库   —— `createSqliteDb(":memory:")` + 整份灌 `output/ddl.sqlite.sql`（61 表）；
 *   * 后端     —— `import { buildApp } from "../../../../apps/api/dist/app.js"`（**编译产物**，
 *                 与生产同源；不 import src）；
 *   * 双租户   —— `buildApp` 的 `IdentityDeps.tenantId` 是装配期常量（register/login 用它），
 *                 而资源族的作用域租户来自 **JWT claims**（`authenticate()` 用
 *                 `claims.tenantId` 建 Scope）。因此用**同一个数据库**装配两个实例
 *                 （租户 A / 租户 B），各自注册本租户用户；之后所有资源级请求统一走
 *                 A 实例 —— 令牌里的 tenant_id 决定作用域，这正是 I-1 要验证的链路。
 *   * 令牌     —— `authFor(tenant)` 走**真实 HTTP register → login** 链拿 access_token。
 *   * 快照     —— `snapshot(caseId)` 直接查库（行数 + 全行内容，按 id 排序），
 *                 骨架用 `assert.deepEqual` 做零副作用判定。
 *
 * 运行方式（见 `T2-06.md`）：
 *   WBTIME_CONFORMANCE_HARNESS=file://<repo>/packages/e2e/tests/conformance/harness.mjs \
 *   node --test packages/e2e/tests/conformance/tenant-404.cases.mjs
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { DEFAULT_TENANT_ID, buildApp } from "../../../../apps/api/dist/app.js";
import { loadConfig } from "../../../../packages/config/dist/index.js";
import { createSqliteDb } from "../../../../packages/db/dist/connection.js";

/** 本文件所在目录（`packages/e2e/tests/conformance/`）。 */
const HERE = path.dirname(fileURLToPath(import.meta.url));

/** 仓根（conformance → tests → e2e → packages → 根）。 */
const REPO_ROOT = path.resolve(HERE, "..", "..", "..", "..");

/** DDL（61 表）——夹具库的唯一定义源，与生产 `output/ddl.sqlite.sql` 同一份。 */
const DDL_PATH = path.join(REPO_ROOT, "output", "ddl.sqlite.sql");

/**
 * 测试主密钥（≥ 32 UTF-8 字节；与生产密钥无关，仅用于本套件的 JWT / 凭据加密）。
 * 长度校验：`"wbtime-e2e-conformance-secret-key-0123456789abcdef".length === 50`。
 */
const SECRET_KEY = "wbtime-e2e-conformance-secret-key-0123456789abcdef";

/** 测试口令（满足 `assertAcceptablePassword`：≥ 6 码点）。 */
const PASSWORD = "E2e-Passw0rd!23";

/** 租户 A：用装配缺省租户（`DEFAULT_TENANT_ID`），证明缺省租户链路同样受 I-1 约束。 */
const TENANT_A = DEFAULT_TENANT_ID;

/** 租户 B：随机 UUID（运行期生成，杜绝与任何固定夹具串巧合相等）。 */
const TENANT_B = randomUUID();

/** 副作用快照覆盖的表（资源 4 族 + 身份链路；行数小，全量快照成本可忽略）。 */
const SNAPSHOT_TABLES = Object.freeze([
  "user",
  "organization",
  "credential",
  "model_provider",
  "model_provider_credential",
  "resource_permission",
  "agent",
  "session",
  "refresh_token",
]);

/**
 * 创建夹具。骨架的 `loadHarness()` 会在收集测试时调用一次。
 *
 * @returns 骨架 §夹具契约声明的夹具对象（另附 `postPayload` / `close` 扩展）。
 */
export async function createHarness() {
  // ── 1. 数据库：内存 SQLite + 整份 DDL ──────────────────────────────────────
  const sqlite = createSqliteDb(":memory:");
  sqlite.raw.exec(readFileSync(DDL_PATH, "utf8"));

  // ── 2. 租户种子：register/login 前置是「租户存在且启用」（AuthService#assertTenantActive）──
  const insertTenant = sqlite.raw.prepare(
    "INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, 1)",
  );
  insertTenant.run(TENANT_A, "conformance-tenant-a", "conformance-tenant-a");
  insertTenant.run(TENANT_B, "conformance-tenant-b", "conformance-tenant-b");

  // ── 3. 装配：同一数据库 × 两个租户实例 ─────────────────────────────────────
  const config = loadConfig({
    WBTIME_AI_MODE: "local",
    WBTIME_AI_SECRET_KEY: SECRET_KEY,
    WBTIME_LOG_LEVEL: "error",
  });
  const shared = {
    config,
    database: sqlite.db,
    dialect: "sqlite",
    enableLogging: false,
  };
  const appA = buildApp({ ...shared, tenantId: TENANT_A });
  const appB = buildApp({ ...shared, tenantId: TENANT_B });
  await appA.ready();
  await appB.ready();

  // ── 4. 用户：真实 register → login 链（HTTP 面，不是直调服务） ─────────────
  const tokenA = await registerAndLogin(appA, "conformance_user_a", "user-a@conformance.test");
  const tokenB = await registerAndLogin(appB, "conformance_user_b", "user-b@conformance.test");

  // ── 5. 直插资源（无对应写 op 的族）：organization / model_provider / agent ──
  const ids = {
    organization: { a: randomUUID(), b: randomUUID() },
    model_provider: { a: randomUUID(), b: randomUUID() },
    agent: { a: randomUUID() },
  };
  const insertOrganization = sqlite.raw.prepare(
    "INSERT INTO organization (id, tenant_id, name, slug) VALUES (?, ?, ?, ?)",
  );
  insertOrganization.run(ids.organization.a, TENANT_A, "org-a", "org-a");
  insertOrganization.run(ids.organization.b, TENANT_B, "org-b", "org-b");

  const insertProvider = sqlite.raw.prepare(
    "INSERT INTO model_provider (id, tenant_id, name, type, status) VALUES (?, ?, ?, ?, ?)",
  );
  insertProvider.run(ids.model_provider.a, TENANT_A, "provider-a", "openai", "ACTIVE");
  insertProvider.run(ids.model_provider.b, TENANT_B, "provider-b", "openai", "ACTIVE");

  // agent：A 租户必须有（`GET /tools/permissions?agent_id=` 是契约必填）；created_by 指向 A 租户用户。
  const userARow = sqlite.raw
    .prepare("SELECT id FROM \"user\" WHERE tenant_id = ? AND username = ?")
    .get(TENANT_A, "conformance_user_a");
  assert.equal(typeof userARow?.id, "string", "A 租户用户必须已落库（agent 夹具的前置）");
  sqlite.raw
    .prepare(
      "INSERT INTO agent (id, tenant_id, name, type, status, created_by) VALUES (?, ?, ?, ?, ?, ?)",
    )
    .run(ids.agent.a, TENANT_A, "agent-a", "chat", "active", userARow.id);

  // ── 6. HTTP 建资源（有写 op 的族）：credential / tool_permission ───────────
  const credentialIds = {};
  for (const [tenant, app, token] of [
    ["a", appA, tokenA],
    ["b", appB, tokenB],
  ]) {
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/models/credentials",
      headers: { authorization: `Bearer ${token}` },
      payload: { provider: "openai", value: `sk-conformance-${tenant}-${randomUUID()}` },
    });
    assert.equal(
      response.statusCode,
      201,
      `credential 夹具（租户 ${tenant}）期望 201，实得 ${response.statusCode} :: ${response.body.slice(0, 300)}`,
    );
    credentialIds[tenant] = response.json().data.id;
  }

  const permissionIds = {};
  for (const [tenant, app, token] of [
    ["a", appA, tokenA],
    ["b", appB, tokenB],
  ]) {
    // A 租户的授权记在 **A 的 agent** 名下（`agent_id` ⇒ `subject_type='agent'`）：
    // `GET /tools/permissions?agent_id=` 是**按主体查**（`listBySubject("agent", …)`），
    // #10 双向判据要求该列表能查到 A 自己的行 —— 主体若是 user，按 agent 查恒空。
    // B 租户保持 user 主体（无 agent 夹具），它的行本就不该出现在 A 的列表里。
    const payload = { tool_id: `tool-conformance-${tenant}` };
    if (tenant === "a") payload.agent_id = ids.agent.a;
    const response = await app.inject({
      method: "POST",
      url: "/api/v1/tools/permissions",
      headers: { authorization: `Bearer ${token}` },
      payload,
    });
    assert.equal(
      response.statusCode,
      201,
      `tool_permission 夹具（租户 ${tenant}）期望 201，实得 ${response.statusCode} :: ${response.body.slice(0, 300)}`,
    );
    permissionIds[tenant] = response.json().data.id;
  }

  const resources = {
    organization: ids.organization,
    model_credential: credentialIds,
    model_provider: ids.model_provider,
    tool_permission: permissionIds,
    agent: ids.agent,
  };

  // ── 7. 夹具对象 ───────────────────────────────────────────────────────────
  return {
    /**
     * 已 ready 的 A 租户实例（资源级请求统一走它；作用域租户由令牌 claims 决定）。
     * `hasRoute` 做 `{param}` → `:param` 翻译：骨架的矩阵写契约形态
     * `/organizations/{organization_id}`，而 Fastify 注册面是 `:organization_id`
     * —— find-my-way 的 `hasRoute` 按**注册形态**匹配，不翻译就会把「空转守卫」
     * 误报成「路由未注册」。
     */
    app: {
      inject: (request) => appA.inject(request),
      hasRoute: ({ method, url }) =>
        appA.hasRoute({ method, url: url.replace(/\{([a-z_]+)\}/g, ":$1") }),
    },

    /** Bearer 头（令牌来自真实 register → login 链）。 */
    authFor(tenant) {
      const token = tenant === "a" ? tokenA : tokenB;
      assert.equal(typeof token, "string", `夹具缺 ${tenant} 租户令牌`);
      return { authorization: `Bearer ${token}` };
    },

    /** 各族在两租户下的真实资源 id。 */
    resourceId(family, tenant) {
      const bag = resources[family];
      assert.ok(bag, `夹具未登记资源族 ${family}`);
      const value = bag[tenant];
      assert.equal(typeof value, "string", `夹具缺 ${family} 在租户 ${tenant} 的资源 id`);
      return value;
    },

    /**
     * POST case 的契约合法最小请求体。
     *
     * `model_provider:read` 是**绑定** op（`BindCredentialRequestSchema` 要求
     * `credential_id` 非空）：空体会被 schema 挡成 422，根本到不了跨租户 scoped
     * 查找 —— 那是「请求不合法的红」，不是 I-1 的红。这里回显 **A 租户自己的**
     * credential id：请求语义仍是「A 令牌打 B 的 provider」，且 bind 的检查顺序是
     * 先 provider 后 credential（T2-07 实测对齐 py），故 provider 不可见必先折
     * 404 `NOT_FOUND{provider_id}`，不会借道凭据检查。
     */
    postPayload(caseId) {
      if (caseId === "model_provider:read") {
        return { credential_id: resources.model_credential.a };
      }
      return {};
    },

    /**
     * 副作用快照：快照表全量行（按 id 排序，可 `assert.deepEqual`）。
     * 查库直接读（绕开 HTTP），保证「写类 case 前后零变化」是**数据面**证据。
     */
    async snapshot() {
      const snap = {};
      for (const table of SNAPSHOT_TABLES) {
        snap[table] = sqlite.raw.prepare(`SELECT * FROM "${table}" ORDER BY id ASC`).all();
      }
      return snap;
    },

    /** 释放实例与连接（幂等；进程收尾用）。 */
    async close() {
      await appA.close().catch(() => {});
      await appB.close().catch(() => {});
      sqlite.close();
    },
  };
}

/**
 * 真实注册 → 登录链：register（自动登录）之后**再**走一次 login，取 login 签发的
 * access_token —— 保证夹具令牌的签发路径与生产用户完全一致。
 *
 * @param app 已 ready 的 Fastify 实例。
 * @param username 用户名（租户内唯一）。
 * @param email 邮箱（租户内唯一）。
 * @returns access token 明文。
 */
async function registerAndLogin(app, username, email) {
  const registered = await app.inject({
    method: "POST",
    url: "/api/v1/auth/register",
    payload: { username, email, password: PASSWORD, display_name: username },
  });
  assert.equal(
    registered.statusCode,
    201,
    `register 夹具期望 201，实得 ${registered.statusCode} :: ${registered.body.slice(0, 300)}`,
  );

  const login = await app.inject({
    method: "POST",
    url: "/api/v1/auth/login",
    payload: { username, password: PASSWORD },
  });
  assert.equal(
    login.statusCode,
    200,
    `login 夹具期望 200，实得 ${login.statusCode} :: ${login.body.slice(0, 300)}`,
  );

  const body = login.json();
  const token = body?.data?.access_token;
  assert.equal(typeof token, "string", `login 夹具必须回 access_token :: ${login.body.slice(0, 300)}`);
  return token;
}
