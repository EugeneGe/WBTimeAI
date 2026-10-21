// @wbtime/domain · T3-04 Run 状态值域与 py 映射测试（R3-02）。
//
// 判据：7 值 / 5 值、映射逐条、暂停态在 py 侧无对应、未知值返回 null（不抛）。

import assert from "node:assert/strict";
import test from "node:test";

import {
  PY_RUN_STATUSES,
  RUN_STATUSES,
  RUN_STATUSES_WITHOUT_PY_COUNTERPART,
  RUN_STATUS_MAP_PY_TO_TS,
  SUSPENDED_RUN_STATUSES,
  TERMINAL_RUN_STATUSES,
  isSuspendedRunStatus,
  isTerminalRunStatus,
  toTsRunStatus,
} from "../dist/index.js";

test("v0019 契约 7 值，顺序与 RunResponse.status.enum 一致", () => {
  assert.deepEqual([...RUN_STATUSES], [
    "QUEUED",
    "RUNNING",
    "WAITING_APPROVAL",
    "WAITING_INPUT",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
  ]);
});

test("终态 3 / 暂停态 2，且互不重叠", () => {
  assert.deepEqual([...TERMINAL_RUN_STATUSES], ["SUCCEEDED", "FAILED", "CANCELLED"]);
  assert.deepEqual([...SUSPENDED_RUN_STATUSES], ["WAITING_APPROVAL", "WAITING_INPUT"]);
  for (const status of TERMINAL_RUN_STATUSES) assert.equal(isTerminalRunStatus(status), true);
  for (const status of SUSPENDED_RUN_STATUSES) {
    assert.equal(isSuspendedRunStatus(status), true);
    assert.equal(isTerminalRunStatus(status), false);
  }
});

test("py 5 值的映射逐条（PENDING→QUEUED / SUCCESS→SUCCEEDED 是重点）", () => {
  assert.equal(PY_RUN_STATUSES.length, 5);
  assert.deepEqual({ ...RUN_STATUS_MAP_PY_TO_TS }, {
    PENDING: "QUEUED",
    RUNNING: "RUNNING",
    SUCCESS: "SUCCEEDED",
    FAILED: "FAILED",
    CANCELLED: "CANCELLED",
  });
  for (const py of PY_RUN_STATUSES) {
    assert.equal(toTsRunStatus(py), RUN_STATUS_MAP_PY_TO_TS[py]);
  }
});

test("暂停态在 py 侧无对应（跨线比对必须跳过，不得判“多了状态”）", () => {
  assert.deepEqual([...RUN_STATUSES_WITHOUT_PY_COUNTERPART], ["WAITING_APPROVAL", "WAITING_INPUT"]);
  const mapped = new Set(Object.values(RUN_STATUS_MAP_PY_TO_TS));
  for (const status of RUN_STATUSES_WITHOUT_PY_COUNTERPART) {
    assert.equal(mapped.has(status), false, `${status} 不应出现在 py 映射的值域里`);
  }
  // 映射值域 ∪ 无对应集合 == 全部 7 值
  assert.equal(new Set([...mapped, ...RUN_STATUSES_WITHOUT_PY_COUNTERPART]).size, RUN_STATUSES.length);
});

test("未知 py 值返回 null（比对器可判“未知”而不是崩）", () => {
  assert.equal(toTsRunStatus("SUCCESS "), null);
  assert.equal(toTsRunStatus("BUDGET_EXHAUSTED"), null);
  assert.equal(toTsRunStatus(""), null);
});
