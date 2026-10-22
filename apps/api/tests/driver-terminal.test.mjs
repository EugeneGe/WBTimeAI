/**
 * AUD-10 · `terminalOf` 的**安全阶段消费**（P3）。
 *
 * 被修复的缺陷
 * ----------
 *   `RunFlags.safetyBlockedStage` 在 `driver.ts` 里**5 处写、0 处读**：
 *   S2/S4/S5/S6/S7 的装饰器都会把它置成挂点名，但没有任何代码消费它 ⇒
 *   "哪个挂点拦的"在终态行里不可见（`error_type` 的取值域是冻结的 11 值，
 *   **没有**安全码，所以它只能落在 `error` 文本里）。
 *
 * 判据
 * ----
 *   ① 非空 stage + **非成功**终局 ⇒ `error` 前缀成 `[安全拦截@<stage>] <原错误>`；
 *   ② `errorType` **保持原取值**（不新增码：R3-04 的 11 值冻结）；
 *   ③ 成功终局**不加前缀**（成功行不该带安全错误文本）；
 *   ④ stage 为空 ⇒ 原样返回（不做任何字符串加工）；
 *   ⑤ `SafetyBlockedError` 的 message 已含挂点名 ⇒ **不重复加前缀**（避免复读）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/driver-terminal.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { terminalOf } from "../dist/modules/run/driver.js";

/** 一个"失败"的内核终局（`FAILED` + `tool_failed`）。 */
const FAILED_OUTCOME = Object.freeze({
  status: "FAILED",
  stopReason: "tool_failed",
  turns: 2,
  toolCalls: 1,
  detail: "模型给出失败终局",
});

test("① 非空 stage + 失败终局 ⇒ error 前缀 [安全拦截@<stage>]，errorType 不变", () => {
  const terminal = terminalOf(FAILED_OUTCOME, "工具入参被安全策略拦截：命中 x", "RUN_EXECUTION_ERROR", {
    approvalRejected: false,
    safetyBlockedStage: "tool_args",
  });

  assert.equal(terminal.status, "FAILED");
  assert.equal(terminal.error, "[安全拦截@tool_args] 工具入参被安全策略拦截：命中 x");
  assert.equal(
    terminal.errorType,
    "RUN_EXECUTION_ERROR",
    "error_type 的取值域冻结（R3-04 的 11 值里没有安全码）—— 不得自造"
  );
  assert.equal(terminal.stopReason, "tool_failed", "stop_reason 也不因加前缀而变");
});

test("② 审批驳回分支同样消费 stage（CANCELLED 终局）", () => {
  const terminal = terminalOf(null, null, null, {
    approvalRejected: true,
    safetyBlockedStage: "output",
  });
  assert.equal(terminal.status, "CANCELLED");
  assert.equal(terminal.stopReason, "approval_rejected");
  assert.equal(terminal.error, "[安全拦截@output] 工具调用未获审批");
});

test("③ 成功终局**不加**前缀（成功行不带安全错误文本）", () => {
  const terminal = terminalOf(
    Object.freeze({ status: "SUCCEEDED", stopReason: "model_finish", turns: 1, toolCalls: 0, detail: "ok" }),
    null,
    null,
    { approvalRejected: false, safetyBlockedStage: "tool_result" }
  );
  assert.equal(terminal.status, "SUCCEEDED");
  assert.equal(terminal.error, null, "成功态的 error 必须是 null");
});

test("④ stage 为空 ⇒ 原样返回（不做字符串加工）", () => {
  const terminal = terminalOf(FAILED_OUTCOME, "原始错误", "RUN_EXECUTION_ERROR", {
    approvalRejected: false,
    safetyBlockedStage: null,
  });
  assert.equal(terminal.error, "原始错误");
});

test("⑤ SafetyBlockedError 的 message 已带挂点名 ⇒ 不重复加前缀", () => {
  // `SafetyBlockedError` 的 message 形态：`安全拦截（context）：命中 ...`
  const terminal = terminalOf(null, "安全拦截（context）：命中注入模式", "SAFETY_DENIED", {
    approvalRejected: false,
    safetyBlockedStage: "context",
  });
  assert.equal(terminal.error, "安全拦截（context）：命中注入模式", "不得变成 [安全拦截@context] 安全拦截（context）：…");
  assert.equal(terminal.errorType, "SAFETY_DENIED");
});
