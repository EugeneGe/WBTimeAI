/**
 * T3-14 · 不变量 ④：**审批拒绝不进执行器**。
 *
 * 判据（DoD#1 前 5 条不变量的第 4 条）
 * ---------------------------------
 *   | 编号 | 断言 | 机器形态 |
 *   |---|---|---|
 *   | A-1 | 命中 `requires_approval` ⇒ run 停在 `WAITING_APPROVAL` 且落 `approval.requested` | 状态 + 帧 + `approval` 行 |
 *   | A-2 | **驳回 ⇒ 工具未执行**（副作用文件不存在）+ `tool_call.DENIED` | 文件系统观测（最硬的证据） |
 *   | A-3 | 驳回 ⇒ run 收敛 `CANCELLED` + `stop_reason='approval_rejected'`（R3-04 矩阵） | 终态三元组 |
 *   | A-4 | 驳回路径也落 `approval.decided` 帧（帧集合完整） | 帧计数 |
 *
 * 为什么用"副作用文件"而不是"看 tool_call 状态"
 * ---------------------------------------
 *   `tool_call.status='DENIED'` 可以**先执行再写 DENIED**（状态是自报的）。
 *   文件系统是外部观测：工具如果真跑了，文件就在。这是本仓一贯的"外部可观测证据"
 *   口径（同 T3-10 的"命中本地规则 ⇒ 沙箱 exec 计数 == 0"）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/invariants/approval.test.mjs`
 */

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { makeRunApp, makeTempDir, sleep, toolTurn, finalTurn } from "./_harness.mjs";

/** 审批等待上限（本文件把它压到 8s；正常驳回在 ~100ms 内完成）。 */
const APPROVAL_WAIT_MS = 8_000;

/**
 * 起一个"命中审批"的 run（工具 = `filesystem.write`，副作用可外部观测）。
 *
 * @param {object} fixture {@link makeRunApp} 产物。
 * @param {string} markerName 目标文件名（相对 run 工作区）。
 * @returns `{runId, markerPath}`。
 */
async function startApprovalRun(fixture, markerName) {
  const started = await fixture.startRun({
    runtimeConfig: { requires_approval: ["filesystem"] },
  });
  assert.equal(started.response.statusCode, 200, started.response.body);
  const run = JSON.parse(started.response.body).data;
  const workspaceRoot = process.env.WBTIME_RUN_WORKSPACE_ROOT;
  assert.ok(typeof workspaceRoot === "string" && workspaceRoot !== "", "本用例必须先设置 WBTIME_RUN_WORKSPACE_ROOT");
  return { runId: run.id, markerPath: join(workspaceRoot, run.id, markerName) };
}

// ---------------------------------------------------------------------------
// A-1 · 命中审批 ⇒ WAITING_APPROVAL + approval.requested
// ---------------------------------------------------------------------------

test("A-1 · 命中 requires_approval ⇒ run 进 WAITING_APPROVAL ∧ approval.requested 已发", async () => {
  const temp = makeTempDir("wbtime-t314-approval-");
  process.env.WBTIME_RUN_WORKSPACE_ROOT = temp.dir;
  const fixture = await makeRunApp({
    turns: [
      toolTurn("call-a1", "filesystem", { action: "write", path: "marker-a1.txt", content: "x" }),
      finalTurn(),
    ],
  });
  try {
    const { runId } = await startApprovalRun(fixture, "marker-a1.txt");

    // 等审批行出现（driver 在建 approval 行之后才迁状态，所以两者几乎同时）
    await fixture.waitFor(
      () => fixture.count("select count(*) as n from approval") === 1,
      "approval 行",
      APPROVAL_WAIT_MS,
    );
    const approval = fixture.raw.prepare("select * from approval").get();
    assert.equal(approval.subject_type, "tool");
    assert.equal(approval.subject_ref, "call-a1", "subject_ref = tool_call id");
    assert.equal(approval.status, "PENDING");

    const channels = fixture.channelsOf(runId);
    assert.ok(channels.includes("approval.requested"), `帧集合缺 approval.requested：${channels.join(",")}`);
    const frame = fixture
      .eventsOf(runId)
      .find((row) => row.type === "approval.requested");
    const payload = JSON.parse(frame.payload);
    assert.equal(payload.approval_id, approval.id, "帧里的 approval_id 必须与库里同一行");
    assert.equal(payload.subject_type, "tool");
    assert.equal(payload.subject_ref, "call-a1");

    // 驳回，让 run 收敛（否则会等满 15s 超时）
    const rejected = await fixture.app.inject({
      method: "POST",
      url: `/api/v1/approvals/${approval.id}/reject`,
      headers: fixture.headers,
      payload: {},
    });
    assert.equal(rejected.statusCode, 200, rejected.body);
    await fixture.waitTerminal(runId, APPROVAL_WAIT_MS);
  } finally {
    await fixture.close();
    temp.cleanup();
  }
});

// ---------------------------------------------------------------------------
// A-2 / A-3 / A-4 · 驳回 ⇒ 未执行 + 矩阵合法终态 + 帧完整
// ---------------------------------------------------------------------------

