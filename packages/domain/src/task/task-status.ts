// @wbtime/domain · Task 状态枚举与状态机。
//
// ⚠️ 取值来源声明（实测）：
//   - 冻结契约 `contracts/schema.v0018.pg.normalized.json` 的 `task.status` 列是
//     `VARCHAR(50) NOT NULL`，**没有 CHECK 约束、没有 PG enum**（已在
//     `contracts/schema.v0018.pg.sql:771-786` 复核，DDL 中无任何 CHECK/enum）。
//   - 因此本枚举的值域 **不是契约给出的**，而是取自旧线实现
//     `WBTimeAI_old/packages/task/src/wbtime_ai_task/states.py:26-52` 的
//     `TaskStatus`（6 值）与转移表；DB 层面只约束「非空 + ≤50 字符」。
//   ⇒ 若后续版本裁定值域变化，须同步改此处并在施工记录登记。

import { DOMAIN_ERROR_CODES, DomainError } from "../errors.js";

/** Task 状态值域（旧线 states.py 实测 6 值）。 */
export const TASK_STATUSES = [
  "CREATED",
  "PENDING",
  "RUNNING",
  "SUCCESS",
  "FAILED",
  "CANCELLED",
] as const;

export type TaskStatus = (typeof TASK_STATUSES)[number];

/** 合法状态转移表（当前状态 → 允许的下一状态集合）。 */
export const ALLOWED_TRANSITIONS: Readonly<Record<TaskStatus, readonly TaskStatus[]>> =
  Object.freeze({
    // CREATED → RUNNING 为 INLINE 路径（跳过 PENDING）。
    CREATED: Object.freeze(["PENDING", "RUNNING", "CANCELLED"] as const),
    PENDING: Object.freeze(["RUNNING", "CANCELLED", "FAILED"] as const),
    RUNNING: Object.freeze(["SUCCESS", "FAILED", "CANCELLED"] as const),
    SUCCESS: Object.freeze([] as const),
    FAILED: Object.freeze([] as const),
    CANCELLED: Object.freeze([] as const),
  });

/** 终态集合（不可再转移）。 */
export const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set<TaskStatus>([
  "SUCCESS",
  "FAILED",
  "CANCELLED",
]);

/** 判断 `from → to` 是否为合法转移。 */
export function canTransition(from: TaskStatus, to: TaskStatus): boolean {
  return ALLOWED_TRANSITIONS[from].includes(to);
}

/** 断言转移合法，否则抛 DomainError（VALIDATION_ERROR）。 */
export function assertTransition(from: TaskStatus, to: TaskStatus): void {
  if (!canTransition(from, to)) {
    throw new DomainError(
      `非法任务状态转移：${from} → ${to}`,
      DOMAIN_ERROR_CODES.VALIDATION_ERROR,
      { from, to },
    );
  }
}
