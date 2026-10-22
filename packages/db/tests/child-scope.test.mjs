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
  ConversationRepo,
  MessageRepo,
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

test("首次使用：父在**库里不存在** ⇒ 插入抛 ScopeError 且该行不落库（parentExists 不得恒真）", async () => {
  const { connection, db, scopeA } = seed();
  // 这个 ref 构造期**合法**：由 scopeA.ref() 产出、owns() 能过 —— 挡不住"库里没有这行"。
  // 能拦住的只有基类的首次使用校验（`parentExists`）：
  // 把它改成 `() => true`，本用例前半段必红（外键报的是另一种 Error，不是 ScopeError）。
  const missingConv = "aaaa0000-0000-4000-8000-00000000dead";
  const repo = new MessageRepo(db, scopeA, scopeA.ref(missingConv), DIALECT);

  await assert.rejects(
    () => repo.append({ role: "user", content: "orphan" }),
    (error) => {
      assert.ok(error instanceof ScopeError, `必须是 ScopeError，实测 ${String(error)}`);
      assert.match(error.message, /父 conversation .* 在本 scope 下不可见/);
      return true;
    },
  );

  // 只断言"抛了错"不够：`parentExists` 恒真时外键也会报错（所以前半段已红），
  // 但若哪天外键被关掉（迁移/初始化顺序），就只剩这一条能证明"没有半条孤儿行落库"。
  const total = connection.raw.prepare("select count(*) as n from message").get();
  assert.equal(Number(total.n), 0, "父不可见时一行都不许落库（出现行说明校验发生在写之后）");
  const orphan = connection.raw
    .prepare("select count(*) as n from message where conversation_id = ?")
    .get(missingConv);
  assert.equal(Number(orphan.n), 0, "不得出现挂在不存在会话下的孤儿行");

  // 对照路径：同一张表换成真实存在的父会话就能写进去 ⇒ 上面的 0 不是"写不进去"。
  const real = new MessageRepo(db, scopeA, scopeA.ref(IDS.convA), DIALECT);
  const written = await real.append({ role: "user", content: "real" });
  assert.equal(written.conversation_id, IDS.convA, "对照路径必须成功，否则 0 行无意义");
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

test("父谓词恒在：message.listByRun 不越出会话域（同租户两会话共用同一 run_id）", async () => {
  const { connection, db, scopeA } = seed();

  // 同一租户 A 下的第二个会话：与 convA 共用 workspace / agent / user ⇒ 租户谓词拦不住
  // 会话之间的串流，能拦住的**只有**父谓词（`conversation_id`）。
  const convA2 = "aaaa0000-0000-4000-8000-0000000000a2";
  const conversations = new ConversationRepo(db, scopeA, DIALECT);
  await conversations.create({
    id: convA2,
    workspaceId: IDS.wsA,
    agentId: IDS.agentA,
    userId: IDS.userA,
    title: "conv-a2",
  });

  const runRef = scopeA.ref(IDS.runA);
  const inConvA = new MessageRepo(db, scopeA, scopeA.ref(IDS.convA), DIALECT);
  const inConvA2 = new MessageRepo(db, scopeA, scopeA.ref(convA2), DIALECT);

  // 两个会话各插一条，**run_id 相同**（runA 归属 convA；message.run_id 没有
  // "必须等于所在会话的 run" 的约束 ⇒ 库里可以造出这种数据，正是要挡的形态）。
  const mine = await inConvA.append({ role: "user", content: "in convA", runId: IDS.runA });
  const theirs = await inConvA2.append({ role: "user", content: "in convA2", runId: IDS.runA });
  assert.notEqual(mine.id, theirs.id);

  // 对照路径：库里确实有 **2** 条同 run_id 的消息（证明下面的"只回 1 条"是过滤掉的，
  // 不是另一条根本没插进去）。
  const raw = connection.raw
    .prepare("select count(*) as n from message where run_id = ?")
    .get(IDS.runA);
  assert.equal(Number(raw.n), 2, "夹具必须真的造出跨会话同 run_id 的两行");

  const listedFromA = await inConvA.listByRun(runRef);
  assert.equal(listedFromA.length, 1, "listByRun 必须只回本会话那条（摘掉父谓词就会变 2）");
  assert.equal(listedFromA[0].id, mine.id);
  assert.equal(listedFromA[0].conversation_id, IDS.convA);

  // 反向对照：另一个会话查同一个 run 也只回自己那条 ⇒ 谓词不是"碰巧只剩一条"。
  const listedFromA2 = await inConvA2.listByRun(runRef);
  assert.deepEqual(
    listedFromA2.map((row) => row.id),
    [theirs.id],
    "会话 A2 查同一 run 只应看到自己那条",
  );
});

test("首次使用：**父存在但属于另一租户** ⇒ 读写两条路径都抛 ScopeError，且一行都不许漏进去", async (t) => {
  const { connection, db, scopeA } = seed();

  /** convB（**租户 B** 的会话）名下现有多少条消息 —— 实测，不硬写。 */
  const countConvB = () =>
    Number(
      connection.raw
        .prepare("select count(*) as n from message where conversation_id = ?")
        .get(IDS.convB).n,
    );

  const BEFORE = countConvB();
  assert.equal(BEFORE, 0, "夹具前提：convB 名下初始没有消息（若 seedParents 变了，改这里而不是改下面的期望）");

  // ---------------------------------------------------------------------
  // 攻击形态：**A 铸造 ref、id 指向 B 的行**
  // ---------------------------------------------------------------------
  // `Scope#ref(id)` 接受**任意**字符串，只把 tenantId 盖成本 scope 的。所以
  // `owns()` 证明的是「这个 ref 由本 scope 铸造」（mint provenance），
  // **不是**「这个 id 的行属于本租户」（row ownership）。两者都能被下面这个 ref 满足。
  const forged = scopeA.ref(IDS.convB);
  assert.ok(scopeA.owns(forged), "owns() 只校验铸造来源 —— 这一格它恒放行，不是安全边界");

  // 构造**必须放行**：把 gate ③ 的表达边界钉死。指望 `owns()` 挡住跨租户父是错的。
  const repo = new MessageRepo(db, scopeA, forged, DIALECT);

  // ---------------------------------------------------------------------
  // 两条路径都要探，且**不能用 assert.rejects 前置**：若 append 真的写成功了，
  // assert.rejects 会先抛，后面的行数断言根本执行不到，证据就丢了。
  // 这里把三处观测都收集起来，最后一次断言 —— 漏写 / 漏读 / 漏行 三项证据同时可见。
  // ---------------------------------------------------------------------
  /** 执行 thunk 并把「抛了什么」变成数据，不让异常打断后续观测。 */
  const probe = async (thunk) => {
    try {
      await thunk();
      return { threw: false, error: undefined, value: undefined };
    } catch (error) {
      return { threw: true, error, value: undefined };
    }
  };

  const write = await probe(() => repo.append({ role: "user", content: "LEAK-W" }));
  const read = await probe(() => repo.list());
  const AFTER = countConvB();

  /** 「父在本 scope 下不可见」的原文判据（与基类 `#checkParent` 的文案同锚）。 */
  const isParentInvisible = (outcome) =>
    outcome.threw &&
    outcome.error instanceof ScopeError &&
    /父 conversation .* 在本 scope 下不可见/.test(outcome.error.message);

  /** 收集问题而不是逐条 assert：一次红要把三处证据全部打印出来。 */
  const problems = [];
  if (!write.threw) {
    problems.push("写路径：append 成功了 —— 消息被写进**别的租户**的会话");
  } else if (!isParentInvisible(write)) {
    problems.push(`写路径：抛的不是预期的 ScopeError，实测 ${String(write.error)}`);
  }
  if (!read.threw) {
    problems.push("读路径：list 成功了 —— 跨租户读泄漏（这个洞是读写双漏）");
  } else if (!isParentInvisible(read)) {
    problems.push(`读路径：抛的不是预期的 ScopeError，实测 ${String(read.error)}`);
  }
  if (AFTER !== BEFORE) {
    problems.push(
      `行数：convB 名下 message 从 ${BEFORE} 变成 ${AFTER} —— 有 ${AFTER - BEFORE} 行漏进去了`,
    );
  }
  assert.deepEqual(problems, [], `伪造父引用必须被兜住，实测问题：\n  - ${problems.join("\n  - ")}`);

  // ---------------------------------------------------------------------
  // 对照路径：同租户的父可写可读 ⇒ 上面的"拒"不是"这张表根本写不进去"
  // ---------------------------------------------------------------------
  const ok = new MessageRepo(db, scopeA, scopeA.ref(IDS.convA), DIALECT);
  const written = await ok.append({ role: "user", content: "OK" });
  assert.equal(written.conversation_id, IDS.convA, "对照路径必须成功，否则上面的拒毫无判别力");
  assert.equal((await ok.list()).length, 1, "对照路径读得到自己刚写的那条");
  assert.equal(countConvB(), BEFORE, "对照路径不得顺手往 convB 写东西（夹具自检）");

  t.diagnostic(
    `forged=${IDS.convB} owns=${String(scopeA.owns(forged))} write.threw=${String(
      write.threw,
    )} read.threw=${String(read.threw)} convB ${BEFORE}→${AFTER}`,
  );
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

// ---------------------------------------------------------------------------
// `append({ runId })` 的 run 归属校验（第三入口：写路径）
//
// 背景：`message.run_id` 是**可空** FK。外键只保证"这个 run 行存在"，**不保证**
// 「它属于本租户」—— 跨租户引用是 FK 唯一管不到的那一格，也是本条校验要补的。
//
// ⚠️ 边界画在**租户级**，不画在会话级（这条边界是判据，不是实现细节）：
//   · 跨租户 run      ⇒ 必须拒（越权）
//   · 同租户、跨会话   ⇒ **必须放行**（合法形态：契约没声明"必须等于所在会话的 run"，
//     应用层加严就是契约外扩展、会破坏 TS 与 py 的行为等价；读侧由父谓词兜住）
// 两条一正一负合起来才把边界写死：只写负向，收窄时会顺手把合法形态也禁掉；
// 只写正向，放宽时什么都不会红。
//   反向验证 1：去掉 scoped `findById`（换成不过租户的直查）⇒ 跨租户那条红、正向仍绿；
//   反向验证 2：把校验收紧成「run.conversation_id === 父会话」⇒ 正向那条红。
// ---------------------------------------------------------------------------

/** 某会话名下现有多少条消息（实测值，夹具自检用）。 */
function countMessages(connection, conversationId) {
  return Number(
    connection.raw
      .prepare("select count(*) as n from message where conversation_id = ?")
      .get(conversationId).n,
  );
}

test("append({runId})：**跨租户 run** ⇒ ScopeError「本 scope 下不可见」，且该行不落库", async () => {
  const { connection, db, scopeA } = seed();
  const messages = new MessageRepo(db, scopeA, scopeA.ref(IDS.convA), DIALECT);

  const BEFORE = countMessages(connection, IDS.convA);

  // `IDS.runB` 是**租户 B** 的 run，在库里**真实存在** ⇒ 外键会放行。
  // 也就是说这一格上 FK 不是屏障，能挡住的只有 scoped `findById`。
  const outcome = await (async () => {
    try {
      return { threw: false, row: await messages.append({ role: "tool", content: "X", runId: IDS.runB }) };
    } catch (error) {
      return { threw: true, error };
    }
  })();
  const AFTER = countMessages(connection, IDS.convA);

  // 三处观测一起断言：不落库的证据不能依赖「抛错断言先通过」。
  const problems = [];
  if (!outcome.threw) {
    problems.push(`append 成功了（行 ${String(outcome.row?.id)} 落进 convA）—— 别的租户的 run 被挂上来了`);
  } else if (!(outcome.error instanceof ScopeError)) {
    problems.push(`抛的不是 ScopeError，实测 ${String(outcome.error)}`);
  } else if (!/run .* 在本 scope 下不可见/.test(outcome.error.message)) {
    problems.push(`错误文案不是「run 在本 scope 下不可见」，实测：${outcome.error.message}`);
  }
  if (AFTER !== BEFORE) {
    problems.push(`convA 下 message 从 ${BEFORE} 变成 ${AFTER} —— 有 ${AFTER - BEFORE} 行漏进去了`);
  }
  assert.deepEqual(problems, [], `跨租户 run 必须被拒：\n  - ${problems.join("\n  - ")}`);

  // 对照路径：同一个仓储、换成**本会话**的 runA ⇒ 成功（证明拒的不是"这张表写不进去"）
  const ok = await messages.append({ role: "tool", content: "OK", runId: IDS.runA });
  assert.equal(ok.run_id, IDS.runA);
  assert.equal(countMessages(connection, IDS.convA), BEFORE + 1);
});

test("append({runId})：**同租户、另一个会话的 run** ⇒ **必须成功**（边界只拦跨租户，不拦跨会话）", async () => {
  const { connection, db, scopeA } = seed();

  // 租户 A 下的第二个会话。`runA` 的 `conversation_id` 是 **convA**，不是 convA2 ——
  // 这一格必须放行：
  //   · 契约（双档 DDL 只有存在性 FK）**没声明**"必须等于所在会话的 run"，应用层加严
  //     就是契约外扩展、会破坏 TS 与 py 的行为等价；
  //   · 读侧串不了会话（`listByRun` 恒 and `conversation_id`），写侧无需重复拦。
  const convA2 = "aaaa0000-0000-4000-8000-0000000000a2";
  const conversations = new ConversationRepo(db, scopeA, DIALECT);
  await conversations.create({
    id: convA2,
    workspaceId: IDS.wsA,
    agentId: IDS.agentA,
    userId: IDS.userA,
    title: "conv-a2",
  });

  const inConvA2 = new MessageRepo(db, scopeA, scopeA.ref(convA2), DIALECT);
  const row = await inConvA2.append({ role: "user", content: "跨会话 run", runId: IDS.runA });

  assert.equal(row.run_id, IDS.runA, "run 是 runA");
  assert.equal(row.conversation_id, convA2, "父列仍是 convA2 —— run 的会话与会话本身**不必**一致");
  assert.equal(countMessages(connection, convA2), 1, "这一行必须真的落库");

  // 这条**正向**断言是判据的另一半：把校验收紧成
  // 「`run.conversation_id` 必须等于父会话 id」时它立刻红（而跨租户那条仍绿），
  // 所以它专门挡"过度约束"，也顺带保住判据①「同租户两会话共用同一 run_id」的夹具。
  // 对照：同一个 run 在**它自己的**会话里当然也能挂。
  const inConvA = new MessageRepo(db, scopeA, scopeA.ref(IDS.convA), DIALECT);
  const alsoOk = await inConvA.append({ role: "user", content: "在自己会话里", runId: IDS.runA });
  assert.equal(alsoOk.run_id, IDS.runA);
  assert.equal(countMessages(connection, IDS.convA), 1);
});

test("append({runId})：**正确的 run**（同租户 + 同会话）⇒ 成功", async () => {
  const { connection, db, scopeA } = seed();
  const messages = new MessageRepo(db, scopeA, scopeA.ref(IDS.convA), DIALECT);

  // runA 的 `conversation_id` 就是 convA（见 fixtures）
  const row = await messages.append({ role: "assistant", content: "同会话 run", runId: IDS.runA });
  assert.equal(row.run_id, IDS.runA);
  assert.equal(row.conversation_id, IDS.convA);
  assert.equal(countMessages(connection, IDS.convA), 1);

  // runA2 同租户、同会话（fixtures 里也是 convA）⇒ 同样可挂
  const row2 = await messages.append({ role: "assistant", content: "第二个 run", runId: IDS.runA2 });
  assert.equal(row2.run_id, IDS.runA2);
  assert.equal(countMessages(connection, IDS.convA), 2);
});

test("append({runId})：`runId` 省略 / 显式 null ⇒ 行为不变（可空是契约允许的）", async () => {
  const { connection, db, scopeA } = seed();
  const messages = new MessageRepo(db, scopeA, scopeA.ref(IDS.convA), DIALECT);

  const omitted = await messages.append({ role: "user", content: "手打输入没有 run" });
  assert.equal(omitted.run_id, null, "省略 runId ⇒ run_id 为 null（不是空串、不是 0）");

  const explicitNull = await messages.append({ role: "user", content: "显式 null", runId: null });
  assert.equal(explicitNull.run_id, null);
  assert.equal(countMessages(connection, IDS.convA), 2, "两条都必须落库（空 run 不受新校验影响）");
});

test("append({runId})：run 可见性**每次都要重查**（同实例先成功后换跨租户 run ⇒ 仍必须抛）", async () => {
  const { connection, db, scopeA } = seed();
  const messages = new MessageRepo(db, scopeA, scopeA.ref(IDS.convA), DIALECT);

  // 第一次：合法 run —— 让实例进入"已经成功查过一次"的状态。
  // 基类 `ensureParent()` 的 `#parentCheck` 就是"查过一次就不再查"的实例级缓存，
  // 父引用构造期固定，那样缓存是对的；但 `runId` **每次 append 都可能不同**，
  // 若把可见性结果也缓存到实例上，第二次换 runId 就会直接跳过校验 —— 典型假绿。
  const first = await messages.append({ role: "user", content: "第一次", runId: IDS.runA });
  assert.equal(first.run_id, IDS.runA, "对照：第一次必须成功（否则后面无从谈'第二次')");
  const BEFORE = countMessages(connection, IDS.convA);

  // 第二次：同一个仓储实例，换成**租户 B** 的 run —— 必须仍然被拒。
  await assert.rejects(
    () => messages.append({ role: "user", content: "第二次", runId: IDS.runB }),
    (error) => {
      assert.ok(error instanceof ScopeError, `必须是 ScopeError，实测 ${String(error)}`);
      assert.match(error.message, /在本 scope 下不可见/);
      return true;
    },
    "同一实例的第二次 append 换了 runId，校验不得被缓存跳过",
  );
  assert.equal(countMessages(connection, IDS.convA), BEFORE, "被拒的第二条不得落库");

  // 第三次：再换一个合法 run（runA2，同会话）—— 证明拒的不是"第二次之后整个实例坏了"。
  const third = await messages.append({ role: "user", content: "第三次", runId: IDS.runA2 });
  assert.equal(third.run_id, IDS.runA2);
  assert.equal(countMessages(connection, IDS.convA), BEFORE + 1);
});
