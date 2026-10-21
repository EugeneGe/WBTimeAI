// @wbtime/domain · Run 状态值域（v0019 的 7 值）与 py/ 线映射表。
//
// 来源（唯一真相源）：
//   · `contracts/v0019.README.md` §2 第 3 行 —— `RunResponse.status` / `RunOut.status`
//     显式 7 值枚举，默认 `QUEUED`；
//   · `00-施工期裁定.md` R3-02 —— py/ 线是 **5 值**且词表不兼容（`SUCCESS`≠`SUCCEEDED`、
//     `PENDING`≠`QUEUED`、无暂停态），跨线比对**必须**经本文件的映射表。
//
// 为什么单独一个文件（而不是塞进 `run-state.ts`）：
//   `run-stop-reason.ts` 与 `run-state.ts` 都需要状态值域，若把常量放在任一者里就会成环。
//   本文件是纯常量 + 纯判定，不引任何其它 runtime 模块。

/** Run 状态（v0019 契约 7 值，顺序与 `RunResponse.status.enum` 逐字一致）。 */
export const RUN_STATUSES = [
  "QUEUED",
  "RUNNING",
  "WAITING_APPROVAL",
  "WAITING_INPUT",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
] as const;

export type RunStatus = (typeof RUN_STATUSES)[number];

/** 终态（不可再转移；终态后零事件 —— Harness §1-5）。 */
export const TERMINAL_RUN_STATUSES = ["SUCCEEDED", "FAILED", "CANCELLED"] as const;

/** 可恢复暂停态：期间 `BudgetLedger.pause()`，墙钟预算不增长（R3-07）。 */
export const SUSPENDED_RUN_STATUSES = ["WAITING_APPROVAL", "WAITING_INPUT"] as const;

/** 是否终态。 */
export function isTerminalRunStatus(status: RunStatus): boolean {
  return (TERMINAL_RUN_STATUSES as readonly string[]).includes(status);
}

/** 是否可恢复暂停态。 */
export function isSuspendedRunStatus(status: RunStatus): boolean {
  return (SUSPENDED_RUN_STATUSES as readonly string[]).includes(status);
}

// ---------------------------------------------------------------------------
// py/ 线映射（仅用于**跨线比对**，不得用于业务判定）
// ---------------------------------------------------------------------------

/** py/ 线 `run.status` 的 5 值（`_old/.../wbtime_ai_domain/constants.py:95-100` 实测）。 */
export const PY_RUN_STATUSES = ["PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED"] as const;

export type PyRunStatus = (typeof PY_RUN_STATUSES)[number];

/**
 * py → TS 映射表。
 *
 * **禁止**写成"与 py 线逐字一致"（R3-02 ③）：两者词表不同，只是经此表后语义等价。
 */
export const RUN_STATUS_MAP_PY_TO_TS: Readonly<Record<PyRunStatus, RunStatus>> = Object.freeze({
  PENDING: "QUEUED",
  RUNNING: "RUNNING",
  SUCCESS: "SUCCEEDED",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
});

/** TS 侧**没有 py 对应值**的状态 —— 跨线比对时必须显式跳过，不得判"多了一个状态"。 */
export const RUN_STATUSES_WITHOUT_PY_COUNTERPART = ["WAITING_APPROVAL", "WAITING_INPUT"] as const;

/** 把 py 状态映射为 TS 状态；未知值返回 `null`（不抛错，便于比对器判"未知"）。 */
export function toTsRunStatus(value: string): RunStatus | null {
  return (RUN_STATUS_MAP_PY_TO_TS as Readonly<Record<string, RunStatus>>)[value] ?? null;
}
