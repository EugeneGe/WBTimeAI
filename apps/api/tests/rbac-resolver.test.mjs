// T2-05 · RBAC 取数层（三层合流）+ 字典种子的幂等性，跑**真 SQL**（node:sqlite）
//
// 为什么这层必须用真库测：三层合流是「`membership.status = ACTIVE` → `role_id` →
// `role_permission` → `permission.code`」四张表的串联，其中「非 ACTIVE 不授权」和
// 「跨租户查不到」这两条**只存在于 SQL 谓词里**。用 stub 替代仓储，测出来的只是
// 「我自己写的那几个 if」——正是本项目反复出现的「测了个假对象」。
//
// 驱动与 T2-03 的 `identity-repos.test.mjs` 同源：`node --experimental-sqlite` +
// 生产代码里的 `createSqliteDb`（`@wbtime/db/connection` 子路径，刻意不进根出口）。

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { test } from "node:test";

import {
  ADMIN_PERMISSION,
  MembershipRepo,
  PERMISSION_CODES,
  PERMISSION_SEED,
  PermissionCatalog,
  RolePermissionCatalog,
  Scope,
  ScopeError,
  seedPermissions,
} from "@wbtime/db";
import { createSqliteDb } from "@wbtime/db/connection";

import { toErrorOutcome } from "../dist/http/error-handler.js";
import { loadPrincipal, resolvePermissionCodes } from "../dist/modules/rbac/index.js";

/** 仓库根（apps/api/tests → apps/api → apps → 根）。 */
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const DDL = readFileSync(join(ROOT, "output", "ddl.sqlite.sql"), "utf8");
const DIALECT = "sqlite";

const T_A = "11111111-1111-4111-8111-111111111111";
const T_B = "22222222-2222-4222-8222-222222222222";
const U_UTIL = "aaaaaaaa-0000-4000-8000-000000000001";
const U_GHOST = "cccccccc-0000-4000-8000-000000000003";
const ORG_A = "0a0a0a0a-0000-4000-8000-00000000000a";
const ROLE_ADMIN = "r0a0a0a0-0000-4000-8000-00000000000a";
const ROLE_EDITOR = "r0e0e0e0-0000-4000-8000-00000000000e";
const ROLE_SUSPENDED = "r0505050-0000-4000-8000-000000000005";

/** 建内存库 + 灌 DDL（顺带证明 DDL 可执行、连接工厂可用）。 */
function freshConnection() {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  return connection;
}

/** 灌夹具：一个租户 A 的活跃用户 + 一条 ACTIVE 角色 + 一条 SUSPENDED 角色。 */
function setup() {
  const connection = freshConnection();
  const raw = connection.raw;

  raw
    .prepare("INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, ?)")
    .run(T_A, "租户 A", "tenant-a", 1);
  raw
    .prepare("INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, ?)")
    .run(T_B, "租户 B", "tenant-b", 1);

  const insertUser = raw.prepare(
    "INSERT INTO user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser) " +
      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
  );
  insertUser.run(U_UTIL, T_A, "util", "util@a.example", "$argon2id$v=19$m=65536,t=3,p=4$fake", "Util", 1, 0);
  insertUser.run(U_GHOST, T_A, "ghost", "ghost@a.example", "$argon2id$v=19$m=65536,t=3,p=4$fake", "Ghost", 1, 0);

  raw
    .prepare("INSERT INTO organization (id, tenant_id, name, slug) VALUES (?, ?, ?, ?)")
    .run(ORG_A, T_A, "组织 A", "org-a");

  const insertRole = raw.prepare(
    "INSERT INTO role (id, tenant_id, name, description, is_system) VALUES (?, ?, ?, ?, ?)",
  );
  insertRole.run(ROLE_ADMIN, T_A, "admin", "租户 A 管理员", 1);
  insertRole.run(ROLE_EDITOR, T_A, "editor", "租户 A 编辑", 0);
  insertRole.run(ROLE_SUSPENDED, T_A, "suspended-role", "已停用成员的角色", 0);

  const insertMembership = raw.prepare(
    "INSERT INTO membership (id, tenant_id, user_id, organization_id, role_id, status) " +
      "VALUES (?, ?, ?, ?, ?, ?)",
  );
  insertMembership.run("m-admin", T_A, U_UTIL, ORG_A, ROLE_ADMIN, "ACTIVE");
  insertMembership.run("m-editor", T_A, U_UTIL, ORG_A, ROLE_EDITOR, "ACTIVE");
  // 同一用户还有一条 SUSPENDED 成员关系，挂着第三个角色 —— 它的码**不得**被解析出来
  insertMembership.run("m-suspended", T_A, U_UTIL, ORG_A, ROLE_SUSPENDED, "SUSPENDED");

  return connection;
}

