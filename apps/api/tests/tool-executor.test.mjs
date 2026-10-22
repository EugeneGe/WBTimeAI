/**
 * T3-10 · `ToolExecutor` 的**四段事务边界**证明（DoD#6）。
 *
 * 判据（卡面验收 ④「intent→authorize→execute→result 各段崩溃可判定」+ 反例）
 * ---------------------------------------------------------------
 *   - **段 1 intent**：未知工具 ⇒ `FAILED`，`durationMs` 有值，**零副作用**（A-1）；
 *   - **段 2 authorize**：权限不足 ⇒ `DENIED`，**执行器零调用**（A-2，卡面反例
 *     "先执行后检查 ⇒ E4 必红" 的机器形态）；
 *   - **段 3 execute**：工具抛错 ⇒ `FAILED`；取消 ⇒ `CANCELLED`（A-3 / A-5）；
 *   - **段 4 result**：成功 ⇒ `SUCCESS` + `output`（A-4）。
 *   - 需沙箱但未装配 ⇒ `FAILED`（**不回落**宿主执行，A-6）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/tool-executor.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { ToolExecutor } from "../dist/modules/tool/executor.js";

/** 计数工具（记录被调用次数）。 */
function countingTool(name, behaviour = "ok") {
  const calls = [];
  return {
    name,
    requiresSandbox: false,
    get calls() {
      return calls;
    },
    async execute(args) {
      calls.push(args);
      if (behaviour === "throw") throw new Error("工具内部炸了");
      if (behaviour === "fail") {
        return { ok: false, error: "业务失败", errorCode: "INTERNAL_ERROR", durationMs: 1 };
      }
      if (behaviour === "deny") {
        return { ok: false, error: "本地规则拒绝", errorCode: "PERMISSION_DENIED", durationMs: 1 };
      }
      return { ok: true, output: { echo: args }, durationMs: 2 };
    },
  };
}

/** 建执行器（工具表可配）。 */
function buildExecutor(tools, options = {}) {
  return new ToolExecutor({
    workspaceRoot: options.workspaceRoot ?? process.cwd(),
    tools: new Map(tools.map((tool) => [tool.name, tool])),
    ...(options.sandbox === undefined ? {} : { sandbox: options.sandbox }),
    ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
  });
}

/** 最小 `RunCallContext`。 */
function ctx(overrides = {}) {
  return {
    runId: "r0000000-0000-4000-8000-000000000001",
    tenantId: "11111111-1111-4111-8111-111111111111",
    signal: overrides.signal ?? new AbortController().signal,
    deadlineMs: Date.now() + 60_000,
    budget: { addToolCall() {}, addTokens() {}, addCost() {}, addTurn() {} },
    permissions: overrides.permissions ?? [],
    policyVersion: "test",
  };
}

// ---------------------------------------------------------------------------
// 四段
// ---------------------------------------------------------------------------

test("A-1 · 段 1 intent：未知工具 ⇒ FAILED，且**没有执行任何工具**", async () => {
  const known = countingTool("known");
  const executor = buildExecutor([known]);

  const result = await executor.execute({ callId: "c1", toolName: "nope", input: {} }, ctx());

  assert.equal(result.status, "FAILED");
  assert.match(result.error ?? "", /未知工具/);
  assert.equal(typeof result.durationMs, "number");
  assert.equal(known.calls.length, 0, "解析失败不得触发任何工具执行");
});

test("A-2 · 段 2 authorize：权限不足 ⇒ DENIED，**执行器零调用**（反例：先执行后检查）", async () => {
  const tool = countingTool("dangerous");
  const executor = buildExecutor([tool]);

  const result = await executor.execute(
    { callId: "c1", toolName: "dangerous", input: {} },
    ctx({ permissions: ["tool:other"] })
  );

  assert.equal(result.status, "DENIED", "未授权必须是 DENIED（不是 FAILED）");
  assert.match(result.error ?? "", /缺少权限 tool:dangerous/);
  assert.equal(
    tool.calls.length,
    0,
    "授权必须在执行之前 —— 这里出现调用就说明顺序写反了（卡面反例）"
  );
});

test("A-3 · 段 3 execute：工具抛错 ⇒ FAILED（不向上抛）", async () => {
  const tool = countingTool("boom", "throw");
  const executor = buildExecutor([tool]);

  const result = await executor.execute({ callId: "c1", toolName: "boom", input: {} }, ctx());
  assert.equal(result.status, "FAILED");
  assert.match(result.error ?? "", /工具内部炸了/);
  assert.equal(tool.calls.length, 1, "工具确实被调了一次");
});

test("A-4 · 段 4 result：成功 ⇒ SUCCESS + output", async () => {
  const tool = countingTool("ok");
  const executor = buildExecutor([tool]);

  const result = await executor.execute(
    { callId: "c1", toolName: "ok", input: { x: 1 } },
    ctx()
  );
  assert.equal(result.status, "SUCCESS");
  assert.deepEqual(result.output, { echo: { x: 1 } });
  assert.equal(typeof result.durationMs, "number");
});

test("A-5 · 取消信号 ⇒ CANCELLED（且有信号时不调工具）", async () => {
  const tool = countingTool("slow");
  const executor = buildExecutor([tool]);
  const controller = new AbortController();
  controller.abort();

  const result = await executor.execute(
    { callId: "c1", toolName: "slow", input: {} },
    ctx({ signal: controller.signal })
  );
  assert.equal(result.status, "CANCELLED");
  assert.equal(tool.calls.length, 0, "已取消时不得执行");
});

test("A-6 · 工具返回 DENIED ⇒ 映射为 DENIED（不是 FAILED）", async () => {
  const tool = countingTool("guard", "deny");
  const executor = buildExecutor([tool]);
  const result = await executor.execute({ callId: "c1", toolName: "guard", input: {} }, ctx());
  assert.equal(result.status, "DENIED", "工具层的 PERMISSION_DENIED 必须保持 DENIED 语义");
});

test("A-7 · 工具返回业务失败 ⇒ FAILED", async () => {
  const tool = countingTool("biz", "fail");
  const executor = buildExecutor([tool]);
  const result = await executor.execute({ callId: "c1", toolName: "biz", input: {} }, ctx());
  assert.equal(result.status, "FAILED");
  assert.equal(result.error, "业务失败");
});

test("A-8 · 空权限集 ⇒ 放行（V0.3.0 现状：真正的裁决在 T3-13）", async () => {
  const tool = countingTool("open");
  const executor = buildExecutor([tool]);
  const result = await executor.execute({ callId: "c1", toolName: "open", input: {} }, ctx());
  assert.equal(result.status, "SUCCESS");
});

test("A-9 · 需沙箱但执行器未装配 ⇒ FAILED 且**工具零调用**（不回落宿主执行）", async () => {
  const sandboxed = {
    name: "needs-box",
    requiresSandbox: true,
    calls: 0,
    async execute() {
      this.calls += 1;
      return { ok: true, durationMs: 1 };
    },
  };
  const executor = buildExecutor([sandboxed]);
  const result = await executor.execute({ callId: "c1", toolName: "needs-box", input: {} }, ctx());

  assert.equal(result.status, "FAILED");
  assert.match(result.error ?? "", /需要沙箱/);
  assert.equal(sandboxed.calls, 0, "前置条件不满足时绝不能进工具（否则就是宿主直执行）");
});
