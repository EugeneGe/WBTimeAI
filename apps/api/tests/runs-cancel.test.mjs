/**
 * T3-08 · run 取消（`POST /runs/{id}/cancel`）的行为证明。
 *
 * 判据（卡面验收 ⑥ + py `agent_run_service.py:239-268` 的语义）
 * ----------------------------------------------------------
 *   ① **取消是幂等的**（**不是** 409）：py 原文 `if run.status not in terminal_values(): ...`
 *      ⇒ 已是终态就**原样返回**。这与审批的二次决议（409）不同 —— 取消的语义是
 *      "确保它停下来"，它已经停了就不该报错。
 *   ② **取消只改状态与终态字段**：`status=CANCELLED` / `success=false` /
 *      `error_type=CANCELLED` / `stop_reason="cancelled"`（v0019 要求终态必写 11 值之一。
 *      py 不写 `stop_reason`，这是 TS 对 v0019 的强制，已登记偏差）。
 *   ③ **取消后零事件**：再 `append` ⇒ `RunTerminalError` 且零写。
 *   ④ **取消置进程内 abort 信号**（验收 ⑥ 的机制面）。
 *   ⑤ **跨租户 404**（先判归属，不泄漏存在性）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/runs-cancel.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { RunCoordinator } from "../dist/modules/run/coordinator.js";
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

/** 造链（同 lifecycle 的形态，独立一份以免跨文件耦合）。 */
async function seedChain(fixture, runOptions = {}) {
  seedWorkspace(fixture);
  const { agentId, versionId } = await createAgentWithVersion(fixture);
  const conversationId = await createConversation(fixture, agentId);
  const runId = seedRun(fixture, { agentId, versionId, conversationId, ...runOptions });
  return { agentId, versionId, conversationId, runId };
}

// ---------------------------------------------------------------------------
// A 组 · 取消语义
// ---------------------------------------------------------------------------

