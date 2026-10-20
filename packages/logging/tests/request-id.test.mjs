// T1-02 · @wbtime/logging：证明 request_id 在**异步调用链**中贯通。
//
// 这条测试是本项目对旧 Python 线 `request_id` 语义（contextvars + middleware）
// 的继承凭证：只要入口处 withRequestId 包住 dispatch，任意深度的 await / 定时器 /
// Promise 链里 getRequestId() 与日志 mixin 都必须拿到同一个值。

import assert from "node:assert/strict";
import { test } from "node:test";
import { Writable } from "node:stream";

import {
  createLogger,
  getRequestId,
  hasRequestId,
  requireRequestId,
  withRequestId,
} from "../dist/index.js";

/** 收集 pino 输出行的内存 destination。 */
function collect() {
  const lines = [];
  const destination = new Writable({
    write(chunk, _encoding, callback) {
      lines.push(chunk.toString());
      callback();
    },
  });
  return { lines, destination };
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("异步调用链深处仍能取到同一个 request_id", async () => {
  assert.equal(getRequestId(), undefined, "上下文外必须取不到");
  assert.equal(hasRequestId(), false);

  const seen = [];
  await withRequestId("rid-async-1", async () => {
    seen.push(getRequestId());
    await delay(1);
    seen.push(getRequestId());
    await Promise.all([delay(1), delay(2)]);
    seen.push(getRequestId());
    // 未被 withRequestId 直接包裹的嵌套函数（模拟 service → repo → 落库三层调用）
    const deep = async () => {
      await delay(1);
      return getRequestId();
    };
    seen.push(await deep());
  });

  assert.deepEqual(seen, ["rid-async-1", "rid-async-1", "rid-async-1", "rid-async-1"]);
  assert.equal(getRequestId(), undefined, "退出上下文后不得残留");
});

test("同步回调同样贯通（ALS 不区分同步 / 异步）", () => {
  const value = withRequestId("rid-sync-1", () => requireRequestId());
  assert.equal(value, "rid-sync-1");
});

test("上下文外 requireRequestId 抛错，不静默给空串", () => {
  assert.throws(() => requireRequestId(), /request_id/);
});

test("pino 每条日志都带上下文中的 request_id（mixin 贯通）", async () => {
  const { lines, destination } = collect();
  const log = createLogger({ level: "info", destination });

  await withRequestId("rid-log-1", async () => {
    log.info("level-1");
    await delay(1);
    log.info("level-2-deep");
  });
  log.info("outside");

  assert.equal(lines.length, 3);
  const [first, second, third] = lines.map((l) => JSON.parse(l));
  assert.equal(first.request_id, "rid-log-1");
  assert.equal(second.request_id, "rid-log-1");
  assert.equal("request_id" in third, false, "上下文外的日志不得伪造 request_id");
});

test("嵌套 withRequestId：内层覆盖、外层恢复", () => {
  withRequestId("outer", () => {
    assert.equal(getRequestId(), "outer");
    withRequestId("inner", () => {
      assert.equal(getRequestId(), "inner");
    });
    assert.equal(getRequestId(), "outer");
  });
});
