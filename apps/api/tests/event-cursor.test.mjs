/**
 * T3-08 · 事件游标（seq 分配 + **gap-aware** 续读 + `Last-Event-ID` 等价）的行为证明。
 *
 * 判据（卡面验收 ② + 反例 ② ④）
 * ---------------------------
 *   ① {@link continualFrom} 的纯函数判据（不碰 IO，喂数组即可）：
 *      - `[5,6,8]` + `after=5` ⇒ **只补 6**（不返 8）；
 *      - `[5,6,8]` + `after=0` ⇒ `[5,6]`（遇到 8 的洞就停）；
 *      - `[1,2,3]` + `after=2` ⇒ `[3]`（已发的 1、2 不重放）；
 *      - 空 ⇒ 空。
 *   ② **真链路**：库里 `1,2,3,5`（缺 4）+ `after_seq=3` ⇒ **0 帧**（期望 4、拿到 5 ⇒ 停）；
 *      `after_seq=0` ⇒ **3 帧**（1,2,3，遇 5 停）。
 *   ③ **`Last-Event-ID` 与 `after_seq` 等价**：同值给同样 body。
 *   ④ **反例 ②（续读不得触发第二次执行）**：读之前/之后，run 的 `status` 与
 *      `agent_event` 行数都不变。这是"读不是跑"的机械化证明。
 *   ⑤ **反例 ④（seq 跨 run 复用）**：`seq` 是 **run 内**序号 —— 两个 run 各自从 1 开始，
 *      查询级断言按 run 隔离（`(run_id, seq)` 才是完整键）。这条**不是**缺陷，
 *      是契约口径；用例把它钉住，防将来有人"顺手"改成全局唯一。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/event-cursor.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { RunEventWriter } from "../dist/modules/run/event-writer.js";
import { continualFrom } from "../dist/modules/run/sse-stream.js";
import { makeApp, request, TENANT_ID } from "./routes-harness.mjs";
import {
  countRows,
  createAgentWithVersion,
  createConversation,
  seedEvent,
  seedRun,
  seedWorkspace,
} from "./fixtures/run-fixture.mjs";

/** 造链。 */
async function seedChain(fixture, runOptions = {}) {
  seedWorkspace(fixture);
  const { agentId, versionId } = await createAgentWithVersion(fixture);
  const conversationId = await createConversation(fixture, agentId);
  const runId = seedRun(fixture, { agentId, versionId, conversationId, ...runOptions });
  return { agentId, versionId, conversationId, runId };
}

/** 把 SSE 响应体切成帧。 */
function splitFrames(body) {
  return body
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk !== "" && chunk.startsWith("id:"));
}

/** 从帧里取 `id:` 行的数字。 */
function seqOf(frame) {
  const match = /^id: (\d+)$/m.exec(frame);
  return match === null ? null : Number(match[1]);
}

// ---------------------------------------------------------------------------
// A 组 · 纯函数
// ---------------------------------------------------------------------------

test("A-1 · continualFrom([5,6,8], 5) ⇒ 只补 6（不返 8、不重放 5）", () => {
  const rows = [{ seq: 5 }, { seq: 6 }, { seq: 8 }];
  assert.deepEqual(
    continualFrom(rows, 5).map((r) => r.seq),
    [6]
  );
});

test("A-2 · continualFrom([5,6,8], 0) ⇒ [5,6]（遇洞即停，不补 7）", () => {
  const rows = [{ seq: 5 }, { seq: 6 }, { seq: 8 }];
  assert.deepEqual(
    continualFrom(rows, 0).map((r) => r.seq),
    [5, 6]
  );
});

test("A-3 · 重放保护：已发过的 seq 被跳过（`[1,2,3]` + after=2 ⇒ `[3]`）", () => {
  const rows = [{ seq: 1 }, { seq: 2 }, { seq: 3 }];
  assert.deepEqual(
    continualFrom(rows, 2).map((r) => r.seq),
    [3]
  );
});

test("A-4 · 空输入 ⇒ 空（不抛错）", () => {
  assert.deepEqual(continualFrom([], 0), []);
  assert.deepEqual(continualFrom([], 7), []);
});

// ---------------------------------------------------------------------------
// B 组 · 真链路
// ---------------------------------------------------------------------------

test("B-1 · 缺帧：库里 1,2,3,5 + after_seq=3 ⇒ **0 帧**（期望 4、拿到 5 ⇒ 停）", async () => {
  const fixture = await makeApp({ username: "cur-b1" });
  try {
    const { runId, agentId } = await seedChain(fixture, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: 1,
    });
    for (const seq of [1, 2, 3, 5]) {
      seedEvent(fixture, runId, seq, "agent.thinking", { run_id: runId, iteration: seq });
    }
    // agentId 只用于让链更真实（不参与断言）
    assert.ok(agentId.length > 0);

    const stopped = await request(fixture, "GET", `/api/v1/runs/${runId}/events?after_seq=3`);
    assert.equal(stopped.statusCode, 200);
    assert.equal(
      splitFrames(stopped.body).length,
      0,
      "4 缺失 ⇒ 5 不得下发（宁可晚，不可错）"
    );

    const fromStart = await request(fixture, "GET", `/api/v1/runs/${runId}/events?after_seq=0`);
    assert.deepEqual(splitFrames(fromStart.body).map(seqOf), [1, 2, 3], "从头读到洞前");

    const fromOne = await request(fixture, "GET", `/api/v1/runs/${runId}/events?after_seq=1`);
    assert.deepEqual(splitFrames(fromOne.body).map(seqOf), [2, 3]);
  } finally {
    await fixture.close();
  }
});