test("A-1 · cancel RUNNING ⇒ 200 + CANCELLED + success=false + error_type=CANCELLED + stop_reason=cancelled", async () => {
  const fixture = await makeApp({ username: "can-a1" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const response = await request(fixture, "POST", `/api/v1/runs/${runId}/cancel`);
    assert.equal(response.statusCode, 200, "契约成功码 200");
    const data = JSON.parse(response.body).data;
    assert.equal(data.status, "CANCELLED");
    assert.equal(data.success, false);
    assert.equal(data.error_type, "CANCELLED", "py CANCELLED_ERROR_TYPE 同值");
    assert.equal(data.stop_reason, "cancelled", "v0019：终态必须写 11 值之一");
    assert.notEqual(data.completed_at, null);
  } finally {
    await fixture.close();
  }
});

test("A-2 · 二次 cancel ⇒ 200 **幂等**（不是 409、不改状态）", async () => {
  const fixture = await makeApp({ username: "can-a2" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const first = await request(fixture, "POST", `/api/v1/runs/${runId}/cancel`);
    assert.equal(first.statusCode, 200);

    const second = await request(fixture, "POST", `/api/v1/runs/${runId}/cancel`);
    assert.equal(second.statusCode, 200, "取消必须幂等（py：已终态原样返回）");
    const data = JSON.parse(second.body).data;
    assert.equal(data.status, "CANCELLED");
    assert.equal(data.id, runId);

    // 行数不变（没有新建"取消记录"之类的东西）
    assert.equal(countRows(fixture, "agent_run", `id = '${runId}'`), 1);
  } finally {
    await fixture.close();
  }
});

test("A-3 · cancel 已 SUCCEEDED 的 run ⇒ 200 幂等，**状态不被改写**", async () => {
  const fixture = await makeApp({ username: "can-a3" });
  try {
    const { runId } = await seedChain(fixture, {
      status: "SUCCEEDED",
      stopReason: "model_finish",
      success: 1,
    });
    const response = await request(fixture, "POST", `/api/v1/runs/${runId}/cancel`);
    assert.equal(response.statusCode, 200);
    const data = JSON.parse(response.body).data;
    assert.equal(data.status, "SUCCEEDED", "已成功的 run 不得被取消改写");
    assert.equal(data.stop_reason, "model_finish", "stop_reason 也不得被覆盖成 cancelled");
  } finally {
    await fixture.close();
  }
});

test("A-4 · cancel 跨租户 / 不存在 ⇒ 404", async () => {
  const fixture = await makeApp({ username: "can-a4" });
  try {
    const otherRunId = seedOtherTenantRun(fixture);
    const cross = await request(fixture, "POST", `/api/v1/runs/${otherRunId}/cancel`);
    assert.equal(cross.statusCode, 404);
    assert.equal(errorOf(cross).code, "NOT_FOUND");

    // 对照：那一行**没被**改动
    assert.equal(
      fixture.raw.prepare("select status from agent_run where id = ?").get(otherRunId).status,
      "RUNNING",
      "跨租户的取消不得落到别租户的行上"
    );

    const missing = await request(
      fixture,
      "POST",
      "/api/v1/runs/f0000000-0000-4000-8000-0000000000de/cancel"
    );
    assert.equal(missing.statusCode, 404);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B 组 · 取消之后
// ---------------------------------------------------------------------------

test("B-1 · 取消后 append ⇒ 终态拒绝且零写", async () => {
  const fixture = await makeApp({ username: "can-b1" });
  try {
    const { runId, agentId } = await seedChain(fixture, { status: "RUNNING" });
    await request(fixture, "POST", `/api/v1/runs/${runId}/cancel`);

    const writer = new RunEventWriter({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      runId,
    });
    const before = countRows(fixture, "agent_event", `run_id = '${runId}'`);
    await assert.rejects(
      () => writer.append("agent.thinking", { iteration: 1 }),
      (error) => error instanceof RunTerminalError
    );
    assert.equal(countRows(fixture, "agent_event", `run_id = '${runId}'`), before);
    // agentId 仅用于证明链是真的（避免 lint 未使用）
    assert.ok(agentId.length > 0);
  } finally {
    await fixture.close();
  }
});

test("B-2 · 取消置进程内 abort 信号（`signalOf(runId).aborted === true`）", async () => {
  const fixture = await makeApp({ username: "can-b2" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    // 与 `app.ts` 用同一构造参数建实例 —— 路由层持有的就是这一个（单实例，见装配注释）。
    const coordinator = new RunCoordinator({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });

    assert.equal(coordinator.signalOf(runId).aborted, false, "取消前必须是未中断");
    await coordinator.cancel(runId);
    assert.equal(
      coordinator.signalOf(runId).aborted,
      true,
      "取消必须立刻打断该 run 的进行中流"
    );

    // 收尾清理后不再持有
    coordinator.forget(runId);
    assert.equal(coordinator.signalOf(runId).aborted, false, "forget 后是新的未中断信号");
  } finally {
    await fixture.close();
  }
});

test("B-3 · **在飞 run 的 controller 不因订阅收尾被丢弃** ⇒ 之后 cancel 仍能置位旧 signal（AUD-02）", async () => {
  const fixture = await makeApp({ username: "can-b3" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const coordinator = new RunCoordinator({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });

    // `RunDriver` 在 run 启动时就是这么拿 signal 的（`RunCallContext.signal`）——
    // 它拿到的引用会活到 run 收尾，**不会**重新获取。
    const driverHeldSignal = coordinator.signalOf(runId);

    // 订阅收尾（`GET /runs/{id}/events` 的 finally）：run 还没终态 ⇒ 不得丢弃。
    const forgotten = await coordinator.forgetIfTerminal(runId);
    assert.equal(forgotten, false, "非终态不得丢弃 controller（controller 生命周期 = run 生命周期）");

    // 客户端取消（POST /runs/{id}/cancel）。
    await coordinator.cancel(runId);

    // 关键断言：driver 手里那个**旧** signal 必须被置位 —— 否则循环与工具前的
    // `signal.aborted` 检查全部失效（AUD-02 的缺陷形态）。
    assert.equal(
      driverHeldSignal.aborted,
      true,
      "取消必须打断 driver 持有的那个 signal（不是本次新建的另一个）"
    );
  } finally {
    await fixture.close();
  }
});

test("B-4 · 对照：无条件 forget 会丢掉在飞 run 的 signal（这就是 AUD-02 的成因）", async () => {
  const fixture = await makeApp({ username: "can-b4" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const coordinator = new RunCoordinator({
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });

    const driverHeldSignal = coordinator.signalOf(runId);
    // 旧路由的写法：订阅收尾无条件 `forget`。
    coordinator.forget(runId);

    await coordinator.cancel(runId);

    assert.equal(
      driverHeldSignal.aborted,
      false,
      "旧写法下 driver 持有的 signal 永不置位 —— 这条断言把缺陷形态钉住，" +
        "防止有人把订阅收尾改回无条件 forget"
    );

    // 对照：run 的**库态**其实已经是 CANCELLED（取消"看起来生效了"，
    // 但在飞循环仍在跑）—— 这正是"不可判定"的危害。
    assert.equal(await coordinator.isTerminal(runId), true, "库态已取消");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// C 组 · 认证
// ---------------------------------------------------------------------------
test("C-1 · 无令牌 cancel ⇒ 401（且不落任何状态变更）", async () => {
  const fixture = await makeApp({ username: "can-c1" });
  try {
    const { runId } = await seedChain(fixture, { status: "RUNNING" });
    const response = await fixture.app.inject({
      method: "POST",
      url: `/api/v1/runs/${runId}/cancel`,
    });
    assert.equal(response.statusCode, 401);
    assert.equal(errorOf(response).code, "UNAUTHORIZED");
    assert.equal(
      fixture.raw.prepare("select status from agent_run where id = ?").get(runId).status,
      "RUNNING",
      "未认证的取消不得改状态"
    );
  } finally {
    await fixture.close();
  }
});
