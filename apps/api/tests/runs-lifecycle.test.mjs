/**
 * T3-08 · run 生命周期（`GET /runs/{id}` + lease/CAS + 终态）的行为证明。
 *
 * 判据（卡面验收 ① ⑤ + 反例 ①）
 * ----------------------------
 *   ① **lease / CAS**（验收 ①）：两个 worker **并发**抢同一 run ⇒ **恰一方成功**，
 *      另一方 `LeaseRejectedError`。测试用 `Promise.allSettled` 真并发发起，断言
 *      `fulfilled === 1 && rejected === 1` —— 这是"恰一方"唯一的机器形态。
 *   ② **终态后零事件**（验收 ⑤ / 反例 ①）：run 落 `SUCCEEDED` 后再 `append` ⇒
 *      `RunTerminalError`，且 `agent_event` 行数**不变**（抛错 + 零写，两件事都要断）。
 *   ③ **`RunResponse` 21 键**（v0019）：20 键 + `stop_reason`；`token_usage` 空对象、
 *      `cost` 为 null 时 `cost_status` 仍是 `UNPRICED`。
 *   ④ **跨租户 404**（I-1）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/runs-lifecycle.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { RunCoordinator, LeaseRejectedError } from "../dist/modules/run/coordinator.js";
import { RunEventWriter, RunTerminalError } from "../dist/modules/run/event-writer.js";
import { errorOf, makeApp, request, TENANT_ID } from "./routes-harness.mjs";
import {
  countRows,
  createAgentWithVersion,
  createConversation,
  seedOtherTenantRun,
  seedRun,
  seedWorkspace,
} from "./fixtures/run-fixture.mjs";

/** 契约 `RunResponse` 的 21 键（v0018 的 20 + v0019 的 `stop_reason`）。 */
const RUN_KEYS = [
  "agent_id",
  "agent_version_id",
  "completed_at",
  "conversation_id",
  "cost",
  "cost_status",
  "duration_ms",
  "error",
  "error_type",
  "id",
  "run_mode",
  "started_at",
  "status",
  "stop_reason",
  "success",
  "task_id",
  "tenant_id",
  "token_usage",
  "trace_id",
  "trigger",
  "user_id",
];

/** 造一条可跑的链路（workspace → agent/version → conversation → run）。 */
async function seedChain(fixture, runOptions = {}) {
  seedWorkspace(fixture);
  const { agentId, versionId } = await createAgentWithVersion(fixture);
  const conversationId = await createConversation(fixture, agentId);
  const runId = seedRun(fixture, { agentId, versionId, conversationId, ...runOptions });
  return { agentId, versionId, conversationId, runId };
}

// ---------------------------------------------------------------------------
// A 组 · GET /runs/{id}
// ---------------------------------------------------------------------------

test("A-1 · GET /runs/{id} ⇒ 200 + 21 键（含 v0019 的 stop_reason）", async () => {
  const fixture = await makeApp({ username: "run-a1" });
  try {
    const { runId, agentId } = await seedChain(fixture, { status: "SUCCEEDED", stopReason: "model_finish", success: 1 });
    const response = await request(fixture, "GET", `/api/v1/runs/${runId}`);
    assert.equal(response.statusCode, 200);
    const data = JSON.parse(response.body).data;
    assert.deepEqual(Object.keys(data).sort(), RUN_KEYS);
    assert.equal(data.id, runId);
    assert.equal(data.agent_id, agentId);
    assert.equal(data.status, "SUCCEEDED");
    assert.equal(data.stop_reason, "model_finish");
    assert.deepEqual(data.token_usage, {}, "列 null ⇒ 契约 object 回落 {}");
    assert.equal(data.cost, null, "未计价 ⇒ null（不是 0）");
    assert.equal(data.cost_status, "UNPRICED");
  } finally {
    await fixture.close();
  }
});

