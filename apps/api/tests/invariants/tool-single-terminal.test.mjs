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

import { finalTurn, makeRunApp, TENANT_ID, toolTurn } from "./_harness.mjs";

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

// COUNTEREXAMPLE: 删掉 `ToolCallRepo.markTerminal` 里的
// `if (isTerminalToolCallStatus(current.status)) return current;`（幂等短路）
// ⇒ S-2 的 `overwritten.status` 变成 FAILED、`output` 变成 `{tampered:true}` ⇒ S-2 红。
// 复跑：改 `packages/db/src/repositories/tool-call-repo.ts` 后
//       `pnpm --filter @wbtime/db build && cd apps/api && node --experimental-sqlite --test tests/invariants/tool-single-terminal.test.mjs`
//
// COUNTEREXAMPLE: 把 `ToolCallRepo.markRunning` 的 `options.allowRevive !== true` 判断
// 改成恒 true（"重试时允许复活"）⇒ S-3 的 `revived` 变成一行且状态 RUNNING ⇒ S-3 红。
