/**
 * AUD-04 · 工具超时的**上界**与 `deadlineMs` 的**消费**（P2）。
 *
 * 被修复的缺陷
 * ----------
 *   ① `code_exec` 把模型给的 `args.timeout_ms` **直传**沙箱（无 cap）；
 *   ② `shell` 同源，而且是"两个 `timeoutMs` 键 + 展开顺序遮盖"，既不是 min 也没有校验；
 *   ③ `ToolExecutor.DEFAULT_TOOL_TIMEOUT_MS = 30_000` 从未进入 `ToolContext`；
 *   ④ `RunCallContext.deadlineMs`（run 的绝对截止时刻）全仓**只有声明与赋值、0 处消费**。
 *
 *   后果：模型一句 `timeout_ms: 86400000` 就能把一个秒级 run 钉住一天，而 run 自己的
 *   墙钟预算（`limits.maxWallTimeMs`）**挡不住**它 —— 预算只在轮次间判定。
 *
 * 判据
 * ----
 *   ① 模型传 `86_400_000` ⇒ 沙箱收到的 `timeoutMs <= 30_000`（执行器默认值收紧）；
 *   ② `timeout_ms: 0` / `-1` / `"abc"` ⇒ `VALIDATION_ERROR` 且**沙箱未被调用**
 *      （不静默回落默认值 —— 那会把调用方 bug 变成"看起来正常"）；
 *   ③ `deadlineMs` 已过 ⇒ **不调用工具**，直接 `FAILED` + `TOOL_TIMEOUT`；
 *   ④ 请求值**收紧**有效（`timeout_ms: 5` ⇒ 沙箱收到 5，不会被抬到 30_000）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/tool-timeout.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { ToolExecutor, DEFAULT_TOOL_TIMEOUT_MS } from "../dist/modules/tool/executor.js";
import { createCodeExecTool } from "../dist/modules/tool/builtin/code-exec.js";
import { shellTool } from "../dist/modules/tool/builtin/shell.js";

/** 记录每次 `exec` 的选项的假沙箱。 */
function recordingSandbox() {
  const execs = [];
  return {
    execs,
    async createSession(workdir) {
      return { id: "sess-1", workdir };
    },
    async exec(session, argv, options) {
      execs.push({ argv, options });
      return {
        stdout: "ok",
        stderr: "",
        exitCode: 0,
        timedOut: false,
        durationMs: 3,
        truncated: false,
      };
    },
    async destroy() {},
  };
}

/** 测试解释器（假路径：本用例只关心 `exec` 选项，不真跑代码）。 */
const FAKE_INTERPRETERS = { python: "/fake/python3", node: "/fake/node", bash: "/fake/bash" };

/** 建执行器（工具表注入 code_exec + shell）。 */
function buildExecutor(sandbox, options = {}) {
  const tools = new Map([
    ["code_exec", createCodeExecTool(FAKE_INTERPRETERS)],
    ["shell", shellTool],
  ]);
  return new ToolExecutor({
    workspaceRoot: options.workspaceRoot ?? process.cwd(),
    tools,
    sandbox,
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
  });
}

/** 最小 `RunCallContext`（`deadlineMs` 可覆盖）。 */
function ctx(overrides = {}) {
  return {
    runId: "r0000000-0000-4000-8000-000000000001",
    tenantId: "11111111-1111-4111-8111-111111111111",
    signal: new AbortController().signal,
    deadlineMs: overrides.deadlineMs ?? Date.now() + 60_000,
    budget: { addToolCall() {}, addTokens() {}, addCost() {}, addTurn() {} },
    permissions: [],
    policyVersion: "test",
  };
}

// ---------------------------------------------------------------------------
// ① 上界
// ---------------------------------------------------------------------------

test("① code_exec：模型传 86_400_000 ⇒ 沙箱收到的 timeoutMs <= 30_000", async () => {
  const sandbox = recordingSandbox();
  const executor = buildExecutor(sandbox);

  const result = await executor.execute(
    { callId: "c1", toolName: "code_exec", input: { code: "print(1)", timeout_ms: 86_400_000 } },
    ctx()
  );

  assert.equal(result.status, "SUCCESS", JSON.stringify(result));
  assert.equal(sandbox.execs.length, 1);
  assert.ok(
    sandbox.execs[0].options.timeoutMs <= DEFAULT_TOOL_TIMEOUT_MS,
    `沙箱 timeoutMs 必须 <= ${DEFAULT_TOOL_TIMEOUT_MS}，实测 ${sandbox.execs[0].options.timeoutMs}`
  );
  assert.equal(sandbox.execs[0].options.timeoutMs, DEFAULT_TOOL_TIMEOUT_MS, "默认值即上界");
});

