// @wbtime/domain · T3-04 tool_call 状态与“终态后无悬空调用”测试（R3-03）。
//
// 判据：7 值（py 5 + CANCELLED/UNKNOWN 登记）；终态集合 5；run 终态后 PENDING/RUNNING ⇒ 抛错；
//       非终态 run 不误报。

import assert from "node:assert/strict";
import test from "node:test";

import {
  TERMINAL_TOOL_CALL_STATUSES,
  TOOL_CALL_STATUSES,
  assertNoDanglingToolCalls,
  assertToolCallStatus,
  findDanglingToolCalls,
  isTerminalToolCallStatus,
} from "../dist/index.js";

test("7 值 = py 5 值 + CANCELLED / UNKNOWN", () => {
  assert.deepEqual([...TOOL_CALL_STATUSES], [
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "FAILED",
    "DENIED",
    "CANCELLED",
    "UNKNOWN",
  ]);
  assert.deepEqual([...TERMINAL_TOOL_CALL_STATUSES], [
    "SUCCESS",
    "FAILED",
    "DENIED",
    "CANCELLED",
    "UNKNOWN",
  ]);
  assert.equal(TOOL_CALL_STATUSES.length, 7);
});

test("终态判定：PENDING / RUNNING 不是终态，其余 5 值都是", () => {
  for (const status of TOOL_CALL_STATUSES) {
    assert.equal(isTerminalToolCallStatus(status), status !== "PENDING" && status !== "RUNNING", status);
  }
  assert.throws(() => assertToolCallStatus("SUCCEEDED"), /未知 tool_call\.status/);
  assert.doesNotThrow(() => assertToolCallStatus("UNKNOWN"));
});

test("run 终态后仍有 PENDING / RUNNING ⇒ 抛错，并列出调用 id", () => {
  const calls = [
    { id: "c1", status: "SUCCESS" },
    { id: "c2", status: "RUNNING" },
    { id: "c3", status: "PENDING" },
  ];
  assert.deepEqual([...findDanglingToolCalls("SUCCEEDED", calls)], ["c2", "c3"]);
  assert.throws(() => assertNoDanglingToolCalls("FAILED", calls), /仍有 2 个未终态的 tool call/);
});

test("run 非终态：在途调用不算悬空（不误报）", () => {
  const calls = [{ id: "c1", status: "RUNNING" }];
  assert.deepEqual([...findDanglingToolCalls("RUNNING", calls)], []);
  assert.doesNotThrow(() => assertNoDanglingToolCalls("WAITING_APPROVAL", calls));
});

test("run 终态 + 全部调用终态 ⇒ 通过（含 UNKNOWN，它也是终态）", () => {
  const calls = [
    { id: "c1", status: "SUCCESS" },
    { id: "c2", status: "UNKNOWN" },
    { id: "c3", status: "DENIED" },
  ];
  assert.doesNotThrow(() => assertNoDanglingToolCalls("CANCELLED", calls));
});
