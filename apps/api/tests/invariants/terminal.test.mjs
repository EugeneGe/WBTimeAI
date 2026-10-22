/**
 * T3-14 · 不变量 ②：**终态零事件**（run 到终态后，`agent_event` 一行都写不进去）。
 *
 * 判据（DoD#1 前 5 条不变量的第 3 条）
 * ---------------------------------
 *   | 编号 | 断言 | 机器形态 |
 *   |---|---|---|
 *   | T-1 | 终态后 `append()` ⇒ `RunTerminalError`，且**行数不变** | 抛错 + 计数两者都断 |
 *   | T-2 | 终态后 `appendInternal()` ⇒ 同样拒绝（内部行没有豁免） | 同上 |
 *   | T-3 | 终态帧是**最后一帧** | `agent.completed` 的 seq == max(seq) |
 *
 * 为什么"抛错"和"行数不变"要一起断
 * ---------------------------
 *   只断抛错 ⇒ 实现可以先写库再抛（行已经多了一条，前端看到的回放比库少一帧）；
 *   只断行数 ⇒ 实现可以静默丢弃（调用方以为写成功，实际丢事件）。
 *   两条一起断才是"一行不写"。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/invariants/terminal.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { RunEventWriter, RunTerminalError } from "../../dist/modules/run/event-writer.js";
import { finalTurn, makeRunApp, TENANT_ID } from "./_harness.mjs";

/** 建一个已终态（`SUCCEEDED`）的 run，返回其 id + 终态前的事件数。 */
async function succeededRun(fixture) {
  const started = await fixture.startRun();
  assert.equal(started.response.statusCode, 200, started.response.body);
  const run = JSON.parse(started.response.body).data;
  const terminal = await fixture.waitTerminal(run.id);
  assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));
  return { runId: run.id, before: fixture.eventsOf(run.id).length };
}

// ---------------------------------------------------------------------------
// T-1 / T-2 · 终态后零事件
// ---------------------------------------------------------------------------

test("T-1 · 终态后 append(12 帧内的通道) ⇒ RunTerminalError 且 agent_event 行数不变", async () => {
  const fixture = await makeRunApp({ turns: [finalTurn()] });
  try {
    const { runId, before } = await succeededRun(fixture);
    const writer = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId,
    });

    await assert.rejects(
      () => writer.append("message.delta", { message_id: "late", role: "assistant", content: "迟到的帧" }),
      (error) => {
        assert.ok(error instanceof RunTerminalError, `实测 ${String(error)}`);
        assert.equal(error.name, "RunTerminalError");
        assert.equal(error.status, "SUCCEEDED", "错误里要带真实终态，便于排障");
        return true;
      },
      "终态后写事件必须抛 RunTerminalError",
    );

    assert.equal(
      fixture.eventsOf(runId).length,
      before,
      "抛错的同时必须一行都不写（先写后抛同样是错的）",
    );
  } finally {
    await fixture.close();
  }
});

test("T-2 · 终态后 appendInternal（内部行）同样拒绝 —— 内部行没有豁免", async () => {
  const fixture = await makeRunApp({ turns: [finalTurn()] });
  try {
    const { runId, before } = await succeededRun(fixture);
    const writer = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId,
    });

    await assert.rejects(
      () => writer.appendInternal("loop.turn.started", { turn: 99 }),
      (error) => {
        assert.ok(error instanceof RunTerminalError, `实测 ${String(error)}`);
        return true;
      },
    );
    assert.equal(fixture.eventsOf(runId).length, before, "内部行也不得在终态后写入");

    // 对照：同一条内部行在**非终态** run 上完全可写（否则上面的绿可能是"这条永远写不进"）
    const live = await fixture.startRun({ message: "第二条" });
    const liveRun = JSON.parse(live.response.body).data;
    const liveWriter = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId: liveRun.id,
    });
    await fixture.waitTerminal(liveRun.id);
    // （live run 也已终态；这里只断"抛的是终态错误而不是别的错误"，两种 run 同一语义）
    await assert.rejects(() => liveWriter.appendInternal("loop.turn.started", { turn: 1 }));
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// T-3 · 终态帧是最后一帧
// ---------------------------------------------------------------------------

test("T-3 · 终态帧（agent.completed）是 run 的最后一条事件", async () => {
  const fixture = await makeRunApp({ turns: [finalTurn()] });
  try {
    const { runId } = await succeededRun(fixture);
    const events = fixture.eventsOf(runId);
    const last = events[events.length - 1];
    assert.equal(last.type, "agent.completed", `最后一帧实测 ${last.type}`);
    const maxSeq = Math.max(...events.map((row) => row.seq));
    assert.equal(last.seq, maxSeq, "终态帧必须是 seq 最大的一条");
  } finally {
    await fixture.close();
  }
});

// COUNTEREXAMPLE: 删掉 `RunEventWriter.append` 里的
// `if (isTerminalRunStatus(run.status)) throw new RunTerminalError(...)` 三行
// （只保留白名单校验）⇒ T-1 的 `assert.rejects` 变成"没抛" ⇒ T-1 红；
// 同时 `agent_event` 行数 +1 ⇒ T-1 的第二条断言也红（双红）。
// 复跑：改 `apps/api/src/modules/run/event-writer.ts` 后
//       `pnpm --filter @wbtime/api build && cd apps/api && node --experimental-sqlite --test tests/invariants/terminal.test.mjs`
//
// COUNTEREXAMPLE: 把 `appendInternal` 里的终态检查删掉（"内部行不影响前端"是错误直觉）
// ⇒ T-2 的 `assert.rejects` 不抛 ⇒ T-2 红。内部行与下发帧共用同一张表与同一个 seq
// 序列，豁免它就等于给"终态后还能追加"开了一个后门。
