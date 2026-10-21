/**
 * T3-03 · 运行时三仓的行为证明（`node:sqlite` 真库，SQLite 档）。
 *
 * 判据（任务卡验收 ② ③ ⑤）：
 *   ② `tool_call` 四段边界三阶段**幂等**（`attempt` 递增、重复 result 不覆盖）；
 *   ③ `agent_event` 写入返回分配的 `seq`；`(run_id, seq)` 重复 ⇒ **抛错**（R3-05，零 DDL）；
 *   ⑤ SQLite 真库全绿；**PG 入口存在**（缺环境 fail loud，见文件末尾两例）。
 *
 * 反例（注入式，文件内标注 `COUNTEREXAMPLE:`）：
 *   · 手工造两条相同 `(run_id, seq)`（绕过 writer）⇒ 查询级断言必红；
 *   · PG 档入口脚本在无 `WBTIME_PG_URL` 时 **rc≠0**（不 skip、不谎报通过）。
 */

import assert from "node:assert/strict";
import test from "node:test";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  AGENT_RUN_STATUSES,
  AgentEventRepo,
  AgentRunRepo,
  ChildConflictError,
  TERMINAL_TOOL_CALL_STATUSES,
  ToolCallRepo,
  TOOL_CALL_STATUSES,
} from "../dist/repositories/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A, T_B } from "./fixtures/runtime-fixture.mjs";
import { Scope } from "../dist/repositories/index.js";

/** 每例一份新库（不共享状态，避免用例互相污染）。 */
function seed() {
  const connection = freshConnection();
  const db = connection.db;
  seedParents(connection);
  const scopeA = new Scope(T_A);
  return { connection, db, scopeA, runA: scopeA.ref(IDS.runA), runA2: scopeA.ref(IDS.runA2) };
}

// ---------------------------------------------------------------------------
// A · agent_run：lease / CAS 原语 + v0019 stop_reason
// ---------------------------------------------------------------------------

test("夹具自检（防空档）：三个 run 均已落库", async () => {
  const { db, scopeA, runA } = seed();
  const runs = new AgentRunRepo(db, scopeA, DIALECT);
  assert.ok(await runs.findById(runA), "runA 必须存在，否则下面全是空集通过");
  assert.equal((await runs.list()).length, 2, "A 租户有 2 个 run");
});

test("create / findById / list：本租户可见，跨租户不可见", async () => {
  const { db, scopeA } = seed();
  const runsA = new AgentRunRepo(db, scopeA, DIALECT);
  const created = await runsA.create({
    id: "aaaa0000-0000-4000-8000-000000000099",
    tenant_id: T_A, // 类型层禁止；JS 侧显式给出只为证明基类会用 scope 覆盖它
    agent_id: IDS.agentA,
    agent_version_id: IDS.versionA,
    conversation_id: IDS.convA,
    user_id: IDS.userA,
    trigger: "user",
    run_mode: "INLINE",
    status: "QUEUED",
    tool_error_count: 0,
    cost_estimated: false,
    cost_status: "UNPRICED",
  });
  assert.equal(created.tenant_id, T_A);
  assert.equal((await runsA.list()).length, 3);
});

test("v0019：stop_reason 可写（finalize 落终态 + 停止原因）", async () => {
  const { db, scopeA, runA } = seed();
  const runs = new AgentRunRepo(db, scopeA, DIALECT);

  assert.equal((await runs.findById(runA)).stop_reason, null, "初始为 null（不是空串）");

  const finalized = await runs.finalize(runA, {
    status: "SUCCEEDED",
    stopReason: "completed",
    success: true,
    completedAt: new Date("2026-10-22T03:00:00Z"),
    durationMs: 1234,
  });
  assert.equal(finalized.status, "SUCCEEDED");
  assert.equal(finalized.stop_reason, "completed", "v0019 的 stop_reason 双档同型可写");
  assert.equal(finalized.success, true);
  assert.equal(finalized.duration_ms, 1234);
  assert.ok(finalized.completed_at !== null, "completed_at 已落（SQLite 档是文本时间）");
});