/** 让某个角色持有某权限码（经字典行 id 串起来）。 */
async function grant(connection, roleId, code) {
  const catalog = new PermissionCatalog(connection.db, DIALECT);
  const permission = await catalog.findByCode(code);
  assert.ok(permission !== null, `字典里没有 ${code}（种子没跑？）`);
  connection.raw
    .prepare("INSERT INTO role_permission (id, role_id, permission_id) VALUES (?, ?, ?)")
    .run(`rp-${roleId}-${permission.id}`, roleId, permission.id);
}

const resolverOf = (connection) => ({
  memberships: new MembershipRepo(connection.db, new Scope(T_A), DIALECT),
  rolePermissions: new RolePermissionCatalog(connection.db, DIALECT),
});

// ─────────────────────────────────────────────────────────────────────────────
// 字典种子（零 DDL + 幂等）
// ─────────────────────────────────────────────────────────────────────────────

test("种子：6 行 = 5 个具体码 + 1 个通配，且首次执行全部 inserted", async () => {
  const connection = freshConnection();

  assert.equal(PERMISSION_CODES.length, 5, "本版落地 5 个具体权限码");
  assert.equal(PERMISSION_SEED.length, 6, "种子 6 行（5 + 通配）");
  assert.equal(PERMISSION_SEED.at(-1).code, ADMIN_PERMISSION);

  const result = await seedPermissions(connection.db, DIALECT);
  assert.equal(result.total, 6);
  assert.deepEqual([...result.inserted].sort(), [...PERMISSION_SEED.map((row) => row.code)].sort());
  assert.deepEqual(result.skipped, []);

  const catalog = new PermissionCatalog(connection.db, DIALECT);
  assert.equal((await catalog.listCodes()).length, 6, "库里恰好 6 行");
  connection.close();
});

test("种子幂等：重复执行不产生第二行（inserted=[] / skipped=6）", async () => {
  const connection = freshConnection();

  const first = await seedPermissions(connection.db, DIALECT);
  const second = await seedPermissions(connection.db, DIALECT);
  const third = await seedPermissions(connection.db, DIALECT);

  assert.equal(first.inserted.length, 6);
  assert.deepEqual(second.inserted, [], "第二次不得插入任何行");
  assert.equal(second.skipped.length, 6, "第二次全部 skipped");
  assert.deepEqual(third.inserted, [], "第三次仍然不插入");

  const catalog = new PermissionCatalog(connection.db, DIALECT);
  const codes = await catalog.listCodes();
  assert.equal(codes.length, 6, "跑三次仍是 6 行 —— 唯一索引没被绕过");
  assert.equal(new Set(codes).size, 6, "码无重复");
  connection.close();
});

test("种子零 DDL：执行前后表清单完全不变", async () => {
  const connection = freshConnection();
  const listTables = () =>
    connection.raw
      .prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
      .all()
      .map((row) => row.name);

  const before = listTables();
  await seedPermissions(connection.db, DIALECT);
  const after = listTables();

  assert.deepEqual(after, before, "种子只写数据行，不得建表/改结构");
  assert.ok(before.length > 50, `表清单过短（${before.length}），疑似 DDL 没灌进去`);
  connection.close();
});

// ─────────────────────────────────────────────────────────────────────────────
// 三层合流（真 SQL）
// ─────────────────────────────────────────────────────────────────────────────

test("三层合流：ACTIVE 成员关系的角色码被解析出来（含通配）", async () => {
  const connection = setup();
  await seedPermissions(connection.db, DIALECT);
  await grant(connection, ROLE_ADMIN, ADMIN_PERMISSION);
  await grant(connection, ROLE_ADMIN, "marketplace:import");
  await grant(connection, ROLE_EDITOR, "evaluation:read");

  const deps = resolverOf(connection);
  const codes = await resolvePermissionCodes(deps, new Scope(T_A).ref(U_UTIL));

  assert.deepEqual([...codes].sort(), ["*", "evaluation:read", "marketplace:import"]);
  connection.close();
});

test("非 ACTIVE 成员关系不授予权限（SUSPENDED 角色的码不出现）", async () => {
  const connection = setup();
  await seedPermissions(connection.db, DIALECT);
  // 唯一给 suspended 角色的码：evaluation:run —— 它绝不能出现在结果里
  await grant(connection, ROLE_SUSPENDED, "evaluation:run");
  await grant(connection, ROLE_EDITOR, "evaluation:read");

  const deps = resolverOf(connection);
  const codes = await resolvePermissionCodes(deps, new Scope(T_A).ref(U_UTIL));

  assert.deepEqual([...codes], ["evaluation:read"], "只有 ACTIVE 角色的码");
  assert.equal(codes.includes("evaluation:run"), false, "SUSPENDED 成员关系的码必须被 SQL 谓词挡掉");
  connection.close();
});

