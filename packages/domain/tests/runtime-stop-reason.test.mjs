// @wbtime/domain · T3-04 `stop_reason` 矩阵测试（R3-04 + R3-01）。
//
// 判据（任务卡 T3-04 验收口径 ②）四例：
//   终态缺值 ⇒ 抛；非终态写值 ⇒ 抛；`SUCCEEDED + tool_failed` ⇒ 抛；`CANCELLED` 两值各 1 例通过。
// 另断言 11 值全覆盖（1 + 8 + 2）与四项预算的互斥优先序（turns > tools > tokens > cost）。

import assert from "node:assert/strict";
import test from "node:test";

import {
  BUDGET_STOP_REASON_PRIORITY,
  RUN_STATUSES,
  STOP_REASONS,
  STOP_REASONS_BY_TERMINAL_STATUS,
  allowedStopReasons,
  assertStopReason,
  isStopReasonAllowed,
  pickBudgetStopReason,
} from "../dist/index.js";

test("11 个 stop_reason 与三个终态的分配 = 1 + 8 + 2，且无遗漏无重复", () => {
  assert.equal(STOP_REASONS.length, 11);
  const grouped = [
    ...STOP_REASONS_BY_TERMINAL_STATUS.SUCCEEDED,
    ...STOP_REASONS_BY_TERMINAL_STATUS.FAILED,
    ...STOP_REASONS_BY_TERMINAL_STATUS.CANCELLED,
  ];
  assert.equal(STOP_REASONS_BY_TERMINAL_STATUS.SUCCEEDED.length, 1);
  assert.equal(STOP_REASONS_BY_TERMINAL_STATUS.FAILED.length, 8);
  assert.equal(STOP_REASONS_BY_TERMINAL_STATUS.CANCELLED.length, 2);
  assert.equal(grouped.length, 11);
  assert.deepEqual([...grouped].sort(), [...STOP_REASONS].sort(), "11 值必须被三个终态恰好覆盖一次");
});

test("非终态 ⇒ allowedStopReasons 为 null（只能为空）", () => {
  for (const status of ["QUEUED", "RUNNING", "WAITING_APPROVAL", "WAITING_INPUT"]) {
    assert.equal(allowedStopReasons(status), null, status);
    assert.equal(isStopReasonAllowed(status, null), true, `${status} + null 应合法`);
  }
});

test("四例矩阵", () => {
  // ① 终态缺值 ⇒ 抛
  assert.throws(() => assertStopReason("SUCCEEDED", null), /stop_reason 非法/);
  assert.throws(() => assertStopReason("FAILED", null), /stop_reason 非法/);
  assert.throws(() => assertStopReason("CANCELLED", null), /stop_reason 非法/);

  // ② 非终态写值 ⇒ 抛
  assert.throws(() => assertStopReason("RUNNING", "model_finish"), /不得携带/);
  assert.throws(() => assertStopReason("WAITING_APPROVAL", "cancelled"), /不得携带/);

  // ③ SUCCEEDED + tool_failed ⇒ 抛（工具失败不能算成功）
  assert.throws(() => assertStopReason("SUCCEEDED", "tool_failed"), /SUCCEEDED 的 stop_reason 非法/);

  // ④ CANCELLED 的两个允许值各 1 例通过
  assert.doesNotThrow(() => assertStopReason("CANCELLED", "cancelled"));
  assert.doesNotThrow(() => assertStopReason("CANCELLED", "approval_rejected"));
});

test("每个合法组合都通过，且没有越界组合溜过", () => {
  for (const status of RUN_STATUSES) {
    const allowed = allowedStopReasons(status);
    for (const reason of STOP_REASONS) {
      const expected = allowed === null ? false : allowed.includes(reason);
      assert.equal(isStopReasonAllowed(status, reason), expected, `${status}+${reason}`);
    }
  }
});

test("预算四项优先序：turns > tools > tokens > cost", () => {
  assert.equal(pickBudgetStopReason({ cost: true }), "budget_cost");
  assert.equal(pickBudgetStopReason({ tokens: true, cost: true }), "budget_tokens");
  assert.equal(pickBudgetStopReason({ tools: true, tokens: true, cost: true }), "budget_tools");
  assert.equal(
    pickBudgetStopReason({ turns: true, tools: true, tokens: true, cost: true }),
    "budget_turns",
  );
  assert.equal(pickBudgetStopReason({}), null);
  assert.deepEqual([...BUDGET_STOP_REASON_PRIORITY], [
    "budget_turns",
    "budget_tools",
    "budget_tokens",
    "budget_cost",
  ]);
});