test("CAS lease：from 命中才迁移；状态已变 ⇒ null（不覆盖）", async () => {
  const { db, scopeA, runA } = seed();
  const runs = new AgentRunRepo(db, scopeA, DIALECT);

  const first = await runs.tryAcquireLease(runA, { from: ["QUEUED"], to: "RUNNING" });
  assert.ok(first, "第一次应当抢到");
  assert.equal(first.status, "RUNNING");

  // 第二次同参数：状态已是 RUNNING，不在 from 里 ⇒ CAS 影响 0 行 ⇒ null。
  // 这就是「不是先查后写」的证明：先查后写会看到 RUNNING 后仍可能写。
  const second = await runs.tryAcquireLease(runA, { from: ["QUEUED"], to: "RUNNING" });
  assert.equal(second, null, "CAS 未命中 ⇒ null（调用方据此放弃 lease）");
});

test("CAS lease：两个 worker 抢同一个 run ⇒ 恰一方成功", async () => {
  const { db, scopeA, runA } = seed();
  const worker1 = new AgentRunRepo(db, scopeA, DIALECT);
  const worker2 = new AgentRunRepo(db, scopeA, DIALECT);

  const results = await Promise.all([
    worker1.tryAcquireLease(runA, { from: ["QUEUED"], to: "RUNNING" }),
    worker2.tryAcquireLease(runA, { from: ["QUEUED"], to: "RUNNING" }),
  ]);
  const winners = results.filter((row) => row !== null);
  assert.equal(winners.length, 1, "双 worker ⇒ 恰一方拿到 lease（R3-05 ③）");
  assert.equal((await worker1.findById(runA)).status, "RUNNING");
});

test("lease：空 from ⇒ 直接抛（多半是漏填，不该静默永不抢到）", async () => {
  const { db, scopeA, runA } = seed();
  const runs = new AgentRunRepo(db, scopeA, DIALECT);
  await assert.rejects(() => runs.tryAcquireLease(runA, { from: [], to: "RUNNING" }), /源状态/);
});

test("heartbeat：刷新 last_heartbeat_at", async () => {
  const { db, scopeA, runA } = seed();
  const runs = new AgentRunRepo(db, scopeA, DIALECT);
  const beat = await runs.heartbeat(runA, new Date("2026-10-22T03:10:00Z"));
  assert.ok(beat.last_heartbeat_at !== null);
  // SQLite 档是 `YYYY-MM-DD HH:MM:SS` 文本（instantLiteral 的既有口径）
  assert.equal(beat.last_heartbeat_at, "2026-10-22 03:10:00");
});

test("idempotency_key：按幂等键能认出同一个 run（零 DDL 复用既有唯一索引）", async () => {
  const { db, scopeA } = seed();
  const runs = new AgentRunRepo(db, scopeA, DIALECT);
  const found = await runs.findByIdempotencyKey("idem-a-1");
  assert.ok(found);
  assert.equal(found.id, IDS.runA);
  assert.equal(await runs.findByIdempotencyKey("no-such-key"), null);
});

// ---------------------------------------------------------------------------
// B · tool_call：四段事务边界 + 幂等
// ---------------------------------------------------------------------------

test("tool_call 状态：7 值 + 终态集合（R3-03）", () => {
  assert.deepEqual([...TOOL_CALL_STATUSES], [
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "FAILED",
    "DENIED",
    "CANCELLED",
    "UNKNOWN",
  ]);
  assert.equal(TOOL_CALL_STATUSES.length, 7);
  assert.deepEqual([...TERMINAL_TOOL_CALL_STATUSES], [
    "SUCCESS",
    "FAILED",
    "DENIED",
    "CANCELLED",
    "UNKNOWN",
  ]);
});

test("① intent：createPending ⇒ PENDING + attempt=1", async () => {
  const { db, scopeA, runA } = seed();
  const calls = new ToolCallRepo(db, scopeA, runA, DIALECT);
  const created = await calls.createPending({
    id: "cccc0000-0000-4000-8000-000000000001",
    tool_name: "read_file",
    tool_type: "builtin",
    status: "PENDING",
    attempt: 1,
  });
  assert.equal(created.status, "PENDING");
  assert.equal(created.attempt, 1);
  assert.equal(created.run_id, IDS.runA, "父由基类注入");
});

