// @wbtime/ports · 调度器端口（**只有接口，无实现**）。
//
// 能力面以旧线取证为准（**只读**：`WBTimeAI_old/packages/config/src/
// wbtime_ai_config/providers.py:452-456` → `create_local_scheduler()`；
// 旧线 `Scheduler` Protocol 的方法面 `schedule_once / start / shutdown` 见
// `WBTimeAI_old/packages/task/src/wbtime_ai_task/scheduler/__init__.py:19-33`）。
//
// 本包严禁引入 APScheduler / Redis / BullMQ 等真实依赖。

/** 一次性调度作业的入参。 */
export interface ScheduledJob {
  /** 目标任务的 `task.type`。 */
  readonly taskType: string;
  /** `task.payload`（JSONB，可空）。 */
  readonly payload?: unknown;
  /** 幂等键（对应 `task.idempotency_key` 唯一索引）。 */
  readonly idempotencyKey?: string | null;
}

/**
 * 调度器端口。
 *
 * 演进路径（接口不变）：V0.1.0 空实现 → V0.5.0 真实实现（本地 / 分布式）。
 */
export interface SchedulerPort {
  /** 调度一次性任务，返回作业 id；`runAt` 为 ISO-8601（建议 UTC）。 */
  scheduleOnce(runAt: string, job: ScheduledJob): Promise<string>;
  /** 启动调度器（幂等，懒启动）。 */
  start(): Promise<void>;
  /** 关闭调度器。 */
  shutdown(wait?: boolean): Promise<void>;
}