test("A-2/A-3/A-4 · 驳回 ⇒ 工具未执行（副作用文件不存在）∧ tool_call.DENIED ∧ CANCELLED/approval_rejected", async () => {
  const temp = makeTempDir("wbtime-t314-approval-rej-");
  process.env.WBTIME_RUN_WORKSPACE_ROOT = temp.dir;
  const fixture = await makeRunApp({
    turns: [
      toolTurn("call-a2", "filesystem", { action: "write", path: "marker-a2.txt", content: "不该写进来" }),
      finalTurn(),
    ],
  });
  try {
    const { runId, markerPath } = await startApprovalRun(fixture, "marker-a2.txt");
    await fixture.waitFor(
      () => fixture.count("select count(*) as n from approval") === 1,
      "approval 行",
      APPROVAL_WAIT_MS,
    );
    const approval = fixture.raw.prepare("select * from approval").get();
    await fixture.app.inject({
      method: "POST",
      url: `/api/v1/approvals/${approval.id}/reject`,
      headers: fixture.headers,
      payload: {},
    });

    const terminal = await fixture.waitTerminal(runId, APPROVAL_WAIT_MS);

    // A-2 ①：**外部观测** —— 文件不存在（工具真的没跑）
    assert.equal(existsSync(markerPath), false, `工具不该被执行：${markerPath} 竟然存在`);

    // A-2 ②：tool_call 落在 DENIED（终态之一），且没有 output
    const calls = fixture.toolCallsOf(runId);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].status, "DENIED", `实测 ${calls[0].status}`);
    assert.equal(calls[0].output, null, "未执行的调用不得有 output");
    assert.ok(
      String(calls[0].error ?? "").includes("未获审批"),
      `error 要说明原因，实测 ${JSON.stringify(calls[0].error)}`,
    );

    // A-3：R3-04 矩阵里 approval_rejected 只能配 CANCELLED
    assert.equal(terminal.status, "CANCELLED", JSON.stringify(terminal));
    assert.equal(terminal.stop_reason, "approval_rejected", JSON.stringify(terminal));
    assert.equal(terminal.success, 0, "驳回 ≠ 成功");

    // A-4：帧集合完整（requested + decided），且 decided 的 status 是 REJECTED
    const channels = fixture.channelsOf(runId);
    assert.ok(channels.includes("approval.requested"), channels.join(","));
    assert.ok(channels.includes("approval.decided"), channels.join(","));
    const decided = JSON.parse(
      fixture.eventsOf(runId).find((row) => row.type === "approval.decided").payload,
    );
    assert.equal(decided.status, "REJECTED");
    assert.equal(decided.approval_id, approval.id);
    assert.equal(decided.decided_by, fixture.userId);
    assert.ok(channels.includes("agent.error"), "失败类终态必须发 agent.error");
  } finally {
    await fixture.close();
    temp.cleanup();
  }
});

// ---------------------------------------------------------------------------
// A-5 · 批准路径对照（否则"未执行"可能是"任何情况都不执行"）
// ---------------------------------------------------------------------------

test("A-5 · 对照：批准 ⇒ 工具**真的**执行（副作用文件存在）∧ SUCCEEDED", async () => {
  const temp = makeTempDir("wbtime-t314-approval-ok-");
  process.env.WBTIME_RUN_WORKSPACE_ROOT = temp.dir;
  const fixture = await makeRunApp({
    turns: [
      toolTurn("call-a5", "filesystem", { action: "write", path: "marker-a5.txt", content: "批准后写入" }),
      finalTurn(),
    ],
  });
  try {
    const { runId, markerPath } = await startApprovalRun(fixture, "marker-a5.txt");
    await fixture.waitFor(
      () => fixture.count("select count(*) as n from approval") === 1,
      "approval 行",
      APPROVAL_WAIT_MS,
    );
    const approval = fixture.raw.prepare("select * from approval").get();
    const approved = await fixture.app.inject({
      method: "POST",
      url: `/api/v1/approvals/${approval.id}/approve`,
      headers: fixture.headers,
      payload: {},
    });
    assert.equal(approved.statusCode, 200, approved.body);

    const terminal = await fixture.waitTerminal(runId, APPROVAL_WAIT_MS);
    assert.equal(terminal.status, "SUCCEEDED", JSON.stringify(terminal));
    assert.equal(terminal.stop_reason, "model_finish");
    assert.equal(existsSync(markerPath), true, `批准后工具必须真的执行：${markerPath} 不存在`);
    assert.equal(fixture.toolCallsOf(runId)[0].status, "SUCCESS");

    // 等待期不计入活动墙钟（R3-07）：这里只断"预算没有被暂停态卡死"——
    // pause/resume 若不成对，`BudgetLedger` 会在 stop() 时抛错，run 就不会 SUCCEEDED。
    await sleep(1);
  } finally {
    await fixture.close();
    temp.cleanup();
  }
});

// COUNTEREXAMPLE: 把 `RunDriver` 执行器装饰器里的
// `if (decision.rejected) { ... return finish({status:"DENIED"}) }` 改成"继续往下执行"
// （只把驳回记进日志）⇒ A-2 的 `existsSync(markerPath)` 变成 true、`calls[0].status`
// 变成 SUCCESS ⇒ A-2 红；A-3 的终态也变成 SUCCEEDED ⇒ A-3 红（双红）。
// 复跑：改 `apps/api/src/modules/run/driver.ts` 后
//       `pnpm --filter @wbtime/api build && cd apps/api && node --experimental-sqlite --test tests/invariants/approval.test.mjs`
//
// COUNTEREXAMPLE: 把 `approvalRequiredFor()` 改成恒 `false`（"审批闸没装"）⇒ 工具直接执行、
// **没有** `approval` 行、**没有** `approval.requested` 帧 ⇒ A-1 红（双红：行 + 帧）。
// 注：`legacy` 的另一条反例「删掉 `ledger.pause()/resume()`」本版**不可验证**（需要
// 超过 600s 墙钟的等待才能触发 `wall_time`），故**不登记为已完成**（R3-21 ③）。