test("③ execute：markRunning 幂等 —— 第二次**不重写任何业务字段**", async () => {
  // 可观测口径（踩过一次才写清楚）：`tool_call` **没有 started_at / updated_at 列**
  // （零 DDL 红线 ⇒ 不能加），所以「第二次有没有真的发一条 UPDATE」在现有列上
  // **不可观测**。能观测、且真正要守的是：重复 execute **不得重置** attempt /
  // output —— 重试计数与结果一旦被 execute 段改写，回放与计费就都不可信了。
  // 下面的 output 用原生 SQL 预置（哨兵值），就是为了把「没被改写」做成可见事实。
  const { connection, db, scopeA, runA } = seed();
  const calls = new ToolCallRepo(db, scopeA, runA, DIALECT);
  const created = await calls.createPending({
    id: "cccc0000-0000-4000-8000-000000000002",
    tool_name: "read_file",
    tool_type: "builtin",
  });
  // 重试两次 ⇒ attempt=3（execute 段不得把它按回 1）
  await calls.incrementAttempt(created.id);
  await calls.incrementAttempt(created.id);

  const first = await calls.markRunning(created.id);
  assert.equal(first.status, "RUNNING");
  assert.equal(first.attempt, 3, "execute 段不改 attempt");

  connection.raw.exec(
    `update tool_call set output = '{"text":"kept-by-first-execute"}' where id = '${created.id}'`,
  );

  const second = await calls.markRunning(created.id);
  assert.equal(second.status, "RUNNING", "仍在 RUNNING（不报错、不回退）");
  assert.equal(second.attempt, 3, "幂等 ⇒ attempt 不被 execute 段重置");
  assert.deepEqual(second.output, { text: "kept-by-first-execute" }, "幂等 ⇒ output 不被清空");
});

test("④ result：markTerminal 写 output；重复 result **不覆盖**", async () => {
  const { db, scopeA, runA } = seed();
  const calls = new ToolCallRepo(db, scopeA, runA, DIALECT);
  const created = await calls.createPending({
    id: "cccc0000-0000-4000-8000-000000000003",
    tool_name: "read_file",
    tool_type: "builtin",
  });
  await calls.markRunning(created.id);

  const done = await calls.markTerminal(created.id, {
    status: "SUCCESS",
    output: { text: "first result" },
    durationMs: 12,
  });
  assert.equal(done.status, "SUCCESS");
  assert.deepEqual(done.output, { text: "first result" });

  const again = await calls.markTerminal(created.id, {
    status: "FAILED",
    output: { text: "second result" },
    durationMs: 99,
  });
  assert.deepEqual(again.output, { text: "first result" }, "重复 result 不覆盖（回放可信的前提）");
  assert.equal(again.status, "SUCCESS", "状态也不被后到的终态改写");
  assert.equal(again.duration_ms, 12);
});

test("attempt 单调递增（incrementAttempt 只增不减）", async () => {
  const { db, scopeA, runA } = seed();
  const calls = new ToolCallRepo(db, scopeA, runA, DIALECT);
  const created = await calls.createPending({
    id: "cccc0000-0000-4000-8000-000000000004",
    tool_name: "http",
    tool_type: "builtin",
  });
  assert.equal(created.attempt, 1);
  const second = await calls.incrementAttempt(created.id);
  assert.equal(second.attempt, 2);
  const third = await calls.incrementAttempt(created.id);
  assert.equal(third.attempt, 3);
});

test("审批/安全拒绝：DENIED 可从 PENDING 直达（四段里唯一合法的跳段）", async () => {
  const { db, scopeA, runA } = seed();
  const calls = new ToolCallRepo(db, scopeA, runA, DIALECT);
  const created = await calls.createPending({
    id: "cccc0000-0000-4000-8000-000000000005",
    tool_name: "shell",
    tool_type: "builtin",
  });
  const denied = await calls.markTerminal(created.id, {
    status: "DENIED",
    error: "safety denied",
  });
  assert.equal(denied.status, "DENIED");
  assert.equal(await calls.markRunning(created.id), null, "终态不可复活（Harness §1-5）");
});

