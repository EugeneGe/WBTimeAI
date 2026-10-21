// @wbtime/domain · T3-04 状态机测试（纯 reducer）。
//
// 判据（任务卡 T3-04 验收口径 ①）：
//   · **11 条合法迁移各 1 例**通过；
//   · 非法迁移 reject（例：`SUCCEEDED → RUNNING`；`QUEUED + COMPLETE`）；
//   · 终态后零事件（任何事件 ⇒ `TERMINAL_STATE`）；
//   · 携带 `stop_reason` 的事件必须过 R3-04 矩阵。

import assert from "node:assert/strict";
import test from "node:test";

import {
  RUN_TRANSITION_EDGES,
  applyRunEvent,
  assertRunState,
  initialRunState,
  isTerminalRunStatus,
} from "../dist/index.js";

/** 从初始状态依次应用事件，返回最终状态（任一事件被拒即抛）。 */
function drive(events) {
  let state = initialRunState();
  for (const event of events) {
    const result = applyRunEvent(state, event);
    assert.equal(result.ok, true, `事件 ${event.type} 在 ${state.status} 被拒：${result.detail}`);
    state = result.state;
  }
  return state;
}

test("迁移表恰好 11 条边（含 FAIL / EXHAUST_BUDGET / TIMEOUT 三条 RUNNING→FAILED）", () => {
  assert.equal(RUN_TRANSITION_EDGES.length, 11);
  const toFailed = RUN_TRANSITION_EDGES.filter((e) => e.to === "FAILED").map((e) => e.event);
  assert.deepEqual(toFailed.sort(), ["EXHAUST_BUDGET", "FAIL", "TIMEOUT"]);
});

test("11 条合法迁移各 1 例 —— 状态与 stop_reason 逐条断言", () => {
  const cases = [
    { events: [{ type: "ACQUIRE_LEASE" }], status: "RUNNING", stopReason: null },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "REQUEST_APPROVAL" }], status: "WAITING_APPROVAL", stopReason: null },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "REQUEST_APPROVAL" }, { type: "APPROVE" }], status: "RUNNING", stopReason: null },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "REQUEST_APPROVAL" }, { type: "REJECT" }], status: "CANCELLED", stopReason: "approval_rejected" },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "REQUEST_INPUT" }], status: "WAITING_INPUT", stopReason: null },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "REQUEST_INPUT" }, { type: "PROVIDE_INPUT" }], status: "RUNNING", stopReason: null },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "COMPLETE" }], status: "SUCCEEDED", stopReason: "model_finish" },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "FAIL", stopReason: "tool_failed" }], status: "FAILED", stopReason: "tool_failed" },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "CANCEL" }], status: "CANCELLED", stopReason: "cancelled" },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "EXHAUST_BUDGET", stopReason: "budget_turns" }], status: "FAILED", stopReason: "budget_turns" },
    { events: [{ type: "ACQUIRE_LEASE" }, { type: "TIMEOUT" }], status: "FAILED", stopReason: "wall_time" },
  ];

  assert.equal(cases.length, 11, "用例数必须与迁移表条数一致");
  for (const [index, item] of cases.entries()) {
    const state = drive(item.events);
    assert.equal(state.status, item.status, `case#${index + 1} status`);
    assert.equal(state.stopReason, item.stopReason, `case#${index + 1} stop_reason`);
    assertRunState(state); // 产物必须自洽
  }
});

test("终态后零事件：SUCCEEDED 上任何事件都返回 TERMINAL_STATE", () => {
  const done = drive([{ type: "ACQUIRE_LEASE" }, { type: "COMPLETE" }]);
  assert.equal(isTerminalRunStatus(done.status), true);
  for (const event of [{ type: "ACQUIRE_LEASE" }, { type: "CANCEL" }, { type: "FAIL", stopReason: "tool_failed" }]) {
    const result = applyRunEvent(done, event);
    assert.equal(result.ok, false);
    assert.equal(result.code, "TERMINAL_STATE");
  }
});

test("非法转移 reject：QUEUED 不能直接 COMPLETE / WAITING 不能 CANCEL", () => {
  const queued = initialRunState();
  const r1 = applyRunEvent(queued, { type: "COMPLETE" });
  assert.equal(r1.ok, false);
  assert.equal(r1.code, "ILLEGAL_TRANSITION");
  assert.match(r1.detail, /要求 RUNNING，当前 QUEUED/);

  const waiting = drive([{ type: "ACQUIRE_LEASE" }, { type: "REQUEST_APPROVAL" }]);
  const r2 = applyRunEvent(waiting, { type: "CANCEL" });
  assert.equal(r2.ok, false);
  assert.equal(r2.code, "ILLEGAL_TRANSITION");
});

test("stop_reason 载荷必须过矩阵：FAIL(model_finish) / EXHAUST_BUDGET(tool_failed) 均拒", () => {
  const running = drive([{ type: "ACQUIRE_LEASE" }]);

  const r1 = applyRunEvent(running, { type: "FAIL", stopReason: "model_finish" });
  assert.equal(r1.ok, false);
  assert.equal(r1.code, "ILLEGAL_STOP_REASON");

  const r2 = applyRunEvent(running, { type: "EXHAUST_BUDGET", stopReason: "tool_failed" });
  assert.equal(r2.ok, false);
  assert.equal(r2.code, "ILLEGAL_STOP_REASON");

  // 预算四项都合法（这里抽两项）
  for (const reason of ["budget_turns", "budget_cost"]) {
    const ok = applyRunEvent(running, { type: "EXHAUST_BUDGET", stopReason: reason });
    assert.equal(ok.ok, true, `${reason} 应被接受`);
    assert.equal(ok.state.stopReason, reason);
  }
});

test("assertRunState：非终态带 stop_reason / 终态缺 stop_reason 都抛", () => {
  assert.throws(() => assertRunState({ status: "RUNNING", stopReason: "model_finish" }), /不得携带|不匹配/);
  assert.throws(() => assertRunState({ status: "SUCCEEDED", stopReason: null }), /stop_reason 非法|不匹配/);
  assert.doesNotThrow(() => assertRunState({ status: "QUEUED", stopReason: null }));
});
