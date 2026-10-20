// @wbtime/ports · 队列端口 **空实现**。
//
// 纪律：V0.1.0 **严禁**实现真实队列（Redis / BullMQ / arq / 进程内队列均不可）。
// 空实现的行为契约（对应 DoD#4 E-2 判据）：
//   - 接口面完整（组合根不会缺键）；
//   - **任何调用都抛** `PortsNotEnabledError`（`code = "CONFIGURATION_ERROR"`），
//     **不**返回 `undefined`、**不**静默成功。

import { QUEUE_CAPABILITY } from "./capability.js";
import { PortsNotEnabledError, type PortsErrorCode } from "../errors.js";
import type { QueueItem, QueuePort } from "./queue-port.js";

function raise(operation: string): never {
  throw new PortsNotEnabledError(
    operation,
    QUEUE_CAPABILITY.feature,
    QUEUE_CAPABILITY.availableIn,
  );
}

/** 构造队列空实现。 */
export function createNoopQueue<T extends QueueItem = QueueItem>(): QueuePort<T> {
  // 一律 `async`：错误以 **rejected promise** 抛出（端口面本身是异步的），
  // 使 `await queue.enqueue(...)` 必抛，且 `assert.rejects` 可断言。
  return Object.freeze({
    enqueue: async (): Promise<void> => raise("enqueue"),
    dequeue: async (): Promise<T | null> => raise("dequeue"),
    ack: async (): Promise<void> => raise("ack"),
    size: async (): Promise<number> => raise("size"),
  });
}

/** 空实现抛出的错误码（便于测试与台账断言）。 */
export const NOOP_QUEUE_ERROR_CODE: PortsErrorCode = "CONFIGURATION_ERROR";

/** 默认导出的单例空实现（组合根装配用）。 */
export const noopQueue: QueuePort = createNoopQueue();
