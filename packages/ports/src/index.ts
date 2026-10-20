// @wbtime/ports · 包出口。
//
// 分层铁律：本包 **只有端口接口 + 空实现**，不引入 Redis / BullMQ / APScheduler
// 等真实依赖（运行时依赖为空）；**不 import `apps/*`**。

export { CONFIGURATION_ERROR_HTTP_STATUS, PORTS_ERROR_CODES, PortsNotEnabledError } from "./errors.js";
export type { PortsErrorCode } from "./errors.js";

export type { QueueItem, QueuePort } from "./queue/queue-port.js";
export type { ScheduledJob, SchedulerPort } from "./queue/scheduler-port.js";

export {
  ASSEMBLY_REGISTRY,
  BACKGROUND_EXECUTOR_CAPABILITY,
  QUEUE_CAPABILITY,
  SCHEDULER_CAPABILITY,
  isQueueEnabled,
  isSchedulerEnabled,
} from "./queue/capability.js";
export type { CapabilityFlag } from "./queue/capability.js";

export { NOOP_QUEUE_ERROR_CODE, createNoopQueue, noopQueue } from "./queue/noop-queue.js";
export { NOOP_SCHEDULER_ERROR_CODE, createNoopScheduler, noopScheduler } from "./queue/noop-scheduler.js";
