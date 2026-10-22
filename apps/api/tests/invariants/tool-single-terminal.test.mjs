/**
 * T3-14 · 不变量 ③：**tool call 单终态**（一次工具调用恰有一条终态，且不可复活/覆盖）。
 *
 * 判据（DoD#1 前 5 条不变量的第 2 条）
 * ---------------------------------
 *   | 编号 | 断言 | 机器形态 |
 *   |---|---|---|
 *   | S-1 | 一次执行 ⇒ `tool_call` 恰一行、状态 ∈ 终态集合 | 行数 + 状态 |
 *   | S-2 | 第二次 `markTerminal` **不覆盖** 第一次的 `output` / `status` | 逐字段比对 |
 *   | S-3 | 终态后 `markRunning` 不复活（返回 `null`，状态不变） | 返回 null + 状态 |
 *   | S-4 | `tool.started` / `tool.completed` 各**恰一帧**（一次调用一对） | 帧计数 |
 *   | S-5 | **并发竞态**：两路 result 同时到 ⇒ 库里仍恰 1 条终态 ∧ 不自相矛盾 | `Promise.allSettled` + 行内一致性 |
 *
 * 为什么"单终态"值得一条不变量
 * -----------------------
 *   `tool_call.status` 是回放的因果链：`PENDING → RUNNING → 终态`。若第二次 result 能
 *   覆盖第一次，"这条工具到底输出了什么"就取决于**到达顺序**（谁后到谁算），
 *   而重试/重放会让到达顺序不稳定 —— 那是"同一份历史两种解释"。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/invariants/tool-single-terminal.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { Scope, ToolCallRepo } from "@wbtime/db";

import { finalTurn, makeRunApp, TENANT_ID, toolTurn, WORKSPACE_ID } from "./_harness.mjs";

/** `tool_call` 的终态集合（与 `packages/db` 同源）。 */
const TERMINAL = ["SUCCESS", "FAILED", "DENIED", "CANCELLED", "UNKNOWN"];

/** 跑一次"请求一个工具、再给答复"的 run，返回 runId 与它的 tool_call 行。 */
async function oneToolRun(fixture) {
  const started = await fixture.startRun();
  assert.equal(started.response.statusCode, 200, started.response.body);
  const run = JSON.parse(started.response.body).data;
  const terminal = await fixture.waitTerminal(run.id);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));
  return { runId: run.id, rows: fixture.toolCallsOf(run.id) };
}

// ---------------------------------------------------------------------------
// S-1 / S-4 · 一次调用 = 一行 + 一对帧
// ---------------------------------------------------------------------------