test("非法 status ⇒ 抛（写脏状态比不写更糟）", async () => {
  const { db, scopeA, runA } = seed();
  const calls = new ToolCallRepo(db, scopeA, runA, DIALECT);
  const created = await calls.createPending({
    id: "cccc0000-0000-4000-8000-000000000006",
    tool_name: "read_file",
    tool_type: "builtin",
  });
  await assert.rejects(
    () => calls.markTerminal(created.id, { status: "MAYBE" }),
    /非法的 tool_call.status/,
  );
});

test("父谓词恒在：另一个 run 的工具调用不可见", async () => {
  const { db, scopeA, runA, runA2 } = seed();
  const callsA = new ToolCallRepo(db, scopeA, runA, DIALECT);
  const callsA2 = new ToolCallRepo(db, scopeA, runA2, DIALECT);
  const created = await callsA.createPending({
    id: "cccc0000-0000-4000-8000-000000000007",
    tool_name: "read_file",
    tool_type: "builtin",
  });
  assert.equal(await callsA2.findById(created.id), null);
  assert.equal((await callsA.list()).length, 1, "对照路径：runA 真的有 1 条");
  assert.deepEqual(await callsA2.list(), []);
});

// ---------------------------------------------------------------------------
// C · agent_event：seq 分配 + 重复检测（R3-05）
// ---------------------------------------------------------------------------

test("append 返回分配的 seq，且严格 1..N 递增", async () => {
  const { db, scopeA, runA } = seed();
  const events = new AgentEventRepo(db, scopeA, runA, DIALECT);
  const a = await events.append({ type: "agent.started" });
  const b = await events.append({ type: "agent.thinking", payload: { turn: 1 } });
  const c = await events.append({ type: "agent.completed" });
  assert.deepEqual(
    [a.seq, b.seq, c.seq],
    [1, 2, 3],
    "seq = max(seq)+1 ⇒ 写入方拿得到号（SSE 的 id: 要用）",
  );
  assert.equal(a.row.seq, a.seq, "返回行里的 seq 与外送的 seq 同源");
});

test("list 按 seq 升序（回放次序 == 写入次序）", async () => {
  const { db, scopeA, runA } = seed();
  const events = new AgentEventRepo(db, scopeA, runA, DIALECT);
  await events.append({ type: "agent.started" });
  await events.append({ type: "agent.thinking" });
  await events.append({ type: "agent.completed" });
  const rows = await events.list();
  assert.deepEqual(
    rows.map((row) => row.seq),
    [1, 2, 3],
  );
});

test("(run_id, seq) 重复 ⇒ 抛 ChildConflictError（R3-05：零 DDL 的应用层护栏）", async () => {
  const { db, scopeA, runA } = seed();
  const events = new AgentEventRepo(db, scopeA, runA, DIALECT);
  await events.append({ type: "agent.started" }); // seq=1
  await assert.rejects(
    () => events.appendAt(1, { type: "duplicate" }),
    (error) => {
      assert.ok(error instanceof ChildConflictError, `必须是 ChildConflictError，实测 ${String(error)}`);
      assert.match(error.message, /\(run_id=.*, seq=1\) 已存在/);
      return true;
    },
  );
  assert.equal((await events.list()).length, 1, "抛错后没有留下第二行（不是先写再报）");
});

test("appendAt 的 seq 必须 ≥1 的整数", async () => {
  const { db, scopeA, runA } = seed();
  const events = new AgentEventRepo(db, scopeA, runA, DIALECT);
  await assert.rejects(() => events.appendAt(0, { type: "x" }), /≥1 的整数/);
  await assert.rejects(() => events.appendAt(1.5, { type: "x" }), /≥1 的整数/);
});

test("跨 run 的 seq 各自编号（seq 是 run 内序号，不是全局）", async () => {
  const { db, scopeA, runA, runA2 } = seed();
  const eventsA = new AgentEventRepo(db, scopeA, runA, DIALECT);
  const eventsA2 = new AgentEventRepo(db, scopeA, runA2, DIALECT);
  assert.equal((await eventsA.append({ type: "agent.started" })).seq, 1);
  assert.equal((await eventsA.append({ type: "agent.thinking" })).seq, 2);
  assert.equal((await eventsA2.append({ type: "agent.started" })).seq, 1, "另一个 run 从 1 起");
});

