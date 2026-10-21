// @wbtime/domain · `stop_reason`（11 值）与 `status × stop_reason` 合法矩阵。
//
// 来源（唯一真相源）：
//   · `contracts/v0019.README.md` §2 第 2 行 —— `RunResponse.stop_reason` / `RunOut.stop_reason`
//     为 `string | null`，11 值写在描述里；
//   · `00-施工期裁定.md` **R3-04** —— DB 列可空，**应用层强制**：非终态必须 NULL、
//     `SUCCEEDED` 只允许 `model_finish`、`FAILED` 8 值、`CANCELLED` 2 值（1+8+2 = 11）；
//   · **R3-01** —— `BUDGET_EXHAUSTED` / `TIMED_OUT` 不是状态，折叠为 `FAILED` + 对应 `stop_reason`，
//     四项预算的**互斥优先序**：`turns > tools > tokens > cost`。
//
// 纯常量 + 纯函数；零 ORM / 零 Web / 不写库。

import { DOMAIN_ERROR_CODES, DomainError } from "../errors.js";
import { isTerminalRunStatus, type RunStatus } from "./run-status.js";

/** `stop_reason` 的 11 个取值（顺序与 v0019 描述一致）。 */
export const STOP_REASONS = [
  "model_finish",
  "tool_failed",
  "approval_rejected",
  "cancelled",
  "budget_tokens",
  "budget_cost",
  "budget_turns",
  "budget_tools",
  "wall_time",
  "provider_error",
  "unknown_recovery",
] as const;

export type StopReason = (typeof STOP_REASONS)[number];

/** 三个终态（与 `run-status.ts` 的 `TERMINAL_RUN_STATUSES` 同源；此处只用于矩阵键类型）。 */
type TerminalRunStatus = "SUCCEEDED" | "FAILED" | "CANCELLED";

/**
 * 每个**终态**允许的 `stop_reason`（R3-04 矩阵，逐值枚举）。
 *
 * 非终态不出现在此表里 —— 它们的约束是「必须为 `null`」。
 */
export const STOP_REASONS_BY_TERMINAL_STATUS: Readonly<
  Record<TerminalRunStatus, readonly StopReason[]>
> = Object.freeze({
  SUCCEEDED: Object.freeze(["model_finish"] as const),
  FAILED: Object.freeze([
    "tool_failed",
    "provider_error",
    "unknown_recovery",
    "budget_tokens",
    "budget_cost",
    "budget_turns",
    "budget_tools",
    "wall_time",
  ] as const),
  CANCELLED: Object.freeze(["cancelled", "approval_rejected"] as const),
});

/** 四项预算耗尽的**互斥优先序**（R3-01：turns > tools > tokens > cost，同轮多触发取最先命中者）。 */
export const BUDGET_STOP_REASON_PRIORITY = [
  "budget_turns",
  "budget_tools",
  "budget_tokens",
  "budget_cost",
] as const;

export type BudgetStopReason = (typeof BUDGET_STOP_REASON_PRIORITY)[number];

/** 查询某状态下允许的 `stop_reason`；非终态返回 `null`（语义 = 只能为空）。 */
export function allowedStopReasons(status: RunStatus): readonly StopReason[] | null {
  if (!isTerminalRunStatus(status)) return null;
  return STOP_REASONS_BY_TERMINAL_STATUS[status as TerminalRunStatus];
}

/** 判断组合是否合法（非终态 + `null` 合法；终态 + 表内值合法）。 */
export function isStopReasonAllowed(status: RunStatus, stopReason: StopReason | null): boolean {
  const allowed = allowedStopReasons(status);
  if (allowed === null) return stopReason === null;
  return stopReason !== null && allowed.includes(stopReason);
}

/**
 * 断言 `status × stop_reason` 合法，否则抛 `VALIDATION_ERROR`。
 *
 * 用于**写入前**（服务层）与**读取后序列化前**（`GET /runs/{id}`）两处 —— R3-04 要求双端断言，
 * 且**不得静默置空**。
 */
export function assertStopReason(status: RunStatus, stopReason: StopReason | null): void {
  if (isStopReasonAllowed(status, stopReason)) return;
  const allowed = allowedStopReasons(status);
  throw new DomainError(
    allowed === null
      ? `非终态 run（${status}）不得携带 stop_reason，实际为 ${String(stopReason)}`
      : `终态 ${status} 的 stop_reason 非法：${String(stopReason)}；允许值 = ${allowed.join(" / ")}`,
    DOMAIN_ERROR_CODES.VALIDATION_ERROR,
    { status, stopReason, allowed: allowed ?? [] },
  );
}

/** 四项预算的命中标记（调用方按实际耗尽项传 `true`）。 */
export interface BudgetExhaustionFlags {
  readonly turns?: boolean;
  readonly tools?: boolean;
  readonly tokens?: boolean;
  readonly cost?: boolean;
}

/**
 * 按 R3-01 的优先序从命中项里挑出**唯一**的 `stop_reason`。
 *
 * 返回 `null` 表示四项都没耗尽（调用方不应据此进终态）。
 */
export function pickBudgetStopReason(flags: BudgetExhaustionFlags): BudgetStopReason | null {
  for (const reason of BUDGET_STOP_REASON_PRIORITY) {
    const hit = flags[reason.slice("budget_".length) as keyof BudgetExhaustionFlags];
    if (hit === true) return reason;
  }
  return null;
}
