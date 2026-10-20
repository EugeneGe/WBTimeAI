/**
 * T1-03 · ScopedRepo 行为证明（node:test + `node:sqlite` 真库）。
 *
 * 驱动选择：**不用 better-sqlite3**（原生模块，本机无 Visual Studio 装不上），
 * 走 Node 22 内置 `node:sqlite` 的 `DatabaseSync`，再由 drizzle 的 `sqlite-proxy`
 * 把查询转交给它 —— 真 SQL、真执行计划，零原生依赖。
 *
 * 这不是"跑一下不报错"的冒烟：
 *   1. 先把 ``output/ddl.sqlite.sql`` **整份灌进** 内存 SQLite —— 顺带证明 SQLite 档 DDL 可执行；
 *   2. 再造两个租户的数据，断言**跨租户不可见**（I-2 的实质判据，而不是"写了 tenant 条件"）；
 *   3. 断言绕过 scope 的三种写法（裸 id / 别人的 ScopedRef / 不传 Scope）全部**当场抛错**。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { DatabaseSync } from "node:sqlite";
import { drizzle } from "drizzle-orm/sqlite-proxy";
import { eq } from "drizzle-orm";

import { sqlite as schema } from "../dist/schema/index.js";
import { Scope, ScopeError, ScopedRepo } from "../dist/repositories/index.js";

const DDL_PATH = fileURLToPath(new URL("../../../output/ddl.sqlite.sql", import.meta.url));
const DDL = readFileSync(DDL_PATH, "utf8");

/** 用真实的 SQLite DDL 建库（61 表 + FTS5 + 触发器），并把 drizzle 架在 node:sqlite 上。 */
function freshDb() {
  const raw = new DatabaseSync(":memory:");
  raw.exec("PRAGMA foreign_keys = OFF"); // 夹具不建父行，只为验 scope 语义
  raw.exec(DDL);
  const db = drizzle(async (sql, params, method) => {
    const stmt = raw.prepare(sql);
    if (method === "run") {
      stmt.run(...params);
      return { rows: [] };
    }
    const rows = stmt.all(...params);
    // sqlite-proxy 要求行是**按列位置**的数组
    return { rows: rows.map((row) => Object.values(row)) };
  });
  return { raw, db };
}

/** 测试用仓储：方言无关的 ScopedRepo 基类 + sqlite 的 task 表。 */
class SqliteTaskRepo extends ScopedRepo {
  constructor(db, scope) {
    super(db, schema.task, scope);
  }

  create(row) {
    return this.insertRow(row);
  }

  list(options = {}) {
    return this.findManyWhere(undefined, options);
  }

  findByIdempotencyKey(key) {
    return this.findOneWhere(eq(schema.task.idempotency_key, key));
  }
}

function taskRow(overrides = {}) {
  return {
    id: `t-${Math.random().toString(36).slice(2, 10)}`,
    type: "generic",
    status: "pending",
    priority: "normal",
    execution_mode: "async",
    ...overrides,
  };
}

test("SQLite 档 DDL 可执行，且建出 61 张业务表", () => {
  const { raw } = freshDb();
  const names = raw
    .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    .all()
    .map((r) => r.name);
  const business = names.filter((n) => !n.startsWith("sqlite_") && !n.includes("_fts"));
  assert.equal(business.length, 61, `业务表应 61 张，实测 ${business.length}`);
  assert.ok(names.includes("document_chunk_fts"), "FTS5 虚表应由 DDL 建出");
  raw.close();
});

test("scope 隔离：A 租户看不见 B 租户的数据行", async () => {
  const { db } = freshDb();
  const a = new Scope("tenant-a");
  const b = new Scope("tenant-b");
  const repoA = new SqliteTaskRepo(db, a);
  const repoB = new SqliteTaskRepo(db, b);

  const createdByA = await repoA.create(taskRow({ id: "task-a1" }));
  const createdByB = await repoB.create(taskRow({ id: "task-b1" }));
  assert.equal(createdByA.tenant_id, "tenant-a", "tenant_id 必须由 scope 注入");
  assert.equal(createdByB.tenant_id, "tenant-b");

  assert.ok(await repoA.findById(a.ref("task-a1")), "本租户的行必须查得到");
  assert.equal(
    await repoA.findById(a.ref("task-b1")),
    null,
    "把 B 的 id 包成 A 的 ScopedRef 也必须查不到（租户条件真的进了 WHERE）"
  );
  assert.equal((await repoA.list()).length, 1);
  assert.equal((await repoB.list()).length, 1);
});

test("workspace 口径：scope 带 workspace 时只看该工作区", async () => {
  const { db } = freshDb();
  const wide = new Scope("tenant-w");
  await new SqliteTaskRepo(db, wide).create(taskRow({ id: "w-null" }));
  // workspace_id 由 scope 注入，故用两个带 workspace 的 scope 各写一行
  const ws1 = new Scope("tenant-w", "ws-1");
  const ws2 = new Scope("tenant-w", "ws-2");
  await new SqliteTaskRepo(db, ws1).create(taskRow({ id: "w-1" }));
  await new SqliteTaskRepo(db, ws2).create(taskRow({ id: "w-2" }));

  const rows = await new SqliteTaskRepo(db, ws1).list();
  assert.deepEqual(
    rows.map((r) => r.id),
    ["w-1"],
    "带 workspace 的 scope 只能看到本工作区行（w-null 的 workspace_id 为 null，也应被过滤掉）"
  );
});

test("禁裸 id：传字符串而不是 ScopedRef 运行时直接拒绝", async () => {
  const { db } = freshDb();
  const repo = new SqliteTaskRepo(db, new Scope("tenant-x"));
  await assert.rejects(() => repo.findById("task-x1"), ScopeError);
  await assert.rejects(() => repo.update("task-x1", { status: "running" }), ScopeError);
  await assert.rejects(() => repo.remove("task-x1"), ScopeError);
});

test("跨 scope 的 ScopedRef 被拒绝（纵深防御）", async () => {
  const { db } = freshDb();
  const a = new Scope("tenant-a");
  const other = new Scope("tenant-other");
  const repoA = new SqliteTaskRepo(db, a);
  await repoA.create(taskRow({ id: "task-a2" }));
  await assert.rejects(() => repoA.findById(other.ref("task-a2")), ScopeError);
});

test("没有 Scope 就构造不出仓储", () => {
  const { db } = freshDb();
  assert.throws(() => new SqliteTaskRepo(db, undefined), ScopeError);
  assert.throws(() => new SqliteTaskRepo(db, "tenant-a"), ScopeError);
  assert.throws(() => new Scope(""), ScopeError, "空 tenantId 必须拒绝");
});

test("tenant_id 由 scope 注入，patch 不可改租户列", async () => {
  const { db } = freshDb();
  const scope = new Scope("tenant-t");
  const repo = new SqliteTaskRepo(db, scope);
  await repo.create(taskRow({ id: "task-t1" }));
  await assert.rejects(() => repo.update(scope.ref("task-t1"), { tenant_id: "evil" }), ScopeError);
  const updated = await repo.update(scope.ref("task-t1"), { status: "running" });
  assert.equal(updated?.status, "running");
  assert.equal(updated?.tenant_id, "tenant-t");
});

test("无 tenant_id 的表（agent_event）禁止直接建仓储", () => {
  const { db } = freshDb();
  class BadRepo extends ScopedRepo {
    constructor() {
      super(db, schema.agent_event, new Scope("tenant-z"));
    }
  }
  assert.throws(() => new BadRepo(), ScopeError, "子表必须经父表 scope 查询，不得直接建仓储");
});
