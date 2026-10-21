// T1-02 · @wbtime/logging：`logError` 必须留住**堆栈**与**原始抛出值**。
//
// 为什么需要这条测试：改造前 `logError` 手拼 `{ name, message }` 塞进 `err`，
// pino 的默认 `err` 序列化器因此拿不到真正的 Error 实例 ⇒ 线上日志里
// **没有 stack**，只剩一句 message。这类缺陷在"日志有输出"的冒烟测试里永远绿，
// 只有逐字段断言 JSON 行才能抓到。同理，非 Error 抛出物（`throw "boom"`）
// 过去只留下固定文案「非 Error 实例被抛出」，原始值直接丢失。

import assert from "node:assert/strict";
import { test } from "node:test";
import { Writable } from "node:stream";

import { createLogger, logError } from "../dist/index.js";

/** 收集 pino 输出行的内存 destination（与 request-id.test.mjs 同款）。 */
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

test("Error 实例：err 字段带 stack / message / type，且带契约错误码", () => {
  const { lines, destination } = collect();
  const log = createLogger({ level: "error", destination });

  const error = new Error("配置非法");
  // 模拟 ConfigError 的形态：契约错误码放在 `code` 上。
  error.code = "CONFIGURATION_ERROR";
  logError(log, error, { stage: "boot" });

  assert.equal(lines.length, 1, "一条错误日志只应产出一行");
  const row = JSON.parse(lines[0]);

  assert.equal(typeof row.err, "object");
  assert.equal(row.err.message, "配置非法");
  assert.equal(typeof row.err.stack, "string", "堆栈必须被序列化出来");
  assert.ok(row.err.stack.length > 0, "堆栈不得为空串");
  assert.match(row.err.stack, /Error: 配置非法/);
  assert.equal(typeof row.err.type, "string", "pino err 序列化器输出 type");

  assert.equal(row.error_code, "CONFIGURATION_ERROR", "契约错误码必须落到日志里");
  assert.equal(row.error_http_status, 422, "错误码对应的 HTTP 状态一并落日志");
  assert.equal(row.stage, "boot", "调用方 context 必须保留");
  assert.equal(row.msg, "配置非法", "message 取 error.message");
});

test("非 Error 抛出物：记录原始值与 typeof，且不伪造 err 字段", () => {
  const { lines, destination } = collect();
  const log = createLogger({ level: "error", destination });

  logError(log, "boom");

  assert.equal(lines.length, 1);
  const row = JSON.parse(lines[0]);

  assert.equal(row.thrown, "boom", "原始抛出值必须被记录");
  assert.equal(row.thrown_type, "string", "typeof 结果一并记录，便于判别类型");
  assert.equal("err" in row, false, "非 Error 没有堆栈，不得伪造 err 字段");
  assert.equal(row.msg, "非 Error 实例被抛出");
});
