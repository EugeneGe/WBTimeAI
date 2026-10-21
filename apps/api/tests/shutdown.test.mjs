/**
 * FIX-07 · 优雅关闭超时兜底（20xx 审计 #9 / `main.ts:165-184`）。
 *
 * 缺陷原文：旧 `shutdown()` 只 `await close()`，既不设超时也不 `exit` ——
 * `app.close()` / `pool.end()` 一旦被空闲 keep-alive 或租借中的连接挂住，
 * 进程就"收到 SIGTERM 但永不退出"，编排系统只能等宽限期结束再 SIGKILL。
 *
 * ⚠️ **不在测试里真发 SIGTERM**：Windows 上 `child.kill` 是硬杀、信号语义与 POSIX
 * 不同，测信号等于测平台而不是测逻辑。这里直接测 `runShutdown` 这个纯函数
 * （`close` / `exit` / `log` 全部注入），三条判据都是确定性的：
 *   ① 正常关闭 ⇒ `exit(0)` 恰好一次；
 *   ② `close` 永挂 + 短超时 ⇒ `exit(1)`（不 await 到底）；
 *   ③ 并发双信号 ⇒ 执行体只跑一次、`exit` 只调一次。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_SHUTDOWN_TIMEOUT_MS,
  EXIT_SHUTDOWN_FAILED,
  EXIT_SHUTDOWN_OK,
  createShutdownHandler,
  runShutdown,
} from "../dist/shutdown.js";

/** 记录器：断言"打了日志"与"没打某些日志"都不必解析 pino 流。 */
function recordingLogger() {
  const infos = [];
  const errors = [];
  return {
    log: {
      info: (fields, message) => {
        infos.push({ fields, message });
      },
      error: (fields, message) => {
        errors.push({ fields, message });
      },
    },
    infos,
    errors,
  };
}

/** 收集 `exit` 的调用序列。 */
function recordingExit() {
  const codes = [];
  return {
    exit: (code) => {
      codes.push(code);
    },
    codes,
  };
}

// ---------------------------------------------------------------------------
// ① 正常路径
// ---------------------------------------------------------------------------

test("FIX-07 ① · 正常关闭 ⇒ exit(0) 恰好一次，且打出关闭完成日志", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();
  let closeCalls = 0;

  const outcome = await runShutdown({
    close: async () => {
      closeCalls += 1;
    },
    timeoutMs: 1000,
    exit: exits.exit,
    log: recorder.log,
    signal: "SIGTERM",
  });

  assert.equal(closeCalls, 1, "close 必须被调用一次");
  assert.deepEqual(exits.codes, [EXIT_SHUTDOWN_OK], "正常关闭必须 exit(0) 且只调一次");
  assert.equal(outcome.code, EXIT_SHUTDOWN_OK);
  assert.equal(outcome.timedOut, false, "正常路径不得被标成超时");
  assert.equal(recorder.errors.length, 0, "正常关闭不得打 error 日志");
  assert.ok(
    recorder.infos.some((item) => item.message.includes("已关闭")),
    "必须留下关闭完成的日志"
  );
});

test("FIX-07 ① · 同步的 close（非 Promise）同样走正常路径", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();
  const outcome = await runShutdown({
    close: () => undefined,
    timeoutMs: 1000,
    exit: exits.exit,
    log: recorder.log,
  });
  assert.equal(outcome.code, EXIT_SHUTDOWN_OK);
  assert.deepEqual(exits.codes, [0]);
});

// ---------------------------------------------------------------------------
// ② 超时兜底
// ---------------------------------------------------------------------------

test("FIX-07 ② · close 永挂 + 20ms 超时 ⇒ exit(1)，不 await 到底", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();
  let closeCalls = 0;

  const startedAt = Date.now();
  const outcome = await runShutdown({
    // 永不 resolve：模拟"app.close() 被空闲 keep-alive 挂住"
    close: () => {
      closeCalls += 1;
      return new Promise(() => {});
    },
    timeoutMs: 20,
    exit: exits.exit,
    log: recorder.log,
    signal: "SIGTERM",
  });
  const elapsed = Date.now() - startedAt;

  assert.equal(closeCalls, 1, "close 必须已被调用（不是『没开始就超时』）");
  assert.deepEqual(exits.codes, [EXIT_SHUTDOWN_FAILED], "超时必须 exit(1) 且只调一次");
  assert.equal(outcome.code, EXIT_SHUTDOWN_FAILED);
  assert.equal(outcome.timedOut, true, "必须标记为走了兜底");
  assert.ok(elapsed < 1000, `超时兜底必须及时生效（实测 ${elapsed}ms）`);
  assert.equal(recorder.errors.length, 1, "超时必须打一条 error 日志（留下归因线索）");
  assert.match(recorder.errors[0].message, /超时/);
});