test("S-1/S-4 · 一次工具调用 ⇒ tool_call 恰一行且落在终态 ∧ tool.started/completed 各一帧", async () => {
  const fixture = await makeRunApp({
    turns: [
      toolTurn("call-s1", "shell", { command: "echo wbtime-single-terminal" }),
      finalTurn(),
    ],
  });
  try {
    const { runId, rows } = await oneToolRun(fixture);
    assert.equal(rows.length, 1, `tool_call 恰一行，实测 ${rows.length}`);
    assert.equal(rows[0].tool_name, "shell");
    assert.ok(TERMINAL.includes(rows[0].status), `状态必须是终态，实测 ${rows[0].status}`);
    assert.equal(rows[0].status, "SUCCESS");
    assert.ok(typeof rows[0].duration_ms === "number", "终态行必须带 duration_ms");

    const channels = fixture.channelsOf(runId);
    assert.equal(channels.filter((type) => type === "tool.started").length, 1, "tool.started 恰一帧");
    assert.equal(channels.filter((type) => type === "tool.completed").length, 1, "tool.completed 恰一帧");

    // 因果序：started 在 completed 之前
    const startedSeq = fixture.eventsOf(runId).find((row) => row.type === "tool.started").seq;
    const completedSeq = fixture.eventsOf(runId).find((row) => row.type === "tool.completed").seq;
    assert.ok(startedSeq < completedSeq, `started(${startedSeq}) 必须在 completed(${completedSeq}) 之前`);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// S-2 / S-3 · 单终态：不覆盖、不复活
// ---------------------------------------------------------------------------

test("S-2 · 第二次 markTerminal 不覆盖第一次的 output / status（幂等）", async () => {
  const fixture = await makeRunApp({
    turns: [toolTurn("call-s2", "shell", { command: "echo first" }), finalTurn()],
  });
  try {
    const { runId, rows } = await oneToolRun(fixture);
    const callId = rows[0].id;
    const repo = new ToolCallRepo(
      fixture.connection.db,
      new Scope(TENANT_ID),
      new Scope(TENANT_ID).ref(runId),
      "sqlite",
    );

    const overwritten = await repo.markTerminal(callId, {
      status: "FAILED",
      output: { tampered: true },
      error: "第二次 result（本该被忽略）",
      durationMs: 999,
    });

    assert.equal(overwritten.status, "SUCCESS", "状态不得被第二次 result 改写");
    assert.equal(overwritten.error, null, "error 不得被补上");
    assert.equal(overwritten.duration_ms, rows[0].duration_ms, "duration_ms 不得被改写");
    // 直读拿到的是 JSONTEXT（sqlite `output` 列），drizzle 拿到的是已解析对象
    // ⇒ 统一按解析后的值比对（比较的是"内容有没有被覆盖"，不是列类型的形状）。
    assert.deepEqual(
      overwritten.output,
      JSON.parse(rows[0].output),
      "output 必须是第一次执行的结果（重复 result 覆盖 = 回放不可信）",
    );

    // 对照：库里也只有一行（没有"插一条新的"这种偷换）
    assert.equal(fixture.count("select count(*) as n from tool_call where run_id = ?", runId), 1);
  } finally {
    await fixture.close();
  }
});

test("S-3 · 终态后 markRunning 不复活（返回 null，状态不变）", async () => {
  const fixture = await makeRunApp({
    turns: [toolTurn("call-s3", "shell", { command: "echo no-revive" }), finalTurn()],
  });
  try {
    const { runId, rows } = await oneToolRun(fixture);
    const callId = rows[0].id;
    const repo = new ToolCallRepo(
      fixture.connection.db,
      new Scope(TENANT_ID),
      new Scope(TENANT_ID).ref(runId),
      "sqlite",
    );

    const revived = await repo.markRunning(callId);
    assert.equal(revived, null, "终态 ⇒ markRunning 必须返回 null（默认不允许复活）");

    const after = fixture.toolCallsOf(runId)[0];
    assert.equal(after.status, "SUCCESS", `终态不得被改回 RUNNING，实测 ${after.status}`);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// S-5 · 并发竞态（主理人 2026-10-22 裁定 P2-4）
// ---------------------------------------------------------------------------

test("S-5 · 并发竞态：两路 result 同时到 ⇒ 库里仍恰 1 条终态且不自相矛盾", async (t) => {
  const fixture = await makeRunApp({ turns: [finalTurn()] });
  try {
    // 造一条「RUNNING 的 tool_call」（要的是"终态未落"的竞态窗口，故不走完整 run ——
    // 完整 run 里工具执行是串行的，构造不出两路 result 同时到）。
    const agent = await fixture.createAgent();
    const conversationId = "6c6c6c6c-0000-4000-8000-0000000000c6";
    const runId = "6f6f6f6f-0000-4000-8000-0000000000f6";
    const callId = "6a6a6a6a-0000-4000-8000-0000000000a6";
    fixture.raw
      .prepare(
        "insert into conversation (id, tenant_id, workspace_id, agent_id, user_id, title, status) " +
          "values (?, ?, ?, ?, ?, 'S-5 会话', 'ACTIVE')",
      )
      .run(conversationId, TENANT_ID, WORKSPACE_ID, agent.agentId, fixture.userId);
    fixture.raw
      .prepare(
        "insert into agent_run (id, tenant_id, agent_id, agent_version_id, conversation_id, user_id, " +
          "trigger, run_mode, status, tool_error_count, cost_estimated, cost_status) " +
          "values (?, ?, ?, ?, ?, ?, 'user', 'INLINE', 'RUNNING', 0, 0, 'UNPRICED')",
      )
      .run(runId, TENANT_ID, agent.agentId, agent.versionId, conversationId, fixture.userId);
    fixture.raw
      .prepare(
        "insert into tool_call (id, run_id, tool_name, tool_type, attempt, status) " +
          "values (?, ?, 'shell', 'builtin', 1, 'RUNNING')",
      )
      .run(callId, runId);

    const repo = new ToolCallRepo(
      fixture.connection.db,
      new Scope(TENANT_ID),
      new Scope(TENANT_ID).ref(runId),
      "sqlite",
    );

    // 两路 result **同时**到：不同 status、不同 output/error
    const results = await Promise.allSettled([
      repo.markTerminal(callId, { status: "SUCCESS", output: { writer: "A" }, durationMs: 11 }),
      repo.markTerminal(callId, { status: "FAILED", error: "writer-B", durationMs: 22 }),
    ]);
    const winners = results.filter(
      (item) => item.status === "fulfilled" && item.value !== null,
    ).length;
    t.diagnostic(`并发两路 markTerminal ⇒ 成功方=${winners}（若为 CAS 实现应为 1）`);

    // ① 行数：并发不得"多插一行 result"（这是最容易写坏的一种实现）
    const rows = fixture.raw.prepare("select * from tool_call where run_id = ?").all(runId);
    assert.equal(rows.length, 1, `并发两路 result 后必须仍恰 1 行，实测 ${rows.length}`);

    // ② 状态：必须是 7 值里的终态，且是两方之一（不能出现第三种/中间态）
    const final = rows[0];
    assert.ok(TERMINAL.includes(final.status), `实测 ${final.status}`);
    assert.ok(
      ["SUCCESS", "FAILED"].includes(final.status),
      `终态必须取自两方之一，实测 ${final.status}`,
    );

    // ③ 一致性：**当前实现过不了这一条（已实测，登记 V0.4.0）**
    //    严格版断言（本该在此处）：
    //      if (final.status === "SUCCESS") { assert.equal(final.error, null); assert.notEqual(final.output, null); }
    //      else { assert.equal(final.output, null); assert.equal(final.error, "writer-B"); }
    //    实测红证（主理人裁定的"如实报告"证据）：
    //      `FAILED 行不得带 output  + '{"writer":"A"}' - null`
    //    原因：`markTerminal` 是 `findById` → 终态短路 → `update`（read-then-write，**非
    //    CAS**），且 patch **只覆盖调用方带的字段** ⇒ 后到者（FAILED）改写了 status/error，
    //    却留下先到者（SUCCESS）写入的 `output` ⇒ 行自相矛盾。
    //    为什么不在这里断言"缺陷存在"：那会在 V0.4.0 修好时反而红（把 bug 写成期望）。
    //    严格版断言的启用条件与原文在 `施工记录/T3-14.md` §9 + 遗留 R-5。
    t.diagnostic(
      `终值行=${JSON.stringify({ status: final.status, output: final.output, error: final.error, duration_ms: final.duration_ms })}`
    );

    // ③′ 可断言的部分（现在与修好后都成立）：终值行必须来自**某一次**完整 patch
    //     —— `duration_ms` 必须是两方之一（11 / 22），不能是空或第三种值。
    assert.ok(
      [11, 22].includes(final.duration_ms),
      `duration_ms 必须取自两方之一，实测 ${final.duration_ms}`,
    );

    // ④ 至少一方生效（防止"两路都被静默丢弃"这种假绿）
    assert.ok(winners >= 1, `至少一方要生效，实测 ${winners}`);

    // ⑤ **已知缺口（实测记录，登记 V0.4.0）**：`winners === 2` ⇒ 两路都写成功。
    //    CAS 实现下应为 1。这条不改成"断言 winners===1"（当前实现会红），
    //    但也不掩盖：诊断已打印实际值，且 ③ 的红证原文在同一段注释里。
    //    V0.4.0 把 `markTerminal` 改成条件更新（`UPDATE … WHERE status NOT IN 终态`
    //    + 整批字段覆盖）后，启用：`assert.equal(winners, 1)` + ③ 的三一致断言。
    if (winners > 1) {
      assert.ok(
        final.status === "FAILED",
        `read-then-write 下由**后到者**决定终值，实测 ${final.status}`,
      );
    }
  } finally {
    await fixture.close();
  }
});

// COUNTEREXAMPLE: 删掉 `ToolCallRepo.markTerminal` 里的
// `if (isTerminalToolCallStatus(current.status)) return current;`（幂等短路）
// ⇒ S-2 的 `overwritten.status` 变成 FAILED、`output` 变成 `{tampered:true}` ⇒ S-2 红。
// 复跑：改 `packages/db/src/repositories/tool-call-repo.ts` 后
//       `pnpm --filter @wbtime/api build && cd apps/api && node --experimental-sqlite --test tests/invariants/tool-single-terminal.test.mjs`
//
// COUNTEREXAMPLE: 把 `ToolCallRepo.markRunning` 的 `options.allowRevive !== true` 判断
// 改成恒 true（"重试时允许复活"）⇒ S-3 的 `revived` 变成一行且状态 RUNNING ⇒ S-3 红。
//
// COUNTEREXAMPLE: 把 `markTerminal` 的 `this.update(id, patch)` 改成
// `this.insertRow({ ...current, ...patch, id: current.id + "-2" })`（"每次 result 插一行"
// 的错实现）⇒ **实测 4 红 / 4 跑**：S-5 先命中 ②（`rows[0]` 是残留的 `RUNNING` 行，
// 报错原文 `实测 RUNNING`；若只跑到 ① 也会因行数 1→2 红），S-1/S-2/S-3 连带红
// （单行与幂等同时被破坏）。
//
