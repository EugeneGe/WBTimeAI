# @wbtime/ports · 端口层（V0.1.0）

> **⚠️ 本版交付的是「端口接口 + 空实现」。队列 / 调度 / 后台执行体能力一律 `enabled: false`，
> 真实实现归 `V0.5.0`，本版严禁实现（不引入 Redis / BullMQ / arq / APScheduler）。**

## 1. 为什么本版是空实现

路线图 M-05 的逆流边 **E-2**：旧线 `config/providers.py` 以**延迟导入**装配队列 / 调度工厂
（实测：`WBTimeAI_old/packages/config/src/wbtime_ai_config/providers.py`
`:440` `create_inprocess_task_queue`、`:447` `InProcessBackgroundExecutor`、
`:454` `create_local_scheduler`、`:517` `RedisTaskQueue` / `redis_available`）。
若 P1 直接闭版，组合根会**缺键**。因此 V0.1.0 的处理是：

- **端口先立**（接口面取自旧线 `TaskQueue` / `Scheduler` Protocol 的**能力面**，只读取证、不抄实现）；
- **空实现补齐装配键**，但**首次调用即抛** `CONFIGURATION_ERROR`（**非**静默降级）；
- 在 `ASSEMBLY_REGISTRY` 中登记 **未启用** —— 这是 DoD#4(E-2) 的判据载体。

## 2. 未启用清单（机器可读：`ASSEMBLY_REGISTRY`）

| feature | enabled | availableIn | 说明 |
|---|---|---|---|
| `task-queue` | `false` | `V0.5.0` | 队列真实实现（进程内 / Redis）归 V0.5.0 |
| `scheduler` | `false` | `V0.5.0` | 调度真实实现归 V0.5.0 |
| `background-executor` | `false` | `V0.5.0` | 随队列真实实现一并落地 |

判定函数：`isQueueEnabled()` / `isSchedulerEnabled()` —— **V0.1.0 恒为 `false`**。

## 3. 空实现的行为契约

| 调用 | 行为 |
|---|---|
| `queue.enqueue()` / `dequeue()` / `ack()` / `size()` | **抛** `PortsNotEnabledError`（`code = "CONFIGURATION_ERROR"`，`httpStatus = 422`） |
| `scheduler.scheduleOnce()` / `start()` / `shutdown()` | 同上 |

错误码与 HTTP 状态 **实测取自** `contracts/errors.json` → `codes.CONFIGURATION_ERROR`
（`code` = `CONFIGURATION_ERROR`，`http_status` = `422`）。

**禁止**：返回 `undefined`、返回 `0` / `null`、静默成功。测试 `tests/queue.test.mjs`
逐方法断言「必须抛 `CONFIGURATION_ERROR`」。

## 4. 端口面（最小面，接口在 V0.5.0 前不变）

```ts
interface QueuePort<T extends QueueItem> {
  enqueue(item: T): Promise<void>;
  dequeue(): Promise<T | null>;
  ack(item: T): Promise<void>;
  size(): Promise<number>;
}

interface SchedulerPort {
  scheduleOnce(runAt: string, job: ScheduledJob): Promise<string>;
  start(): Promise<void>;
  shutdown(wait?: boolean): Promise<void>;
}
```

## 5. 分层铁律

- 本包 **只有端口接口 + 空实现**：运行时依赖为空（`dependencies: {}`）；
- **不得**引入 Redis / BullMQ / arq / APScheduler 等真实依赖；
- **不 import** `apps/*`；
- 错误码字面量当前内联，待 `@wbtime/contracts`（T1-04）产出统一枚举后改为 re-export（已登记为遗留项）。
