// @wbtime/ports · 队列 / 调度空实现测试（node:test，零测试框架）。
//
// 核心断言：调用空实现 **必须抛 `CONFIGURATION_ERROR`** —— 不是返回 undefined、
// 不是静默成功（对应 DoD#4 E-2 判据）。
//
// 实测教训（2026-10-21，node v22.22.2）：`assert.rejects` **接不住同步 throw**
// —— 同步抛会让 `assert.rejects` 自身以该错误 reject（实测输出：`FAIL -> CONFIGURATION_ERROR`）。
// 故空实现方法一律声明为 `async`（错误以 rejected promise 抛出），测试统一用
// `await assert.rejects(...)` 断言。

import assert from "node:assert/strict";
import test from "node:test";

import {
  ASSEMBLY_REGISTRY,
  CONFIGURATION_ERROR_HTTP_STATUS,
  NOOP_QUEUE_ERROR_CODE,
  NOOP_SCHEDULER_ERROR_CODE,
  QUEUE_CAPABILITY,
  SCHEDULER_CAPABILITY,
  createNoopQueue,
  createNoopScheduler,
  isQueueEnabled,
  isSchedulerEnabled,
  noopQueue,
} from "../dist/index.js";

const TASK_ID = "018f3f6a-7b1c-7c2e-9a11-2f5b0d3e4a01";
const ITEM = { taskId: TASK_ID, type: "agent.run" };

/** 断言 `fn()` 以 CONFIGURATION_ERROR 拒绝。 */
async function assertConfigError(fn, operation) {
  await assert.rejects(
    fn,
    (err) => {
      assert.equal(err.code, "CONFIGURATION_ERROR", `${operation} 必须抛 CONFIGURATION_ERROR`);
      assert.equal(err.httpStatus, 422, "http_status 应与 contracts/errors.json 一致（422）");
      assert.equal(err.data.operation, operation);
      assert.match(err.message, /未启用/);
      return true;
    },
    `${operation} 未抛错（静默成功 = 判红）`,
  );
}

test("noopQueue：enqueue / dequeue / ack / size 全部抛 CONFIGURATION_ERROR", async () => {
  const queue = createNoopQueue();
  await assertConfigError(() => queue.enqueue(ITEM), "enqueue");
  await assertConfigError(() => queue.dequeue(), "dequeue");
  await assertConfigError(() => queue.ack(ITEM), "ack");
  await assertConfigError(() => queue.size(), "size");
  await assertConfigError(() => noopQueue.enqueue(ITEM), "enqueue");
});

test("noopQueue：绝不静默返回 —— 返回的是 rejected promise，不是 undefined / 0 / null", async () => {
  const queue = createNoopQueue();
  for (const [name, call] of [
    ["dequeue", () => queue.dequeue()],
    ["size", () => queue.size()],
    ["enqueue", () => queue.enqueue(ITEM)],
  ]) {
    const p = call();
    assert.equal(typeof p?.then, "function", `${name}() 必须返回 promise`);
    let rejected = false;
    try {
      await p;
    } catch {
      rejected = true;
    }
    assert.equal(rejected, true, `${name}() 必须拒绝（不得 resolve）`);
  }
});

test("noopScheduler：scheduleOnce / start / shutdown 全部抛 CONFIGURATION_ERROR", async () => {
  const scheduler = createNoopScheduler();
  await assertConfigError(
    () => scheduler.scheduleOnce("2026-10-21T00:00:00.000Z", { taskType: "data.sync" }),
    "scheduleOnce",
  );
  await assertConfigError(() => scheduler.start(), "start");
  await assertConfigError(() => scheduler.shutdown(true), "shutdown");
});

test("装配登记：本版队列 / 调度 / 执行体均未启用，真实实现归 V0.5.0", () => {
  assert.equal(isQueueEnabled(), false);
  assert.equal(isSchedulerEnabled(), false);
  assert.equal(QUEUE_CAPABILITY.availableIn, "V0.5.0");
  assert.equal(SCHEDULER_CAPABILITY.availableIn, "V0.5.0");
  assert.deepEqual(Object.keys(ASSEMBLY_REGISTRY).sort(), [
    "background-executor",
    "scheduler",
    "task-queue",
  ]);
  for (const flag of Object.values(ASSEMBLY_REGISTRY)) {
    assert.equal(flag.enabled, false, `${flag.feature} 本版必须为未启用`);
    assert.equal(flag.availableIn, "V0.5.0");
    assert.ok(flag.reason.length > 0);
  }
});

test("错误码常量与契约一致", () => {
  assert.equal(NOOP_QUEUE_ERROR_CODE, "CONFIGURATION_ERROR");
  assert.equal(NOOP_SCHEDULER_ERROR_CODE, "CONFIGURATION_ERROR");
  assert.equal(CONFIGURATION_ERROR_HTTP_STATUS, 422);
});