test("B-2 · `Last-Event-ID` 与 `after_seq` **等价**（同值同 body）", async () => {
  const fixture = await makeApp({ username: "cur-b2" });
  try {
    const { runId } = await seedChain(fixture, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: 1,
    });
    for (const seq of [1, 2, 3]) {
      seedEvent(fixture, runId, seq, "agent.thinking", { run_id: runId, iteration: seq });
    }

    const viaQuery = await request(fixture, "GET", `/api/v1/runs/${runId}/events?after_seq=1`);
    const viaHeader = await fixture.app.inject({
      method: "GET",
      url: `/api/v1/runs/${runId}/events`,
      headers: { authorization: fixture.authHeader, "last-event-id": "1" },
    });

    assert.equal(viaHeader.statusCode, 200);
    assert.deepEqual(
      splitFrames(viaHeader.body).map(seqOf),
      splitFrames(viaQuery.body).map(seqOf),
      "两种游标必须给出同样的帧序列"
    );
    assert.deepEqual(splitFrames(viaHeader.body).map(seqOf), [2, 3]);

    // 查询参数**优先于** header（显式覆盖隐式）
    const both = await fixture.app.inject({
      method: "GET",
      url: `/api/v1/runs/${runId}/events?after_seq=2`,
      headers: { authorization: fixture.authHeader, "last-event-id": "0" },
    });
    assert.deepEqual(splitFrames(both.body).map(seqOf), [3], "after_seq 覆盖 Last-Event-ID");
  } finally {
    await fixture.close();
  }
});

test("B-3 · 反例②：续读**不触发执行**（run 状态与事件行数都不变）", async () => {
  const fixture = await makeApp({ username: "cur-b3" });
  try {
    const { runId } = await seedChain(fixture, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: 1,
    });
    seedEvent(fixture, runId, 1, "agent.thinking", { run_id: runId, iteration: 1 });

    const statusBefore = fixture.raw
      .prepare("select status, completed_at from agent_run where id = ?")
      .get(runId);
    const rowsBefore = countRows(fixture, "agent_event", `run_id = '${runId}'`);

    await request(fixture, "GET", `/api/v1/runs/${runId}/events?after_seq=0`);
    await request(fixture, "GET", `/api/v1/runs/${runId}/events?after_seq=0`);

    const statusAfter = fixture.raw
      .prepare("select status, completed_at from agent_run where id = ?")
      .get(runId);
    assert.deepEqual(statusAfter, statusBefore, "续读不得改 run 状态 / completed_at");
    assert.equal(
      countRows(fixture, "agent_event", `run_id = '${runId}'`),
      rowsBefore,
      "续读不得产生新事件"
    );
  } finally {
    await fixture.close();
  }
});

test("B-4 · seq 是 **run 内**序号：两个 run 各自从 1 开始（反例 ④ 的正确口径）", async () => {
  const fixture = await makeApp({ username: "cur-b4" });
  try {
    seedWorkspace(fixture);
    const first = await createAgentWithVersion(fixture, "run-1");
    const conv1 = await createConversation(fixture, first.agentId);
    const run1 = seedRun(fixture, {
      agentId: first.agentId,
      versionId: first.versionId,
      conversationId: conv1,
      status: "RUNNING",
    });

    const second = await createAgentWithVersion(fixture, "run-2");
    const conv2 = await createConversation(fixture, second.agentId);
    const run2 = seedRun(fixture, {
      agentId: second.agentId,
      versionId: second.versionId,
      conversationId: conv2,
      status: "RUNNING",
    });

    const writer1 = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId: run1,
    });
    const writer2 = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId: run2,
    });

    const a1 = await writer1.append("agent.thinking", { iteration: 1 });
    const a2 = await writer2.append("agent.thinking", { iteration: 1 });
    assert.equal(a1.seq, 1);
    assert.equal(a2.seq, 1, "另一个 run 的 seq 从 1 重新开始（run 内序号）");

    // 查询级隔离：各自的游标互不影响
    const rows1 = await writer1.listAfter(0);
    const rows2 = await writer2.listAfter(0);
    assert.equal(rows1.length, 1);
    assert.equal(rows2.length, 1);
    assert.notEqual(rows1[0].id, rows2[0].id, "两条事件是不同的行");
  } finally {
    await fixture.close();
  }
});
