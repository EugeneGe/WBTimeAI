/**
 * T2-03 · 11 张身份表持久化的行为证明（`node:test` + `node:sqlite` 真库）。
 *
 * 驱动与既有 `scoped-repo.test.mjs` 同源：`node --experimental-sqlite` + Node 22 内置
 * `DatabaseSync`，经 drizzle 的 `sqlite-proxy` 跑**真 SQL**。本文件额外多证一件事：
 * 连接走的是生产代码里的 {@link createSqliteDb}（`src/connection.ts`），不是测试自拼的
 * 一次性代理 —— 否则「连接工厂能编译」就只是编译期幻觉。
 *
 * 覆盖的判据面：
 *   1. **I-1 语义**：两个租户夹具，A 看不见 B 的行（含"把 B 的 id 包成 A 的 ScopedRef"）；
 *   2. **三个白名单通道**：`permission` / `role_permission` / `login_attempt` 无 scope 可用，
 *      且第 4 张表想开 unscoped 通道会在**构造时**被拒；
 *   3. `session` / `refresh_token` / `login_attempt` 的写入与查询（含撤销幂等、哈希规约）；
 *   4. RBAC 三层合流的取数路径（`membership.role_id` → `role_permission` → `permission.code`）；
 *   5. `resource_permission` 的**纯函数**判决（`DENY` 优先于 `ALLOW`、无显式 `ALLOW` 默认拒绝）。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  ADMIN_PERMISSION,
  LoginAttemptSink,
  MembershipRepo,
  OrganizationRepo,
  PermissionCatalog,
  RefreshTokenRepo,
  ResourcePermissionRepo,
  RolePermissionCatalog,
  RoleRepo,
  Scope,
  ScopeError,
  SessionRepo,
  TenantRepo,
  UnscopedTableRepo,
  UserRepo,
  assertSha256Hex,
  countConsecutiveFailures,
  decideResourcePermission,
} from "../dist/repositories/index.js";
import { sqlite as sqliteSchema } from "../dist/schema/index.js";
import { createSqliteDb } from "../dist/connection.js";

const DDL_PATH = fileURLToPath(new URL("../../../output/ddl.sqlite.sql", import.meta.url));
const DDL = readFileSync(DDL_PATH, "utf8");

const DIALECT = "sqlite";

/** 灌整份 SQLite DDL 建内存库（顺带证明 DDL 可执行 + 连接工厂可用）。 */
function freshDb() {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  return connection;
}

// ---------------------------------------------------------------------------
// 夹具：两个租户，各自一套 user / organization / role / membership
// ---------------------------------------------------------------------------

const T_A = "11111111-1111-4111-8111-111111111111";
const T_B = "22222222-2222-4222-8222-222222222222";

const U_ALICE = "aaaaaaaa-0000-4000-8000-000000000001";
const U_BOB = "bbbbbbbb-0000-4000-8000-000000000002";

const ORG_A = "0a0a0a0a-0000-4000-8000-00000000000a";
const ORG_B = "0b0b0b0b-0000-4000-8000-00000000000b";

const ROLE_A_ADMIN = "raaaaaaa-0000-4000-8000-00000000000a";
const ROLE_A_GUEST = "ragggggg-0000-4000-8000-00000000000g";
const ROLE_B_OWNER = "rbbbbbbb-0000-4000-8000-00000000000b";

const PERM_IMPORT = "p0000001-0000-4000-8000-000000000001";
const PERM_EXPORT = "p0000002-0000-4000-8000-000000000002";
const PERM_STAR = "p0000003-0000-4000-8000-000000000003";

const SESSION_ALICE_ACTIVE = "50000000-0000-4000-8000-00000000000a";
const SESSION_ALICE_EXPIRED = "50000000-0000-4000-8000-00000000000e";
const SESSION_ALICE_REVOKED = "50000000-0000-4000-8000-00000000000f";
const SESSION_BOB = "50000000-0000-4000-8000-00000000000b";

const FUTURE = "2099-01-01 00:00:00";
const PAST = "2000-01-01 00:00:00";