test("A-2 · 跨租户 / 不存在 ⇒ 404 `NOT_FOUND`", async () => {
  const fixture = await makeApp({ username: "run-a2" });
  try {
    const otherRunId = seedOtherTenantRun(fixture);

    const cross = await request(fixture, "GET", `/api/v1/runs/${otherRunId}`);
    assert.equal(cross.statusCode, 404, "跨租户必须 404（不是 403）");
    assert.equal(errorOf(cross).code, "NOT_FOUND");
    assert.deepEqual(errorOf(cross).data, { run_id: otherRunId });

    const missing = await request(
      fixture,
      "GET",
      "/api/v1/runs/f0000000-0000-4000-8000-0000000000de"
    );
    assert.equal(missing.statusCode, 404);

    // 对照：那一行确实在库里（否则 404 可能只是"没插进去"）
    assert.equal(countRows(fixture, "agent_run", `id = '${otherRunId}'`), 1);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B 组 · lease / CAS（验收 ①）
// ---------------------------------------------------------------------------

test("B-1 · 双 worker 并发抢同一 run ⇒ **恰一方成功**（CAS）", async () => {
  const fixture = await makeApp({ username: "run-b1" });
  try {
    const { runId } = await seedChain(fixture, { status: "QUEUED" });
    const coordinator = new RunCoordinator({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });

    // 真并发发起（不是"先 await 一个再 await 另一个"—— 那样必然第一方成功，测不出 CAS）。
    const results = await Promise.allSettled([
      coordinator.acquire(runId, { from: ["QUEUED"], to: "RUNNING" }),
      coordinator.acquire(runId, { from: ["QUEUED"], to: "RUNNING" }),
    ]);

    const fulfilled = results.filter((r) => r.status === "fulfilled");
    const rejected = results.filter((r) => r.status === "rejected");
    assert.equal(fulfilled.length, 1, "必须恰有一方抢到");
    assert.equal(rejected.length, 1, "必须恰有一方被拒");
    assert.ok(
      rejected[0].reason instanceof LeaseRejectedError,
      `被拒方必须是 LeaseRejectedError，实测 ${String(rejected[0].reason)}`
    );

    // 状态只被推进一次
    assert.equal(
      fixture.raw.prepare("select status from agent_run where id = ?").get(runId).status,
      "RUNNING"
    );
  } finally {
    await fixture.close();
  }
});

test("B-2 · 抢已在 RUNNING 的 run ⇒ 拒绝；抢不存在的 run ⇒ 404", async () => {
  const fixture = await makeApp({ username: "run-b2" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const coordinator = new RunCoordinator({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });

    await assert.rejects(
      () => coordinator.acquire(runId, { from: ["QUEUED"], to: "RUNNING" }),
      (error) => error instanceof LeaseRejectedError
    );

    await assert.rejects(
      () => coordinator.acquire("f0000000-0000-4000-8000-0000000000de", { from: ["QUEUED"] }),
      (error) => {
        assert.equal(error.statusCode, 404, "不存在的 run 要 404，不是 409");
        return true;
      }
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// C 组 · 终态落库 + 终态后零事件
// ---------------------------------------------------------------------------

test("C-1 · finish 写终态：status / stop_reason / success / completed_at 一次落库", async () => {
  const fixture = await makeApp({ username: "run-c1" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const coordinator = new RunCoordinator({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });

    const updated = await coordinator.finish(runId, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: true,
      durationMs: 1234,
    });
    assert.equal(updated.status, "SUCCEEDED");
    assert.equal(updated.stop_reason, "model_finish");
    assert.equal(updated.success, true);
    assert.equal(updated.duration_ms, 1234);
    assert.notEqual(updated.completed_at, null, "completed_at 必须落值");
    assert.equal(await coordinator.isTerminal(runId), true);
  } finally {
    await fixture.close();
  }
});

test("C-2 · 终态后 append ⇒ **RunTerminalError 且零写**（验收 ⑤ / 反例 ①）", async () => {
  const fixture = await makeApp({ username: "run-c2" });
  try {
    const { runId, agentId } = await seedChain(fixture, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: 1,
    });
    const writer = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId,
    });

    const before = countRows(fixture, "agent_event", `run_id = '${runId}'`);
    await assert.rejects(
      () => writer.append("agent.started", { agent_id: agentId }),
      (error) => {
        assert.ok(error instanceof RunTerminalError, "终态后写入必须抛 RunTerminalError");
        assert.equal(error.status, "SUCCEEDED");
        return true;
      }
    );
    assert.equal(
      countRows(fixture, "agent_event", `run_id = '${runId}'`),
      before,
      "抛错的同时必须**一行都没写**（终态后零事件）"
    );
  } finally {
    await fixture.close();
  }
});

test("C-3 · 非终态 run 可以正常写事件，且 seq 从 1 递增", async () => {
  const fixture = await makeApp({ username: "run-c3" });
  try {
    const { runId, agentId } = await seedChain(fixture, { status: "RUNNING" });
    const writer = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId,
    });

    const first = await writer.append("agent.started", { agent_id: agentId });
    const second = await writer.append("agent.thinking", { iteration: 1 });

    assert.equal(first.seq, 1);
    assert.equal(second.seq, 2);
    assert.ok(Buffer.isBuffer(first.frame), "append 必须同时产出已编码帧");
    assert.match(first.frame.toString("utf8"), /^id: 1\nevent: agent\.started\ndata: \{/);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// E 组 · 并发收敛（AUD-03：中断言"取消不复活"）
// ---------------------------------------------------------------------------

test("E-1 · cancel 先到、finish 晚到 ⇒ 终态仍是 CANCELLED（**取消不复活**）", async () => {
  const fixture = await makeApp({ username: "run-e1" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const coordinator = new RunCoordinator({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });

    await coordinator.cancel(runId);
    // 晚到的成功收敛（`#settle` 的形态）：条件写不命中活跃态 ⇒ 一行都不改。
    const settled = await coordinator.finish(runId, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: true,
      durationMs: 12,
    });

    assert.equal(settled.status, "CANCELLED", "晚到的 SUCCEEDED 不得覆写 CANCELLED");
    assert.equal(settled.stop_reason, "cancelled");
    assert.equal(settled.success, false);
    assert.equal(settled.error_type, "CANCELLED");
  } finally {
    await fixture.close();
  }
});

test("E-2 · finish 对已终态 run ⇒ **幂等返回现状行**（不抛 404）；run 不存在 ⇒ 404", async () => {
  const fixture = await makeApp({ username: "run-e2" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const coordinator = new RunCoordinator({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });

    await coordinator.finish(runId, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: true,
    });
    const again = await coordinator.finish(runId, {
      status: "FAILED",
      stopReason: "tool_failed",
      success: false,
      error: "晚到的失败",
    });
    assert.equal(again.status, "SUCCEEDED", "终态行不得被二次写");
    assert.equal(again.error, null, "晚到的 error 不得写进成功态（终态行不带异族字段）");

    // 行不存在才 404 —— 「已终态」与「不存在」不得混成同一个结果。
    await assert.rejects(
      () =>
        coordinator.finish("f0000000-0000-4000-8000-0000000000de", {
          status: "SUCCEEDED",
          stopReason: "model_finish",
        }),
      (error) => {
        assert.equal(error.statusCode, 404);
        return true;
      }
    );
  } finally {
    await fixture.close();
  }
});

test("E-3 · 并发 cancel + finish ⇒ 终值行**自洽**（不留 success=null 的半写）", async () => {
  const fixture = await makeApp({ username: "run-e3" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const build = () =>
      new RunCoordinator({ db: fixture.connection.db, dialect: "sqlite", tenantId: TENANT_ID });

    // 两条路径并发（SQLite 驱动把它们串行化，但判据是"后到者不覆写"，与 PG 同语义）。
    const [cancelled, finished] = await Promise.all([
      build().cancel(runId),
      build().finish(runId, {
        status: "SUCCEEDED",
        stopReason: "model_finish",
        success: true,
      }),
    ]);

    const row = fixture.raw
      .prepare("select status, stop_reason, success, error_type from agent_run where id = ?")
      .get(runId);

    // 终值必须等于**其中一方**的写入（不是两者的混合）。
    assert.ok(
      row.status === "CANCELLED" || row.status === "SUCCEEDED",
      `终态必须是 CANCELLED 或 SUCCEEDED，实测 ${row.status}`
    );
    if (row.status === "CANCELLED") {
      assert.equal(row.stop_reason, "cancelled");
      assert.equal(row.success, 0);
      assert.equal(row.error_type, "CANCELLED");
      assert.equal(cancelled.status, "CANCELLED");
    } else {
      assert.equal(row.stop_reason, "model_finish");
      assert.equal(row.success, 1);
      assert.equal(row.error_type, null);
      assert.equal(finished.status, "SUCCEEDED");
    }
    // 反例形态：CAS 之后二次 finalize 会留下 `status=CANCELLED` 但 `success=null`
    // 的中间行 —— 一次写之后这一格不可能出现。
    assert.notEqual(row.success, null, "终态行不得留 success=null（那是两次写的中间态）");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// D 组 · 认证
// ---------------------------------------------------------------------------

test("D-1 · 无令牌 ⇒ 401", async () => {
  const fixture = await makeApp({ username: "run-d1" });
  try {
    const { runId } = await seedChain(fixture);
    for (const [method, url] of [
      ["GET", `/api/v1/runs/${runId}`],
      ["POST", `/api/v1/runs/${runId}/cancel`],
      ["GET", `/api/v1/runs/${runId}/events`],
    ]) {
      const response = await fixture.app.inject({ method, url });
      assert.equal(response.statusCode, 401, `${method} ${url} 无令牌必须 401`);
      assert.equal(errorOf(response).code, "UNAUTHORIZED");
    }
  } finally {
    await fixture.close();
  }
});
