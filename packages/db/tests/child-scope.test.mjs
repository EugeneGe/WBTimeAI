/**
 * T3-03 · `ChildScopedRepo` 的行为证明（**R3-22**：父引用强制）。
 *
 * 判据（任务卡验收 ① + R3-22 影响判据 ①②③）：
 *   · `UNSCOPED_WHITELIST` **仍 3 条**（不扩）；
 *   · 跨租户父 ref ⇒ `ScopeError`（**不是**空数组）；
 *   · 父在本 scope 下不可见 ⇒ `ScopeError`（首次使用时）；
 *   · 子表**不暴露**无父参的查询（类型测试单列，见 `tests/typecheck`）；
 *   · 父列只能由基类注入（调用方自带 ⇒ 抛）。
 *
 * 防假绿：每条"查不到"的断言都先断言**对照路径查得到**（证明夹具真的有行），
 * 否则"空"可能只是"没插进去"。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  AgentEventRepo,
  AgentRunRepo,
  ChildConflictError,
  ChildScopedRepo,
  Scope,
  ScopeError,
  UNSCOPED_WHITELIST,
} from "../dist/repositories/index.js";
import { sqlite as sqliteSchema } from "../dist/schema/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A, T_B } from "./fixtures/runtime-fixture.mjs";

/** 建库 + 父链 + 两个 scope。 */
function seed() {
  const connection = freshConnection();
  const db = connection.db;
  seedParents(connection);
  const scopeA = new Scope(T_A);
  const scopeB = new Scope(T_B);
  return { connection, db, scopeA, scopeB };
}

test("UNSCOPED_WHITELIST 仍 3 条（R3-22：不扩通道）", () => {
  assert.deepEqual(Object.keys(UNSCOPED_WHITELIST).sort(), [
    "login_attempt",
    "permission",
    "role_permission",
  ]);
  assert.equal(Object.keys(UNSCOPED_WHITELIST).length, 3);
});

test("构造：跨租户父 ref ⇒ ScopeError（不是空数组）", () => {
  const { db, scopeA, scopeB } = seed();
  // B 的 run 拿去给 A 的 scope 建子仓储 ⇒ 当场抛，绝不能退化成"这个 run 没事件"。
  assert.throws(
    () => new AgentEventRepo(db, scopeA, scopeB.ref(IDS.runB), DIALECT),
    (error) => {
      assert.ok(error instanceof ScopeError, `必须是 ScopeError，实测 ${String(error)}`);
      assert.match(error.message, /agent_event/);
      return true;
    },
  );
});

test("构造：伪造的父 ref（无品牌）⇒ ScopeError", () => {
  const { db, scopeA } = seed();
  assert.throws(
    () => new AgentEventRepo(db, scopeA, { id: IDS.runA, tenantId: T_A }, DIALECT),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /不是本 scope 产出的 ScopedRef/);
      return true;
    },
  );
});

test("构造：带 tenant_id 的表不得用子表基类（分工互斥）", () => {
  const { db, scopeA } = seed();
  class BogusChild extends ChildScopedRepo {
    constructor(database, scope, runRef) {
      super(database, sqliteSchema.agent_run, scope, runRef, {
        parentColumn: "agent_id",
        parentLabel: "agent",
        parentExists: async () => true,
      });
    }
  }
  assert.throws(
    () => new BogusChild(db, scopeA, scopeA.ref(IDS.runA)),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /有 tenant_id 列 ⇒ 应当直接用 ScopedRepo/);
      return true;
    },
  );
});

test("构造：父列不存在 ⇒ ScopeError（接错列会造出孤儿行）", () => {
  const { db, scopeA } = seed();
  class BogusChild extends ChildScopedRepo {
    constructor(database, scope, runRef) {
      super(database, sqliteSchema.agent_event, scope, runRef, {
        parentColumn: "conversation_id",
        parentLabel: "conversation",
        parentExists: async () => true,
      });
    }
  }
  assert.throws(
    () => new BogusChild(db, scopeA, scopeA.ref(IDS.runA)),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /没有父列 conversation_id/);
      return true;
    },
  );
});

test("首次使用：父在本 scope 下不可见 ⇒ ScopeError（R3-22 的属主校验）", async () => {
  const { db, scopeA } = seed();
  // runB 属于租户 B；用 A 的 scope 包它的 id ⇒ owns() 通过（都是 A 的 ref），
  // 但父查询（scoped）查不到 ⇒ 第一次真正查询时抛。
  const repo = new AgentEventRepo(db, scopeA, scopeA.ref(IDS.runB), DIALECT);
  await assert.rejects(
    () => repo.list(),
    (error) => {
      assert.ok(error instanceof ScopeError, `必须是 ScopeError，实测 ${String(error)}`);
      assert.match(error.message, /父 run .* 在本 scope 下不可见/);
      return true;
    },
  );
});

