// @wbtime/ports · 任务队列端口（**只有接口，无实现**）。
//
// 能力面以旧线取证为准（**只读**：`WBTimeAI_old/packages/config/src/wbtime_ai_config/
// providers.py:438-442` → `create_inprocess_task_queue()`；`:516-517` →
// `RedisTaskQueue` / `redis_available()`）。旧线 `TaskQueue` Protocol 的方法面为
// `enqueue / dequeue / ack / size`（`WBTimeAI_old/packages/task/src/wbtime_ai_task/
// queue/__init__.py:28-42`），本端口沿用该最小面并统一为 Promise（V0.5.0 真实实现
// 为 Redis/Arq，天然异步）。
//
// 本包严禁引入 Redis / BullMQ / arq 等真实依赖。

/** 队列元素的最小面（对齐 `task` 表主键 + `type` 列）。 */
export interface QueueItem {
  /** `task.id`。 */
  readonly taskId: string;
  /** `task.type`（VARCHAR(100) NOT NULL）。 */
  readonly type: string;
  /** `task.payload`（JSONB，可空）。 */
  readonly payload?: unknown;
}

/**
 * 任务队列端口。
 *
 * 演进路径（接口不变）：V0.1.0 空实现 → V0.5.0 真实实现（进程内 / Redis）。
 */
export interface QueuePort<T extends QueueItem = QueueItem> {
  /** 入队。 */
  enqueue(item: T): Promise<void>;
  /** 出队（无元素返回 `null`；取出未 ack 的元素计入 in-flight）。 */
  dequeue(): Promise<T | null>;
  /** 确认完成（从 in-flight 移除，幂等）。 */
  ack(item: T): Promise<void>;
  /** 待处理元素数量。 */
  size(): Promise<number>;
}