/** 用原生句柄灌夹具（绕过仓储：夹具是"库里已有的数据"，不是被测行为）。 */
function seed(raw) {
  const insertTenant = raw.prepare(
    "INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, ?)"
  );
  insertTenant.run(T_A, "租户 A", "tenant-a", 1);
  insertTenant.run(T_B, "租户 B", "tenant-b", 1);

  const insertUser = raw.prepare(
    "INSERT INTO user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser) " +
      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
  );
  insertUser.run(U_ALICE, T_A, "alice", "alice@a.example", "$argon2id$v=19$m=65536,t=3,p=4$fake", "Alice", 1, 1);
  insertUser.run(U_BOB, T_B, "bob", "bob@b.example", "$argon2id$v=19$m=65536,t=3,p=4$fake", "Bob", 1, 0);

  const insertOrg = raw.prepare(
    "INSERT INTO organization (id, tenant_id, name, slug) VALUES (?, ?, ?, ?)"
  );
  insertOrg.run(ORG_A, T_A, "组织 A", "org-a");
  insertOrg.run(ORG_B, T_B, "组织 B", "org-b");

  const insertRole = raw.prepare(
    "INSERT INTO role (id, tenant_id, name, description, is_system) VALUES (?, ?, ?, ?, ?)"
  );
  insertRole.run(ROLE_A_ADMIN, T_A, "admin", "租户 A 管理员", 1);
  insertRole.run(ROLE_A_GUEST, T_A, "guest", "租户 A 访客", 0);
  insertRole.run(ROLE_B_OWNER, T_B, "owner", "租户 B 所有者", 0);

  const insertPermission = raw.prepare(
    "INSERT INTO permission (id, code, name, description) VALUES (?, ?, ?, ?)"
  );
  insertPermission.run(PERM_IMPORT, "marketplace:import", "市场导入", null);
  insertPermission.run(PERM_EXPORT, "marketplace:export", "市场导出", null);
  insertPermission.run(PERM_STAR, ADMIN_PERMISSION, "通配权限", "ADMIN_PERMISSION");

  const insertRolePermission = raw.prepare(
    "INSERT INTO role_permission (id, role_id, permission_id) VALUES (?, ?, ?)"
  );
  insertRolePermission.run("rp-1", ROLE_A_ADMIN, PERM_IMPORT);
  insertRolePermission.run("rp-2", ROLE_A_ADMIN, PERM_STAR);
  insertRolePermission.run("rp-3", ROLE_A_GUEST, PERM_EXPORT);
  insertRolePermission.run("rp-4", ROLE_B_OWNER, PERM_IMPORT);

  const insertMembership = raw.prepare(
    "INSERT INTO membership (id, tenant_id, user_id, organization_id, role_id, status) " +
      "VALUES (?, ?, ?, ?, ?, ?)"
  );
  insertMembership.run("m-1", T_A, U_ALICE, ORG_A, ROLE_A_ADMIN, "ACTIVE");
  insertMembership.run("m-2", T_A, U_ALICE, ORG_A, null, "ACTIVE"); // 无角色也要出现在 listByUser
  insertMembership.run("m-3", T_A, U_ALICE, ORG_A, ROLE_A_GUEST, "SUSPENDED"); // 非 ACTIVE 不授权
  insertMembership.run("m-4", T_B, U_BOB, ORG_B, ROLE_B_OWNER, "ACTIVE");
}

function setup() {
  const connection = freshDb();
  seed(connection.raw);
  return connection;
}

const scopeA = new Scope(T_A);
const scopeB = new Scope(T_B);

// ---------------------------------------------------------------------------
// 1. 连接工厂 + tenant 自作用域
// ---------------------------------------------------------------------------

test("createSqliteDb 建出的库能执行整份 DDL（61 张业务表）", () => {
  const connection = freshDb();
  const names = connection.raw
    .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    .all()
    .map((row) => row.name);
  const business = names.filter((name) => !name.startsWith("sqlite_") && !name.includes("_fts"));
  assert.equal(business.length, 61, `业务表应 61 张，实测 ${business.length}`);
  connection.close();
});