test("无成员关系 ⇒ 空码集（不是抛错、不是隐性放行）", async () => {
  const connection = setup();
  await seedPermissions(connection.db, DIALECT);
  await grant(connection, ROLE_ADMIN, ADMIN_PERMISSION);

  const deps = resolverOf(connection);
  const codes = await resolvePermissionCodes(deps, new Scope(T_A).ref(U_GHOST));
  assert.deepEqual([...codes], []);
  connection.close();
});

test("跨租户：用 B 的 scope 查 A 的用户 ⇒ 空码集（I-1 在取数层的表现）", async () => {
  const connection = setup();
  await seedPermissions(connection.db, DIALECT);
  await grant(connection, ROLE_ADMIN, ADMIN_PERMISSION);

  const scopeB = new Scope(T_B);
  const deps = {
    memberships: new MembershipRepo(connection.db, scopeB, DIALECT),
    rolePermissions: new RolePermissionCatalog(connection.db, DIALECT),
  };
  // 把 A 的用户 id 包成 B 的引用：类型层允许（都是 ScopedRef），但 SQL 谓词会把它挡掉
  const codes = await resolvePermissionCodes(deps, scopeB.ref(U_UTIL));
  assert.deepEqual([...codes], [], "跨租户查不到 ⇒ 空码集 ⇒ 后续任何需要权限的动作都会被拒");
  connection.close();
});

test("多角色授同一个码 ⇒ 结果去重（审计计数不失真）", async () => {
  const connection = setup();
  await seedPermissions(connection.db, DIALECT);
  await grant(connection, ROLE_ADMIN, "evaluation:read");
  await grant(connection, ROLE_EDITOR, "evaluation:read");

  const deps = resolverOf(connection);
  const codes = await resolvePermissionCodes(deps, new Scope(T_A).ref(U_UTIL));
  assert.deepEqual([...codes], ["evaluation:read"], "同一码只出现一次");
  connection.close();
});

// ─────────────────────────────────────────────────────────────────────────────
// loadPrincipal：取数 + 组装（认证层 T2-04 的接缝）
// ─────────────────────────────────────────────────────────────────────────────

test("loadPrincipal：一次取数即得到注入守卫用的 Principal", async () => {
  const connection = setup();
  await seedPermissions(connection.db, DIALECT);
  await grant(connection, ROLE_ADMIN, "evaluation:run");

  const deps = resolverOf(connection);
  const scopeA = new Scope(T_A);
  const principal = await loadPrincipal(deps, {
    userRef: scopeA.ref(U_UTIL),
    userId: U_UTIL,
    tenantId: T_A,
    organizationIds: [ORG_A],
  });

  assert.equal(principal.userId, U_UTIL);
  assert.equal(principal.tenantId, T_A);
  assert.deepEqual([...principal.permissionCodes], ["evaluation:run"]);
  assert.deepEqual([...principal.organizationIds], [ORG_A]);
  assert.equal(Object.isFrozen(principal), true, "Principal 必须冻结");
  connection.close();
});

test("loadPrincipal：userRef 的租户与 Principal 租户不一致 ⇒ 当场拒绝", async () => {
  const connection = setup();
  await seedPermissions(connection.db, DIALECT);
  const deps = resolverOf(connection);
  const scopeB = new Scope(T_B);

  await assert.rejects(
    () =>
      loadPrincipal(deps, {
        userRef: scopeB.ref(U_UTIL),
        userId: U_UTIL,
        tenantId: T_A, // 与 ref 的租户不一致
      }),
    ScopeError,
    "把 scope 拆成两半的调用必须在入口处失败",
  );
  connection.close();
});

test("不变量：ScopeError 落到「未捕获 ⇒ 500」，绝不能被当成域错误（422）", () => {
  // 这是 `error-handler.ts` ① 分支那条注释的**可执行版本**：
  // `asDomainError` 是鸭子类型（带契约码即认），而 `ScopeError` 刻意只有 `name` + `message`。
  // 一旦有人给 `ScopeError` 加一个契约码（哪怕 VALIDATION_ERROR），本用例立刻红 ——
  // 否则「编程错误不该被 try/catch 吞掉」这条语义会在无声中消失。
  const scopeError = new ScopeError("findById 只收 ScopedRef，不接受裸 id");
  assert.equal(
    Object.hasOwn(scopeError, "code"),
    false,
    "ScopeError 不得带 code 字段（带了就会被 ① 分支吃成 422）",
  );

  const outcome = toErrorOutcome(scopeError, "rid-scope");
  assert.equal(outcome.status, 500, "编程错误必须是 500，不能伪装成用户错误");
  assert.equal(outcome.origin, "unhandled");
  assert.equal(outcome.body.code, "INTERNAL_ERROR");
  assert.equal(outcome.body.request_id, "rid-scope");
});
