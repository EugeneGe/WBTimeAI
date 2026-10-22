/**
 * T3-14 · 不变量 ①：**单 lease**（一个 run 恰由一个 worker 推进）。
 *
 * 判据（DoD#1 前 5 条不变量的第 1 条）
 * ---------------------------------
 *   | 编号 | 断言 | 机器形态 |
 *   |---|---|---|
 *   | B-1 | 两个 worker **并发**抢同一 run ⇒ **恰一方成功** | `Promise.allSettled` ⇒ `fulfilled===1 && rejected===1` |
 *   | B-2 | 驱动侧真的**先抢 lease 再干活** | 一个已终态的 run，任何时刻再 `acquire(from:["QUEUED"])` 都失败 |
 *   | B-3 | 单写者 ⇒ `agent.started` **恰一帧**（两个 worker 会各发一次） | `count(*) where type='agent.started'` == 1 |
 *
 * 为什么这三条必须一起断
 * -------------------
 *   B-1 只能证明「CAS 是 CAS」，证明不了「驱动用了它」。B-2/B-3 把驱动和 CAS 绑在一起：
 *   如果 `RunDriver.#drive` 忘了 `acquire`（或把它换成"先查后写"），B-3 就会变成 2 帧 ——
 *   那正是"两个 worker 同时推一个 run、各写一套事件"的真实形态。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/invariants/lease.test.mjs`
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";

import { RunCoordinator, LeaseRejectedError } from "../../dist/modules/run/coordinator.js";
import { makeRunApp, finalTurn, TENANT_ID, WORKSPACE_ID } from "./_harness.mjs";

/**
 * 裸 SQL 插一个 `QUEUED` 的 run（父链齐全：agent / version 由真路由产出）。
 *
 * 为什么不走 `POST /agents/{id}/run`：那个入口会**立刻**建 run 并抢 lease，
 * 于是"两个 worker 并发抢同一个 QUEUED 行"就没有可抢的对象了。B-1 需要一个
 * **静止的** `QUEUED` 行。
 *
 * @param {object} fixture {@link makeRunApp} 产物。
 * @returns {Promise<{runId: string, agentId: string, versionId: string}>}
 */
async function seedQueuedRun(fixture) {
  const agent = await fixture.createAgent();
  const conversationId = randomUUID();
  fixture.raw
    .prepare(
      "insert into conversation (id, tenant_id, workspace_id, agent_id, user_id, title, status) " +
        "values (?, ?, ?, ?, ?, 'lease 会话', 'ACTIVE')",
    )
    .run(conversationId, TENANT_ID, WORKSPACE_ID, agent.agentId, fixture.userId);

  const runId = randomUUID();
  fixture.raw
    .prepare(
      "insert into agent_run (id, tenant_id, agent_id, agent_version_id, conversation_id, user_id, " +
        "trigger, run_mode, status, tool_error_count, cost_estimated, cost_status) " +
        "values (?, ?, ?, ?, ?, ?, 'user', 'INLINE', 'QUEUED', 0, 0, 'UNPRICED')",
    )
    .run(runId, TENANT_ID, agent.agentId, agent.versionId, conversationId, fixture.userId);
  return { runId, agentId: agent.agentId, versionId: agent.versionId };
}

// ---------------------------------------------------------------------------
// B-1 · 并发抢 lease ⇒ 恰一方成功
// ---------------------------------------------------------------------------

