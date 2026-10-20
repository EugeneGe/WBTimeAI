// @wbtime/domain · Task 执行模式枚举。
//
// ⚠️ 取值来源声明（实测）：冻结契约 `task.execution_mode` 为 `VARCHAR(20) NOT NULL`
// （`contracts/schema.v0018.pg.sql:779`），**无 CHECK / 无 enum、无 DB 默认值**；
// 值域取自旧线 `WBTimeAI_old/packages/task/src/wbtime_ai_task/models.py:42`
// 的 `execution_mode: str = "INLINE"` 与 `workflow_service.py` 的
// `EXECUTION_MODE_INLINE` / `EXECUTION_MODE_QUEUED` 实测用法。
// ⇒ 契约只保证「非空 + ≤20 字符」；默认值 `INLINE` 是 **域层默认**，不是 DB 默认。

export const TASK_EXECUTION_MODES = ["INLINE", "QUEUED"] as const;

export type TaskExecutionMode = (typeof TASK_EXECUTION_MODES)[number];

/** 域层默认执行模式（对应旧线 models.py 默认值）。 */
export const DEFAULT_EXECUTION_MODE: TaskExecutionMode = "INLINE";