test("tenant 是「自作用域」表：靠 id 列承载 scope，跨租户查不到", async () => {
  const connection = setup();
  const repoA = new TenantRepo(connection.db, scopeA, DIALECT);

  const own = await repoA.findById(scopeA.ref(T_A));
  assert.equal(own?.id, T_A, "本租户行必须查得到");
  assert.equal(
    await repoA.findById(scopeA.ref(T_B)),
    null,
    "把 B 的 id 包成 A 的 ScopedRef 也必须查不到（id 谓词真的进了 WHERE）"
  );
  assert.equal(await repoA.isActive(scopeA.ref(T_A)), true);
  assert.equal(await repoA.isActive(scopeA.ref(T_B)), false, "跨租户 ⇒ 查不到 ⇒ isActive=false");
  connection.close();
});

test("tenant 自作用域插入不注入 tenant_id（该表没有这一列）", async () => {
  const connection = setup();
  // 子类只为把受保护的 insertRow 暴露给测试；不改生产 API（tenant 建档属 bootstrap）
  class WritableTenantRepo extends TenantRepo {
    create(row) {
      return this.insertRow(row);
    }
  }
  const scopeC = new Scope("33333333-3333-4333-8333-333333333333");
  const repo = new WritableTenantRepo(connection.db, scopeC, DIALECT);
  const created = await repo.create({
    id: "33333333-3333-4333-8333-333333333333",
    name: "租户 C",
    slug: "tenant-c",
    is_active: true,
  });
  assert.equal(created.id, "33333333-3333-4333-8333-333333333333");
  assert.equal(Object.hasOwn(created, "tenant_id"), false, "tenant 行不该有 tenant_id 键");
  connection.close();
});

// ---------------------------------------------------------------------------
// 2. I-1：跨租户不可见
// ---------------------------------------------------------------------------

test("I-1 · user：跨租户按 id / username / email 一律查不到", async () => {
  const connection = setup();
  const usersA = new UserRepo(connection.db, scopeA, DIALECT);
  const usersB = new UserRepo(connection.db, scopeB, DIALECT);

  assert.equal((await usersA.findById(scopeA.ref(U_ALICE)))?.username, "alice");
  assert.equal(
    await usersA.findById(scopeA.ref(U_BOB)),
    null,
    "B 的用户 id 在 A 的 scope 下必须查不到"
  );
  assert.equal(await usersA.findByUsername("bob"), null, "跨租户按 username 也必须查不到");
  assert.equal(await usersA.findByEmail("bob@b.example"), null, "跨租户按 email 也必须查不到");
  assert.equal((await usersB.findByUsername("bob"))?.id, U_BOB, "B 自己查得到");
  assert.equal((await usersA.listActive()).length, 1, "A 只看到自己的 1 个启用账号");
  connection.close();
});

test("I-1 · organization / role / membership 同样只在 scope 内可见", async () => {
  const connection = setup();

  const orgsA = new OrganizationRepo(connection.db, scopeA, DIALECT);
  assert.deepEqual((await orgsA.list()).map((row) => row.slug), ["org-a"]);
  assert.equal(await orgsA.findBySlug("org-b"), null);

  const rolesA = new RoleRepo(connection.db, scopeA, DIALECT);
  assert.deepEqual(
    (await rolesA.list()).map((row) => row.name).sort(),
    ["admin", "guest"],
    "A 看不到 B 的 owner 角色"
  );
  assert.equal(
    (await rolesA.listByIds([ROLE_B_OWNER])).length,
    0,
    "即使塞进 B 的 role id，scoped 查询也不返回 —— 这是白名单通道 #2 的前置筛子"
  );
  assert.equal((await rolesA.listByIds([ROLE_A_ADMIN])).length, 1);

  const membershipsA = new MembershipRepo(connection.db, scopeA, DIALECT);
  assert.equal((await membershipsA.listByUser(scopeA.ref(U_ALICE))).length, 3, "含非 ACTIVE 行");
  assert.deepEqual(
    (await membershipsA.listActiveRoleIdsByUser(scopeA.ref(U_ALICE))),
    [ROLE_A_ADMIN],
    "只取 ACTIVE 且 role_id 非空（SUSPENDED 与空角色都被排除）"
  );
  assert.deepEqual(
    await membershipsA.listActiveRoleIdsByUser(scopeA.ref(U_BOB)),
    [],
    "B 的用户 id 在 A 的 scope 下取不到任何角色"
  );
  connection.close();
});