test("父谓词恒在：A 的 run 看不到 B 的 run 的子行", async () => {
  const { db, scopeA, scopeB } = seed();
  const eventsA = new AgentEventRepo(db, scopeA, scopeA.ref(IDS.runA), DIALECT);
  const eventsB = new AgentEventRepo(db, scopeB, scopeB.ref(IDS.runB), DIALECT);

  const inB = await eventsB.append({ type: "agent.started" });
  assert.equal(inB.seq, 1, "对照路径：B 自己的仓储能写入（夹具不是空壳）");

  assert.equal(await eventsA.findById(inB.row.id), null, "A 的仓储按 id 也取不到 B 的事件");
  assert.deepEqual(await eventsA.list(), [], "A 的 run 下没有事件");
  assert.equal((await eventsB.list()).length, 1);
});

test("父谓词恒在：同一租户的另一个 run 也互相隔离", async () => {
  const { db, scopeA } = seed();
  const eventsA1 = new AgentEventRepo(db, scopeA, scopeA.ref(IDS.runA), DIALECT);
  const eventsA2 = new AgentEventRepo(db, scopeA, scopeA.ref(IDS.runA2), DIALECT);

  await eventsA1.append({ type: "agent.started" });
  assert.equal((await eventsA1.list()).length, 1, "对照路径：runA 真的有 1 条");
  assert.deepEqual(await eventsA2.list(), [], "runA2 与 runA 同租户也互不可见（父谓词，不是租户谓词）");
});

test("父列只能由基类注入：插入自带 run_id ⇒ ScopeError", async () => {
  const { db, scopeA } = seed();
  class LeakyChild extends ChildScopedRepo {
    constructor(database, scope, runRef) {
      super(database, sqliteSchema.agent_event, scope, runRef, {
        parentColumn: "run_id",
        parentLabel: "run",
        parentExists: async () => true,
      });
    }
    /** 只为本用例开的出口：基类之外无人能调 insertRow。 */
    insert(row) {
      return this.insertRow(row);
    }
  }
  const repo = new LeakyChild(db, scopeA, scopeA.ref(IDS.runA));
  await assert.rejects(
    () => repo.insert({ id: "x-1", run_id: IDS.runB, seq: 1, type: "agent.started" }),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /插入入参不得自带 run_id/);
      return true;
    },
  );
});

test("父列不可改：patch 带 run_id ⇒ ScopeError", async () => {
  const { db, scopeA } = seed();
  const events = new AgentEventRepo(db, scopeA, scopeA.ref(IDS.runA), DIALECT);
  const first = await events.append({ type: "agent.started" });
  await assert.rejects(
    () => events.update(first.row.id, { run_id: IDS.runA2 }),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /patch 不得包含 id \/ run_id/);
      return true;
    },
  );
});

test("构造缺父 ref ⇒ ScopeError（父是**必填**第 3 参，无默认值）", () => {
  const { db, scopeA } = seed();
  // R3-22：「构造必须传父 ScopedRef」。少传一个参数在 JS 里是 `undefined`，
  // 类型层则直接编译不过（见 `tests/typecheck/no-parent.ts`）—— 两头都锁。
  assert.throws(
    () => new AgentEventRepo(db, scopeA),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /不是本 scope 产出的 ScopedRef/);
      return true;
    },
  );
  assert.ok(
    AgentEventRepo.length >= 3,
    `构造函数至少要有 (db, scope, parentRef) 三个**必填**形参，实测 ${AgentEventRepo.length}`,
  );
});

test("父仓储仍然是 ScopedRepo（agent_run 走租户直挂，不进子表基类）", async () => {
  const { db, scopeA, scopeB } = seed();
  const runsA = new AgentRunRepo(db, scopeA, DIALECT);
  const runsB = new AgentRunRepo(db, scopeB, DIALECT);
  assert.ok(await runsA.findById(scopeA.ref(IDS.runA)), "对照路径：A 的 run 查得到");
  assert.equal(await runsA.findById(scopeA.ref(IDS.runB)), null, "A 查不到 B 的 run");
  assert.equal((await runsA.list()).length, 2);
  assert.equal((await runsB.list()).length, 1);
});

test("导出完整性：ChildConflictError 可用（R3-05 的抛错类型）", () => {
  assert.equal(new ChildConflictError("x").name, "ChildConflictError");
  assert.ok(new ChildConflictError("x") instanceof Error);
});