test("listAfter：续读原语（只给区间，不含 gap 语义）", async () => {
  const { db, scopeA, runA } = seed();
  const events = new AgentEventRepo(db, scopeA, runA, DIALECT);
  for (const type of ["agent.started", "agent.thinking", "agent.completed"]) {
    await events.append({ type });
  }
  const after = await events.listAfter(1);
  assert.deepEqual(
    after.map((row) => row.seq),
    [2, 3],
  );
});

test("查询级不变量：本 run 内无重复 seq", async () => {
  const { db, scopeA, runA } = seed();
  const events = new AgentEventRepo(db, scopeA, runA, DIALECT);
  await events.append({ type: "agent.started" });
  await events.append({ type: "agent.completed" });
  assert.deepEqual(await events.findDuplicateSeq(), []);
});

test("COUNTEREXAMPLE: 手工造重复 seq（绕过 writer）⇒ 查询级断言必红", async () => {
  const { connection, db, scopeA, runA } = seed();
  const events = new AgentEventRepo(db, scopeA, runA, DIALECT);
  await events.appendAt(1, { type: "agent.started" });
  // 直接灌一条同 (run_id, seq) 的行 —— 模拟"另一个写者没走仓储"的最坏情况。
  connection.raw.exec(
    `insert into agent_event (id, run_id, seq, type, payload, trace_id, span_id, created_at) values ` +
      `('dddd0000-0000-4000-8000-000000000001', '${IDS.runA}', 1, 'ghost', null, null, null, '2026-10-22 00:00:00')`,
  );
  const duplicates = await events.findDuplicateSeq();
  assert.equal(duplicates.length, 1, "注入的重复必须被查询级断言抓到（否则该断言是空转）");
  assert.equal(duplicates[0].seq, 1);
});

// ---------------------------------------------------------------------------
// D · PG 档入口（R3-20：fail loud，不 skip）
// ---------------------------------------------------------------------------

const PG_ENTRY = fileURLToPath(new URL("./runtime-pg.mjs", import.meta.url));

test("PG 档入口存在（同一组断言文件，不另立一套）", () => {
  assert.ok(existsSync(PG_ENTRY), `PG 入口脚本必须存在：${PG_ENTRY}`);
});

test("PG 档入口：缺 WBTIME_PG_URL ⇒ exit≠0 + 明确提示（fail loud，不是 skip）", () => {
  // 清空 PG 相关 env 后跑入口脚本：R3-20 要求**非 0 退出 + 明确提示**，
  // 禁止"没环境就 exit 0"（那会把"没验证"伪装成"验证过"）。
  const env = { ...process.env };
  delete env.WBTIME_PG_URL;
  delete env.WBTIME_DATABASE_URL;

  const result = spawnSync(process.execPath, [PG_ENTRY], { encoding: "utf8", env });
  assert.equal(result.error, undefined, `无法启动入口脚本：${String(result.error)}`);
  assert.notEqual(result.status, 0, "缺 PG 环境时入口脚本必须非 0 退出（fail loud）");
  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  assert.match(output, /WBTIME_PG_URL/, "提示必须点名缺失的环境变量");
  assert.match(output, /未验证|依赖不可得|fail loud/i, "提示必须写明「未验证」，不得含糊");
});

test("PG 档构造入口存在：仓储可按 pg 档构造（生产档是 pg）", () => {
  const { db, scopeA, runA } = seed();
  // 缺省 dialect 即 "pg" ⇒ 入口不是"只有 SQLite 能构造"。
  const runs = new AgentRunRepo(db, scopeA);
  assert.equal(runs.tableName, "agent_run");
  const events = new AgentEventRepo(db, scopeA, runA);
  assert.equal(events.tableName, "agent_event");
  const calls = new ToolCallRepo(db, scopeA, runA);
  assert.equal(calls.tableName, "tool_call");
});

test("run 状态常量：7 值（v0019）", () => {
  assert.deepEqual([...AGENT_RUN_STATUSES], [
    "QUEUED",
    "RUNNING",
    "WAITING_APPROVAL",
    "WAITING_INPUT",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
  ]);
  assert.equal(AGENT_RUN_STATUSES.length, 7);
});