test("禁裸 id：身份族仓储同样拒绝字符串 id（继承 ScopedRepo 的运行时校验）", async () => {
  const connection = setup();
  const repo = new UserRepo(connection.db, scopeA, DIALECT);
  await assert.rejects(() => repo.findById(U_ALICE), ScopeError);
  await assert.rejects(() => repo.update(U_ALICE, { is_active: false }), ScopeError);
  await assert.rejects(
    () => repo.findById(scopeB.ref(U_ALICE)),
    ScopeError,
    "别的 scope 产出的 ScopedRef 也必须拒（纵深防御）"
  );
  connection.close();
});

// ---------------------------------------------------------------------------
// 3. 三个白名单通道
// ---------------------------------------------------------------------------

test("白名单 #1 · permission：无 tenant_id 也能读全平台字典", async () => {
  const connection = setup();
  const catalog = new PermissionCatalog(connection.db, DIALECT);
  const codes = await catalog.listCodes();
  assert.deepEqual(
    [...codes].sort(),
    ["*", "marketplace:export", "marketplace:import"],
    "平台字典不按租户切分，读得到全部 3 条"
  );
  assert.equal((await catalog.findByCode(ADMIN_PERMISSION))?.id, PERM_STAR);
  assert.equal(await catalog.findByCode("nope:nope"), null);
  connection.close();
});

test("白名单 #2 · role_permission：经 role_id 集合取码（三层合流的中间 + 末跳）", async () => {
  const connection = setup();
  const rolesA = new RoleRepo(connection.db, scopeA, DIALECT);
  const rolePermissions = new RolePermissionCatalog(connection.db, DIALECT);

  const roleIdsA = (await rolesA.list()).map((row) => row.id);
  const codesA = await rolePermissions.listCodesByRoleIds(roleIdsA);
  assert.deepEqual(
    [...codesA].sort(),
    ["*", "marketplace:export", "marketplace:import"],
    "A 的 admin+guest 合起来 3 个码"
  );

  // 只取 admin ⇒ 两码（含通配）
  assert.deepEqual(
    [...(await rolePermissions.listCodesByRoleIds([ROLE_A_ADMIN]))].sort(),
    ["*", "marketplace:import"]
  );

  // 空集合 ⇒ 空结果，且不生成 `inArray(col, [])`
  assert.deepEqual(await rolePermissions.listCodesByRoleIds([]), []);

  // 关键：**跨租户 role id 不会经由 scoped 筛子流出**
  assert.deepEqual(await rolesA.listByIds([ROLE_B_OWNER]), []);
  const codesFromB = await rolePermissions.listCodesByRoleIds([ROLE_B_OWNER]);
  assert.deepEqual(codesFromB, ["marketplace:import"], "通道本身无 scope —— 这正是它必须只吃 scoped 筛过的 id 的原因");
  connection.close();
});

test("白名单 #3 · login_attempt：租户未知时也能落库", async () => {
  const connection = setup();
  const sink = new LoginAttemptSink(connection.db, DIALECT);

  const unknownTenant = await sink.record({
    tenantId: null,
    username: "ghost",
    ipAddress: "10.0.0.9",
    success: false,
  });
  assert.equal(unknownTenant.tenant_id, null, "tenant_id 可空");
  assert.equal(unknownTenant.username, "ghost");
  assert.equal(unknownTenant.success, false);
  assert.ok(unknownTenant.id, "id 由 sink 生成（DDL 无默认值）");
  assert.equal(typeof unknownTenant.created_at, "string", "SQLite 档时间为文本");

  const anonymous = await sink.record({ success: false });
  assert.equal(anonymous.username, null, "连用户名都可以没有（请求体没带）");
  assert.equal(anonymous.tenant_id, null);

  // `record` 是同步方法：入参非法**当场**抛（不返回 rejected promise —— 那是异步形状）
  assert.throws(() => sink.record({ success: "yes" }), TypeError, "success 必须是布尔");
  assert.throws(() => sink.recentFailures(""), TypeError, "空 username 必须拒绝");
  connection.close();
});