test("B-1 · 两个 worker 并发抢同一 run ⇒ 恰一方成功（CAS）", async () => {
  const fixture = await makeRunApp({ turns: [finalTurn()] });
  try {
    const { runId } = await seedQueuedRun(fixture);
    // 两个**独立**协调器实例：模拟两个 worker 各自的进程内状态（取消 Map 不共享）。
    const workerA = new RunCoordinator({ db: fixture.connection.db, dialect: "sqlite", tenantId: TENANT_ID });
    const workerB = new RunCoordinator({ db: fixture.connection.db, dialect: "sqlite", tenantId: TENANT_ID });

    const outcomes = await Promise.allSettled([
      workerA.acquire(runId, { from: ["QUEUED"], to: "RUNNING" }),
      workerB.acquire(runId, { from: ["QUEUED"], to: "RUNNING" }),
    ]);

    const fulfilled = outcomes.filter((item) => item.status === "fulfilled");
    const rejected = outcomes.filter((item) => item.status === "rejected");
    assert.equal(fulfilled.length, 1, `恰一方成功，实测 ${fulfilled.length}`);
    assert.equal(rejected.length, 1, `恰一方失败，实测 ${rejected.length}`);
    assert.ok(
      rejected[0].reason instanceof LeaseRejectedError,
      `失败方必须是 LeaseRejectedError，实测 ${String(rejected[0].reason)}`,
    );

    // 对照：run 真的到了 RUNNING（不是"两边都没抢到"这种假绿）
    assert.equal(fixture.runRow(runId).status, "RUNNING");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B-2 / B-3 · 驱动侧真的抢 lease，且单写者
// ---------------------------------------------------------------------------

test("B-2/B-3 · 驱动先抢 lease 再干活 ⇒ 终态后再抢必失败 ∧ agent.started 恰一帧", async () => {
  const fixture = await makeRunApp({ turns: [finalTurn()] });
  try {
    const started = await fixture.startRun();
    assert.equal(started.response.statusCode, 200, started.response.body);
    const run = JSON.parse(started.response.body).data;
    const terminal = await fixture.waitTerminal(run.id);
    assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));

    // B-2：QUEUED → 已是终态，任何"从 QUEUED 抢"的尝试都必须失败（不是 404，是 CAS 未命中）
    const late = new RunCoordinator({ db: fixture.connection.db, dialect: "sqlite", tenantId: TENANT_ID });
    await assert.rejects(
      () => late.acquire(run.id, { from: ["QUEUED"], to: "RUNNING" }),
      (error) => {
        assert.ok(error instanceof LeaseRejectedError, `实测 ${String(error)}`);
        return true;
      },
      "终态 run 不得再被「从 QUEUED 抢」成功 —— 否则就是重复推进",
    );

    // B-3：单写者 ⇒ agent.started 恰一帧（两个 worker 会各发一次，共 2 帧）
    const startedFrames = fixture.eventsOf(run.id).filter((row) => row.type === "agent.started");
    assert.equal(startedFrames.length, 1, `agent.started 恰一帧，实测 ${startedFrames.length}`);
    // 内部行 `loop.started` 同样只能有一次（九步内核只跑一次）
    const loopStarted = fixture.eventsOf(run.id).filter((row) => row.type === "loop.started");
    assert.equal(loopStarted.length, 1, `loop.started 恰一次，实测 ${loopStarted.length}`);
  } finally {
    await fixture.close();
  }
});

// COUNTEREXAMPLE: 把 `AgentRunRepo.tryAcquireLease` 的 CAS（`UPDATE ... WHERE status IN (from)`）
// 拆成"先 findById 判 QUEUED、再 update"两段（两条 SQL 之间留出窗口）⇒ B-1 的
// `fulfilled.length` 从 1 变成 2（两个 worker 都通过了检查）⇒ B-1 红。
// 复跑：改 `packages/db/src/repositories/agent-run-repo.ts::tryAcquireLease` 后
//       `pnpm --filter @wbtime/db build && cd apps/api && node --experimental-sqlite --test tests/invariants/lease.test.mjs`
//
// COUNTEREXAMPLE: 删掉 `RunDriver.#drive` 开头的 `coordinator.acquire(runId, {from:["QUEUED"]})`
// （改成直接干活）⇒ 两个并发驱动都会写事件 ⇒ B-3 的 `agent.started` 变成 2 ⇒ B-3 红；
// 同时 B-2 的"终态后再抢"会**成功**（状态还在 QUEUED/RUNNING）⇒ B-2 也红。
