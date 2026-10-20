// @wbtime/ports · 调度器端口 **空实现**（同 `noop-queue.ts` 的行为契约）。

import { SCHEDULER_CAPABILITY } from "./capability.js";
import { PortsNotEnabledError, type PortsErrorCode } from "../errors.js";
import type { SchedulerPort } from "./scheduler-port.js";

function raise(operation: string): never {
  throw new PortsNotEnabledError(
    operation,
    SCHEDULER_CAPABILITY.feature,
    SCHEDULER_CAPABILITY.availableIn,
  );
}

/** 构造调度器空实现。 */
export function createNoopScheduler(): SchedulerPort {
  return Object.freeze({
    scheduleOnce: async (): Promise<string> => raise("scheduleOnce"),
    start: async (): Promise<void> => raise("start"),
    shutdown: async (): Promise<void> => raise("shutdown"),
  });
}

/** 空实现抛出的错误码。 */
export const NOOP_SCHEDULER_ERROR_CODE: PortsErrorCode = "CONFIGURATION_ERROR";

/** 默认导出的单例空实现（组合根装配用）。 */
export const noopScheduler: SchedulerPort = createNoopScheduler();