test("白名单闸门：第 4 张表想开 unscoped 通道 ⇒ 构造时抛 ScopeError", () => {
  const connection = setup();
  class RogueRepo extends UnscopedTableRepo {
    constructor(table, purpose) {
      super(connection.db, table, purpose);
    }
  }
  assert.throws(
    () => new RogueRepo(sqliteSchema.user, "我想省点事"),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /不在 unscoped 白名单内/);
      assert.match(error.message, /permission \/ role_permission \/ login_attempt/);
      return true;
    },
    "user 表没有 scope 就构造不出仓储 —— 白名单只此三处"
  );
  // 白名单表但没写理由 ⇒ 也拒（逼着在调用点写清"为什么它可以没有 scope"）
  assert.throws(
    () => new RogueRepo(sqliteSchema.permission, "   "),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /必须写明理由/);
      return true;
    }
  );
  connection.close();
});

// ---------------------------------------------------------------------------
// 4. session / refresh_token
// ---------------------------------------------------------------------------

test("session：写入、有效会话筛选、撤销幂等、全端退出", async () => {
  const connection = setup();
  const sessions = new SessionRepo(connection.db, scopeA, DIALECT);

  await sessions.create({
    id: SESSION_ALICE_ACTIVE,
    user_id: U_ALICE,
    device: "MacBook",
    ip_address: "10.0.0.1",
    user_agent: "Mozilla/5.0",
    expires_at: FUTURE,
    revoked_at: null,
  });
  await sessions.create({
    id: SESSION_ALICE_EXPIRED,
    user_id: U_ALICE,
    expires_at: PAST,
    revoked_at: null,
  });
  await sessions.create({
    id: SESSION_ALICE_REVOKED,
    user_id: U_ALICE,
    expires_at: FUTURE,
    revoked_at: "2026-01-01 00:00:00",
  });

  assert.equal((await sessions.listByUser(scopeA.ref(U_ALICE))).length, 3, "devices 列表含已撤销行");
  assert.deepEqual(
    (await sessions.listActiveByUser(scopeA.ref(U_ALICE))).map((row) => row.id),
    [SESSION_ALICE_ACTIVE],
    "只有「未撤销且未过期」的那条算有效"
  );
  assert.equal(await sessions.isActive(scopeA.ref(SESSION_ALICE_EXPIRED)), false, "过期 ⇒ 无效");

  // 撤销幂等：第一次返回 true，第二次返回 false，两次都不抛
  assert.equal(await sessions.revoke(scopeA.ref(SESSION_ALICE_ACTIVE)), true);
  assert.equal(
    await sessions.revoke(scopeA.ref(SESSION_ALICE_ACTIVE)),
    false,
    "重复撤销不抛错、也不改写已有 revoked_at"
  );
  assert.deepEqual(await sessions.listActiveByUser(scopeA.ref(U_ALICE)), []);

  // 全端退出：数「由未撤销变已撤销」的行 —— 含过期但未撤销的那条（登出要一并作废）
  await sessions.create({
    id: "50000000-0000-4000-8000-0000000000c1",
    user_id: U_ALICE,
    expires_at: FUTURE,
    revoked_at: null,
  });
  assert.equal(
    await sessions.revokeAllByUser(scopeA.ref(U_ALICE)),
    2,
    "已过期未撤销 + 新建未撤销 = 2 行被改写（已撤销行不被重复计数）"
  );

  // 跨租户：B 的 scope 构造的 ref 拿不到 A 的会话 —— 纵深防御在**进 WHERE 之前**就拒
  await assert.rejects(
    () => sessions.revoke(scopeB.ref(SESSION_ALICE_ACTIVE)),
    ScopeError,
    "跨 scope 的 ScopedRef 必须当场拒绝"
  );
  // 同 scope 里不存在的 id ⇒ 幂等返回 false（登出必须幂等，不抛错）
  assert.equal(
    await sessions.revoke(scopeA.ref("50000000-0000-4000-8000-0000000000ff")),
    false,
    "撤销一条不存在的会话返回 false，不抛错"
  );
  connection.close();
});

