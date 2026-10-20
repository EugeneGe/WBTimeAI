// @wbtime/domain · 包出口。
//
// 分层铁律：本包 **零 ORM import、零 Web import**（R1），且 **不 import `apps/*`**。
// 运行时依赖为空（dependencies: {}）。

export { DOMAIN_ERROR_CODES, DomainError, invariant } from "./errors.js";
export type { DomainErrorCode } from "./errors.js";

export {
  ALLOWED_TRANSITIONS,
  TERMINAL_STATUSES,
  TASK_STATUSES,
  assertTransition,
  canTransition,
} from "./task/task-status.js";
export type { TaskStatus } from "./task/task-status.js";

export { DEFAULT_EXECUTION_MODE, TASK_EXECUTION_MODES } from "./task/task-execution-mode.js";
export type { TaskExecutionMode } from "./task/task-execution-mode.js";

export { TASK_COLUMN_LIMITS, TASK_ERROR_CODES, Task, TaskDomainError } from "./task/task.js";
export type {
  JsonValue,
  TaskCreateInput,
  TaskProps,
  TaskRecord,
} from "./task/task.js";
