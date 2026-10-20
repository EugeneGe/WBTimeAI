// @wbtime/ports · 装配登记（「该装配分支未启用」的机器可读判据载体）。
//
// 背景（路线图 M-05 逆流边 E-2）：旧线 `config/providers.py` 以**延迟导入**装配
// 队列 / 调度工厂（实测行号：`:440` create_inprocess_task_queue、`:447`
// InProcessBackgroundExecutor、`:454` create_local_scheduler、`:517`
// RedisTaskQueue/redis_available），P1 闭版时组合根会缺键。
// V0.1.0 只交付 **端口 + 空实现**，真实实现归 **V0.5.0**。

/** 能力开关登记项。 */
export interface CapabilityFlag {
  /** 能力名。 */
  readonly feature: string;
  /** 本版是否启用。 */
  readonly enabled: boolean;
  /** 真实实现的目标版本。 */
  readonly availableIn: string;
  /** 未启用原因。 */
  readonly reason: string;
}

/** 任务队列能力登记：**未启用**。 */
export const QUEUE_CAPABILITY: CapabilityFlag = Object.freeze({
  feature: "task-queue",
  enabled: false,
  availableIn: "V0.5.0",
  reason: "V0.1.0 仅交付端口接口 + 空实现；队列真实实现（Redis/Arq 或进程内）归 V0.5.0。",
});

/** 调度器能力登记：**未启用**。 */
export const SCHEDULER_CAPABILITY: CapabilityFlag = Object.freeze({
  feature: "scheduler",
  enabled: false,
  availableIn: "V0.5.0",
  reason: "V0.1.0 仅交付端口接口 + 空实现；调度真实实现归 V0.5.0。",
});

/** 后台执行体能力登记：**未启用**（旧线 `InProcessBackgroundExecutor` 对应分支）。 */
export const BACKGROUND_EXECUTOR_CAPABILITY: CapabilityFlag = Object.freeze({
  feature: "background-executor",
  enabled: false,
  availableIn: "V0.5.0",
  reason: "V0.1.0 不交付执行体；随队列真实实现在 V0.5.0 一并落地。",
});

/** 本版装配登记总表（供组合根 / 台账 / 门禁直接读）。 */
export const ASSEMBLY_REGISTRY: Readonly<Record<string, CapabilityFlag>> = Object.freeze({
  [QUEUE_CAPABILITY.feature]: QUEUE_CAPABILITY,
  [SCHEDULER_CAPABILITY.feature]: SCHEDULER_CAPABILITY,
  [BACKGROUND_EXECUTOR_CAPABILITY.feature]: BACKGROUND_EXECUTOR_CAPABILITY,
});

/** 队列能力是否启用（V0.1.0 恒为 `false`）。 */
export function isQueueEnabled(): boolean {
  return QUEUE_CAPABILITY.enabled;
}

/** 调度能力是否启用（V0.1.0 恒为 `false`）。 */
export function isSchedulerEnabled(): boolean {
  return SCHEDULER_CAPABILITY.enabled;
}