test("refresh_token：只存 sha256 hex，明文入参当场被拒；按 session 连带撤销", async () => {
  const connection = setup();
  const sessions = new SessionRepo(connection.db, scopeA, DIALECT);
  const tokens = new RefreshTokenRepo(connection.db, scopeA, DIALECT);

  await sessions.create({
    id: SESSION_ALICE_ACTIVE,
    user_id: U_ALICE,
    expires_at: FUTURE,
    revoked_at: null,
  });

  const plaintext = "refresh-plaintext-0123456789";
  const tokenHash = createHash("sha256").update(plaintext).digest("hex");

  // 明文（或截断的 hash）形状不符 ⇒ 直接拒，绝不让它落库
  assert.throws(() => assertSha256Hex(plaintext), ScopeError, "明文必须被拒");
  // `create` 是同步方法（哈希校验先于 insert），故用 assert.throws
  assert.throws(
    () => tokens.create({ id: "rt-bad", user_id: U_ALICE, token_hash: plaintext, expires_at: FUTURE }),
    ScopeError,
    "create 会校验 token_hash 形状"
  );
  await assert.rejects(() => tokens.findByTokenHash("deadbeef"), ScopeError, "查询也校验形状");

  await tokens.create({
    id: "rt-1",
    user_id: U_ALICE,
    session_id: SESSION_ALICE_ACTIVE,
    token_hash: tokenHash,
    expires_at: FUTURE,
    revoked_at: null,
  });
  await tokens.create({
    id: "rt-2",
    user_id: U_ALICE,
    session_id: SESSION_ALICE_ACTIVE,
    token_hash: createHash("sha256").update("second").digest("hex"),
    expires_at: PAST,
    revoked_at: null,
  });

  assert.equal((await tokens.findByTokenHash(tokenHash))?.id, "rt-1");
  assert.equal((await tokens.findActiveByTokenHash(tokenHash))?.id, "rt-1", "未撤销未过期 ⇒ 有效");
  assert.deepEqual((await tokens.listBySession(scopeA.ref(SESSION_ALICE_ACTIVE))).length, 2);

  const revoked = await tokens.revokeBySession(scopeA.ref(SESSION_ALICE_ACTIVE));
  assert.equal(revoked, 2, "连带撤销该 session 名下全部 refresh");
  assert.equal(
    await tokens.findActiveByTokenHash(tokenHash),
    null,
    "撤销后二次使用 ⇒ 查不到（API 层折 401 AUTH_TOKEN_REVOKED，且不区分「已撤销/不存在」）"
  );
  assert.ok(await tokens.findByTokenHash(tokenHash), "行仍在（不物理删除），只是 revoked_at 非空");
  connection.close();
});

// ---------------------------------------------------------------------------
// 5. login_attempt 限速取数
// ---------------------------------------------------------------------------

test("login_attempt：连续失败计数被成功打断（§3.4 的唯一数据源）", async () => {
  const connection = setup();
  const sink = new LoginAttemptSink(connection.db, DIALECT);

  for (let index = 0; index < 5; index += 1) {
    await sink.record({ tenantId: T_A, username: "alice", ipAddress: "10.0.0.1", success: false });
  }
  // 20 条窗口内、且最近一次是失败 ⇒ 连续 5 次
  const beforeSuccess = await sink.recentAttempts("alice", 20);
  assert.equal(beforeSuccess.length, 5);
  assert.equal(countConsecutiveFailures(beforeSuccess), 5, "连续 5 次失败应数成 5");

  await sink.record({ tenantId: T_A, username: "alice", success: true });
  await sink.record({ tenantId: T_A, username: "alice", success: false });
  await sink.record({ tenantId: T_A, username: "alice", success: false });

  const afterSuccess = await sink.recentAttempts("alice", 20);
  assert.equal(afterSuccess.length, 8);
  assert.equal(afterSuccess[0].success, false, "新的在前");
  assert.equal(
    countConsecutiveFailures(afterSuccess),
    2,
    "成功尝试打断连续计数 —— 只数成功之后的那 2 次"
  );

  const failures = await sink.recentFailures("alice", 20);
  assert.equal(failures.length, 7, "recentFailures 只返回失败行");
  assert.equal(failures.every((row) => row.success === false), true);
  assert.equal(await sink.countSuccesses("alice"), 1);

  // 纯函数边界
  assert.equal(countConsecutiveFailures([]), 0);
  assert.equal(countConsecutiveFailures([{ success: true }]), 0);
  assert.equal(countConsecutiveFailures([{ success: false }, { success: false }]), 2);
  connection.close();
});