test("FIX-07 ② · close 抛错 ⇒ exit(1)（不能假装正常退出）", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();
  const outcome = await runShutdown({
    close: async () => {
      throw new Error("pool.end() 二次调用");
    },
    timeoutMs: 1000,
    exit: exits.exit,
    log: recorder.log,
  });

  assert.deepEqual(exits.codes, [EXIT_SHUTDOWN_FAILED], "关闭失败必须 exit(1)");
  assert.equal(outcome.code, EXIT_SHUTDOWN_FAILED);
  assert.equal(outcome.timedOut, false, "抛错不是超时（两者要能在日志里区分）");
  assert.equal(recorder.errors.length, 1);
});

test("FIX-07 ② · timeoutMs=0 ⇒ 不设兜底（只 await close，正常完成仍 exit(0)）", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();
  const outcome = await runShutdown({
    close: async () => undefined,
    timeoutMs: 0,
    exit: exits.exit,
    log: recorder.log,
  });
  assert.equal(outcome.code, EXIT_SHUTDOWN_OK);
  assert.deepEqual(exits.codes, [0]);
});

test("FIX-07 · timeoutMs 非法（负数 / NaN）⇒ 抛 TypeError（编程错误不静默兜底）", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();
  await assert.rejects(
    () =>
      runShutdown({
        close: async () => undefined,
        timeoutMs: -1,
        exit: exits.exit,
        log: recorder.log,
      }),
    (error) => error instanceof TypeError
  );
  await assert.rejects(
    () =>
      runShutdown({
        close: async () => undefined,
        timeoutMs: Number.NaN,
        exit: exits.exit,
        log: recorder.log,
      }),
    (error) => error instanceof TypeError
  );
  assert.deepEqual(exits.codes, [], "参数非法时不得 exit");
});

test("FIX-07 · 默认兜底时长是 10_000ms（与 config 的 DEFAULTS 同值）", () => {
  assert.equal(DEFAULT_SHUTDOWN_TIMEOUT_MS, 10_000);
});

// ---------------------------------------------------------------------------
// ③ 并发双信号
// ---------------------------------------------------------------------------

test("FIX-07 ③ · 并发双信号 ⇒ 执行体只跑一次，exit 只调一次（两个调用拿到同一结果）", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();
  let closeCalls = 0;

  const handler = createShutdownHandler({
    close: async () => {
      closeCalls += 1;
    },
    timeoutMs: 1000,
    exit: exits.exit,
    log: recorder.log,
  });

  const [first, second] = await Promise.all([
    handler.shutdown("SIGTERM"),
    handler.shutdown("SIGINT"),
  ]);

  assert.equal(handler.runs(), 1, "执行体只能跑一次（旧实现的 closing 标志是同一目的，但没有兜底）");
  assert.equal(closeCalls, 1, "close 只能被调用一次");
  assert.deepEqual(exits.codes, [EXIT_SHUTDOWN_OK], "exit 只能被调用一次");
  assert.equal(first, second, "并发调用必须拿到同一个结局对象");
  assert.ok(
    recorder.infos.some((item) => item.message.includes("忽略重复信号")),
    "重复信号必须留下日志（否则排查时会以为信号丢了）"
  );
});

test("FIX-07 ③ · 先 SIGTERM 完成后再来 SIGINT：仍然只有一次关闭（幂等）", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();
  let closeCalls = 0;

  const handler = createShutdownHandler({
    close: async () => {
      closeCalls += 1;
    },
    timeoutMs: 1000,
    exit: exits.exit,
    log: recorder.log,
  });

  await handler.shutdown("SIGTERM");
  const second = await handler.shutdown("SIGINT");

  assert.equal(handler.runs(), 1);
  assert.equal(closeCalls, 1, "已关闭后不得再跑一遍 close（`pool.end()` 二次调用会抛）");
  assert.deepEqual(exits.codes, [EXIT_SHUTDOWN_OK], "exit 不得被调用第二次");
  assert.equal(second.code, EXIT_SHUTDOWN_OK);
  assert.equal(handler.started(), true);
});

test("FIX-07 ③ · 并发双信号在**超时**路径下同样只 exit 一次（exit(1)）", async () => {
  const recorder = recordingLogger();
  const exits = recordingExit();

  const handler = createShutdownHandler({
    close: () => new Promise(() => {}),
    timeoutMs: 20,
    exit: exits.exit,
    log: recorder.log,
  });

  const outcomes = await Promise.all([handler.shutdown("SIGTERM"), handler.shutdown("SIGINT")]);

  assert.equal(handler.runs(), 1);
  assert.deepEqual(exits.codes, [EXIT_SHUTDOWN_FAILED], "超时路径也只 exit 一次，且是失败码");
  assert.equal(outcomes[0].timedOut, true);
  assert.equal(outcomes[1].timedOut, true);
});
