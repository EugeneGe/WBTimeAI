// @wbtime/domain · `tool_call.status`（7 值）与"终态后无悬空调用"不变量。
//
// 来源：`00-施工期裁定.md` **R3-03** —— `tool_call.status` 不在冻结 OpenAPI 内
// （`ToolCall` 不是 schema 对象），故**反向保留 py/ 线词表**（5 值）+ 登记 2 值：
//   py 原值：`PENDING / RUNNING / SUCCESS / FAILED / DENIED`
//   新增两值：`CANCELLED`（取消传播致中断）/ `UNKNOWN`（崩溃后外部结果未知，待恢复）
// 保留 py 词表的目的：DoD#5 的 `code_exec` 等价性可直接逐字比较，少一层映射。

import { DOMAIN_ERROR_CODES, DomainError } from "../errors.js";
import { isTerminalRunStatus, type RunStatus } from "./run-status.js";

/** 工具调用状态（7 值；顺序与 R3-03 登记一致）。 */
export const TOOL_CALL_STATUSES = [
  "PENDING",
  "RUNNING",
  "SUCCESS",
  "FAILED",
  "DENIED",
  "CANCELLED",
  "UNKNOWN",
] as const;

export type ToolCallStatus = (typeof TOOL_CALL_STATUSES)[number];

/** 终态（恰有一条终态 —— Harness §1-2）。 */
export const TERMINAL_TOOL_CALL_STATUSES = [
  "SUCCESS",
  "FAILED",
  "DENIED",
  "CANCELLED",
  "UNKNOWN",
] as const;

/** 是否工具调用终态。 */
export function isTerminalToolCallStatus(status: ToolCallStatus): boolean {
  return (TERMINAL_TOOL_CALL_STATUSES as readonly string[]).includes(status);
}

/** 断言状态值合法（写入第 8 值 ⇒ 抛错）。 */
export function assertToolCallStatus(value: string): asserts value is ToolCallStatus {
  if (!(TOOL_CALL_STATUSES as readonly string[]).includes(value)) {
    throw new DomainError(`未知 tool_call.status：${value}`, DOMAIN_ERROR_CODES.VALIDATION_ERROR, {
      status: value,
      allowed: TOOL_CALL_STATUSES,
    });
  }
}

/** 判定所需的最小视图（不依赖 DB 行形状 —— 域层禁止定义行结构）。 */
export interface ToolCallStatusView {
  readonly id: string;
  readonly status: ToolCallStatus;
}

/** 找出悬空的调用（run 已终态，但调用仍在 `PENDING` / `RUNNING`）。 */
export function findDanglingToolCalls(
  runStatus: RunStatus,
  calls: readonly ToolCallStatusView[],
): readonly string[] {
  if (!isTerminalRunStatus(runStatus)) return [];
  return calls.filter((call) => !isTerminalToolCallStatus(call.status)).map((call) => call.id);
}

/**
 * 断言「run 终态后不得存在 `PENDING` / `RUNNING` 的 tool call」（R3-03 判据 ②）。
 *
 * 非终态 run 允许存在在途调用（正常执行中），故本断言只在终态生效。
 */
export function assertNoDanglingToolCalls(
  runStatus: RunStatus,
  calls: readonly ToolCallStatusView[],
): void {
  const dangling = findDanglingToolCalls(runStatus, calls);
  if (dangling.length > 0) {
    throw new DomainError(
      `run 已终态（${runStatus}）但仍有 ${dangling.length} 个未终态的 tool call`,
      DOMAIN_ERROR_CODES.VALIDATION_ERROR,
      { runStatus, dangling },
    );
  }
}