// ---------------------------------------------------------------------------
// 6. resource_permission 判决
// ---------------------------------------------------------------------------

test("resource_permission：DENY 优先于 ALLOW，无显式 ALLOW 默认拒绝", async () => {
  const connection = setup();
  const repo = new ResourcePermissionRepo(connection.db, scopeA, DIALECT);
  const subject = { subjectType: "user", subjectId: U_ALICE, resourceType: "TOOL", action: "EXECUTE" };

  // 类型级 ALLOW（resource_id NULL）
  const typeAllow = await repo.create({
    id: "resperm-type-allow",
    subject_type: "user",
    subject_id: U_ALICE,
    resource_type: "TOOL",
    resource_id: null,
    action: "EXECUTE",
    effect: "ALLOW",
    scope: { level: "type" },
  });
  // 实例级 DENY（tool-1）
  const instanceDeny = await repo.create({
    id: "resperm-inst-deny",
    subject_type: "user",
    subject_id: U_ALICE,
    resource_type: "TOOL",
    resource_id: "tool-1",
    action: "EXECUTE",
    effect: "DENY",
    scope: { level: "instance" },
  });

  // ① 实例有 DENY ⇒ 即便类型级有 ALLOW，也必须拒
  const forTool1 = await repo.listApplicable({ ...subject, resourceId: "tool-1" });
  assert.equal(forTool1.length, 2, "实例级 + 类型级都适用");
  const decisionTool1 = decideResourcePermission(forTool1, { ...subject, resourceId: "tool-1" });
  assert.deepEqual(decisionTool1, {
    allowed: false,
    effect: "DENY",
    matchedId: instanceDeny.id,
  });

  // ② 实例无行 ⇒ 只剩类型级 ALLOW
  const forTool2 = await repo.listApplicable({ ...subject, resourceId: "tool-2" });
  assert.equal(forTool2.length, 1);
  assert.deepEqual(decideResourcePermission(forTool2, { ...subject, resourceId: "tool-2" }), {
    allowed: true,
    effect: "ALLOW",
    matchedId: typeAllow.id,
  });

  // ③ 没有任何适用行 ⇒ 默认拒绝，且不回显任何 id
  const forRead = await repo.listApplicable({ ...subject, action: "READ", resourceId: null });
  assert.deepEqual(forRead, []);
  assert.deepEqual(decideResourcePermission(forRead, { ...subject, action: "READ", resourceId: null }), {
    allowed: false,
    effect: "DENY",
    matchedId: null,
  });

  // ④ 跨租户：B 的 scope 取不到 A 的判决行
  const repoB = new ResourcePermissionRepo(connection.db, scopeB, DIALECT);
  assert.deepEqual(await repoB.listApplicable({ ...subject, resourceId: "tool-1" }), []);
  connection.close();
});

// ---------------------------------------------------------------------------
// 7. 方言与 limit 规则的共用
// ---------------------------------------------------------------------------

test("limit 规则与 ScopedRepo 同源：白名单通道的非法 limit 同样拒绝", async () => {
  const connection = setup();
  const catalog = new PermissionCatalog(connection.db, DIALECT);
  await assert.rejects(() => catalog.listAll({ limit: 0 }), ScopeError);
  await assert.rejects(() => catalog.listAll({ limit: 501 }), ScopeError);
  assert.equal((await catalog.listAll({ limit: 1 })).length, 1, "边界下界可用");
  connection.close();
});