test("① shell：同样被收紧到执行器默认值", async () => {
  const sandbox = recordingSandbox();
  const executor = buildExecutor(sandbox);

  const result = await executor.execute(
    { callId: "c1", toolName: "shell", input: { command: "echo 1", timeout_ms: 86_400_000 } },
    ctx()
  );

  assert.equal(result.status, "SUCCESS", JSON.stringify(result));
  assert.equal(sandbox.execs[0].options.timeoutMs, DEFAULT_TOOL_TIMEOUT_MS);
});

test("① run 剩余时间更短 ⇒ 取**更小**的那个（deadlineMs 真正参与计算）", async () => {
  const sandbox = recordingSandbox();
  const executor = buildExecutor(sandbox);

  await executor.execute(
    { callId: "c1", toolName: "shell", input: { command: "echo 1", timeout_ms: 20_000 } },
    // 只剩 ~1.5s（留足容差给用例自身的执行）
    ctx({ deadlineMs: Date.now() + 1_500 })
  );

  const timeoutMs = sandbox.execs[0].options.timeoutMs;
  assert.ok(timeoutMs <= 1_500, `必须被 run 剩余时间收紧，实测 ${timeoutMs}`);
  assert.ok(timeoutMs > 0, `收紧后仍须为正，实测 ${timeoutMs}`);
});

// ---------------------------------------------------------------------------
// ② 非法 timeout_ms
// ---------------------------------------------------------------------------

test("② timeout_ms: 0 / -1 / \"abc\" ⇒ VALIDATION_ERROR 且**沙箱未被调用**", async () => {
  for (const bogus of [0, -1, Number.NaN, Number.POSITIVE_INFINITY, "abc", null]) {
    const sandbox = recordingSandbox();
    const executor = buildExecutor(sandbox);

    for (const [toolName, input] of [
      ["code_exec", { code: "print(1)", timeout_ms: bogus }],
      ["shell", { command: "echo 1", timeout_ms: bogus }],
    ]) {
      const result = await executor.execute({ callId: "c", toolName, input }, ctx());
      assert.equal(result.status, "FAILED", `${toolName} timeout_ms=${String(bogus)} 必须失败`);
      assert.match(
        result.error ?? "",
        /timeout_ms 必须是正的有限数/,
        `${toolName} timeout_ms=${String(bogus)} ⇒ VALIDATION_ERROR（实测 ${result.error}）`
      );
    }

    assert.equal(
      sandbox.execs.length,
      0,
      `timeout_ms=${String(bogus)} 时沙箱**一次都不该被调用**（拒绝要发生在执行之前）`
    );
  }
});

test("② 对照：未传 timeout_ms ⇒ 用上下文上限（不是 VALIDATION_ERROR）", async () => {
  const sandbox = recordingSandbox();
  const executor = buildExecutor(sandbox);
  const result = await executor.execute(
    { callId: "c1", toolName: "shell", input: { command: "echo 1" } },
    ctx()
  );
  assert.equal(result.status, "SUCCESS", JSON.stringify(result));
  assert.equal(sandbox.execs[0].options.timeoutMs, DEFAULT_TOOL_TIMEOUT_MS);
});

// ---------------------------------------------------------------------------
// ③ deadlineMs 已过
// ---------------------------------------------------------------------------

test("③ deadlineMs 已过 ⇒ **不调用工具**，直接 FAILED + TOOL_TIMEOUT", async () => {
  let toolCalls = 0;
  const sandbox = recordingSandbox();
  const executor = new ToolExecutor({
    workspaceRoot: process.cwd(),
    sandbox,
    tools: new Map([
      [
        "spy",
        {
          name: "spy",
          requiresSandbox: false,
          async execute() {
            toolCalls += 1;
            return { ok: true, durationMs: 1 };
          },
        },
      ],
    ]),
  });

  const result = await executor.execute(
    { callId: "c1", toolName: "spy", input: {} },
    ctx({ deadlineMs: Date.now() - 1 })
  );

  assert.equal(result.status, "FAILED");
  assert.match(result.error ?? "", /TOOL_TIMEOUT/, `错误码必须是 TOOL_TIMEOUT，实测 ${result.error}`);
  assert.equal(toolCalls, 0, "截止时刻已过时**不得进入工具**");
  assert.equal(sandbox.execs.length, 0);
});

// ---------------------------------------------------------------------------
// ④ 请求值可以收紧
// ---------------------------------------------------------------------------

test("④ timeout_ms: 5 ⇒ 沙箱收到 5（收紧有效，不会被抬到 30_000）", async () => {
  const sandbox = recordingSandbox();
  const executor = buildExecutor(sandbox);
  await executor.execute(
    { callId: "c1", toolName: "code_exec", input: { code: "print(1)", timeout_ms: 5 } },
    ctx()
  );
  assert.equal(sandbox.execs[0].options.timeoutMs, 5);
});
