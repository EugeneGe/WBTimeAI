/**
 * T031-03 第二阶 · `spawn_agent`（第 6 个内置工具）过 `ToolExecutor` 的**权限链**证明。
 *
 * 判据（任务卡出口 ②：「仍完整过 `ToolExecutor` 权限链（ALLOW/DENY 逐次）与
 * `SandboxProvider`，**不自建执行通道**」）：
 *   - **A 组 · 授权面**：`permissions` 无 `tool:spawn_agent` 码 ⇒ 段 2 authorize 就返回
 *     `DENIED`（`PERMISSION_DENIED`），**走不到工具体**（端口零调用）⇒ 机器形态即
 *     `tool_call.status == 'DENIED'`（行由上层协调器落，本执行器不写库）；
 *   - **B 组 · 透传面**：授权通过 ⇒ 到达工具体 ⇒ 委派端口经 `ToolContext.delegation`
 *     透传（入参逐字），工具**不自建执行通道**（唯一出口是端口）；
 *   - **C 组 · 拒绝映射**：端口拒绝分两类 —— 策略类（深度/并发/安全闸）⇒ `DENIED`；
 *     装配/生命周期类（父不可见/驱动失败/无网关/未知）⇒ `FAILED`；
 *   - **D 组 · 沙箱面**：`requiresSandbox:false` ⇒ 段 3 的「需沙箱但无沙箱 ⇒ FAILED」
 *     前置**不触发**；且 `#toolContext` 的**两条返回路径**（无沙箱 / 有沙箱）都带端口；
 *   - **E 组 · 输入校验**：与 `BUILTIN_TOOLS.inputSchema.required` 同源的三个校验。
 *
 * 反例（注入即红，本文件自证）：
 *   - 把 A-1 的 `permissions` 给足权限却仍期望 `DENIED` ⇒ 必红（见施工记录 §四）；
 *   - 删掉 A-1 的 DENY 分支 ⇒ 必红。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/spawn-agent-tool.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { ToolExecutor } from "../dist/modules/tool/executor.js";

/** 工具名（与 `SPAWN_AGENT_TOOL_NAME` 同值；测试不 import domain，保持独立）。 */
const TOOL = "spawn_agent";

/** 记录调用的委派端口（返回预定 outcome）。 */
function recordingPort(outcome) {
  const calls = [];
  return {
    calls,
    spawn: async (input) => {
      calls.push(input);
      return outcome;
    },
  };
}

/** 接受的 outcome（`DelegateSpawnOutcome` 的 accepted 形态）。 */
function accepted(childRunId = "child-run-1") {
  return { accepted: true, childRunId, policyVersion: "policy-v1" };
}

/** 拒绝的 outcome（`DelegateSpawnOutcome` 的 rejected 形态）。 */
function rejected(reason) {
  return { accepted: false, reason };
}

/** fake 沙箱（只为证明「有沙箱路径也带端口」；spawn_agent 不用它）。 */
function fakeSandbox() {
  return {
    sessions: 0,
    async createSession(workdir) {
      this.sessions += 1;
      return { id: "sess-1", workdir };
    },
    async exec() {
      return { stdout: "", stderr: "", exitCode: 0, timedOut: false, durationMs: 1, truncated: false };
    },
    async destroy() {},
  };
}

/** 建执行器（**不注入** tools ⇒ 走真实注册表 `resolveTool`，证明真工具过真权限链）。 */
function buildExecutor(options = {}) {
  return new ToolExecutor({
    workspaceRoot: options.workspaceRoot ?? process.cwd(),
    ...(options.sandbox === undefined ? {} : { sandbox: options.sandbox }),
    ...(options.delegation === undefined ? {} : { delegation: options.delegation }),
  });
}

/** 最小 `RunCallContext`（与 `tool-executor.test.mjs` 同形）。 */
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

/** 一次合法调用（入参过工具自身校验）。 */
const VALID_INPUT = { target_agent_id: "agent-1", task: "子任务" };

// ---------------------------------------------------------------------------
// A 组 · 授权面（DENY 必须在执行之前）
// ---------------------------------------------------------------------------

test("A-1 · 无 `tool:spawn_agent` 权限码 ⇒ 段 2 authorize 即 DENIED，端口零调用", async () => {
  const port = recordingPort(accepted());
  const executor = buildExecutor({ delegation: port });

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: VALID_INPUT },
    ctx({ permissions: ["tool:filesystem"] })
  );

  assert.equal(result.status, "DENIED", "未授权必须是 DENIED（不是 FAILED）");
  assert.match(result.error ?? "", /缺少权限 tool:spawn_agent/);
  assert.equal(port.calls.length, 0, "授权段就返回 ⇒ 委派端口一次都不该被调（走不到工具体）");
});

test("A-2 · 空权限集 ⇒ 放行到工具体（V0.3.0 现状：真正的裁决在 SafetyGate）⇒ 端口未装配即拒", async () => {
  const executor = buildExecutor(); // 不注入 delegation

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: VALID_INPUT },
    ctx({ permissions: [] })
  );

  // 空集放行 ⇒ 到达工具 ⇒ 端口**未装配** ⇒ 刻意设计的 INTERNAL_ERROR（映射为 FAILED）。
  // 错误形态是「端口未装配」而非「缺少权限」⇒ 证明它过了授权段、确实到达了工具体。
  assert.equal(result.status, "FAILED");
  assert.match(result.error ?? "", /委派端口未装配/);
  assert.doesNotMatch(result.error ?? "", /缺少权限/, "空权限集必须放行（V0.3.0 现状），不得在授权段拦下");
});

test("A-3 · `*` 通配码 ⇒ 放行到工具体（与 `#authorized` 口径一致）", async () => {
  const port = recordingPort(accepted());
  const executor = buildExecutor({ delegation: port });

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: VALID_INPUT },
    ctx({ permissions: ["*"] })
  );

  assert.equal(result.status, "SUCCESS");
  assert.deepEqual(result.output, { child_run_id: "child-run-1" });
});

test("A-4 · ALLOW 且端口未装配 ⇒ FAILED +「委派端口未装配」（刻意现状，不是缺陷）", async () => {
  const executor = buildExecutor(); // 不注入 delegation

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: VALID_INPUT },
    ctx({ permissions: [`tool:${TOOL}`] })
  );

  assert.equal(result.status, "FAILED");
  assert.match(result.error ?? "", /委派端口未装配/);
  assert.match(result.error ?? "", /不静默降级|一调即拒/);
});

// ---------------------------------------------------------------------------
// B 组 · 透传面（授权通过 ⇒ 端口经 ToolContext.delegation 到达，工具不自建通道）
// ---------------------------------------------------------------------------

test("B-1 · ALLOW + 端口 accepted ⇒ SUCCESS(child_run_id)，入参逐字透传", async () => {
  const port = recordingPort(accepted("child-xyz"));
  const executor = buildExecutor({ delegation: port });

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: { target_agent_id: "agent-7", task: "干活" } },
    ctx({ permissions: [`tool:${TOOL}`] })
  );

  assert.equal(result.status, "SUCCESS");
  assert.deepEqual(result.output, { child_run_id: "child-xyz" }, "观察面只带 child_run_id（不多不少）");
  assert.equal(port.calls.length, 1, "唯一执行出口 = 委派端口（工具不自建执行通道）");
  assert.deepEqual(port.calls[0], { targetAgentId: "agent-7", task: "干活" }, "模型入参逐字透传");
});

test("B-2 · budget_hint 透传（缺省则不出现该键）", async () => {
  const withHint = recordingPort(accepted());
  const executorA = buildExecutor({ delegation: withHint });
  const resultA = await executorA.execute(
    { callId: "c1", toolName: TOOL, input: { target_agent_id: "a", task: "t", budget_hint: 500 } },
    ctx({ permissions: [`tool:${TOOL}`] })
  );
  assert.equal(resultA.status, "SUCCESS");
  assert.deepEqual(withHint.calls[0], { targetAgentId: "a", task: "t", budgetHint: 500 });

  const withoutHint = recordingPort(accepted());
  const executorB = buildExecutor({ delegation: withoutHint });
  const resultB = await executorB.execute(
    { callId: "c1", toolName: TOOL, input: { target_agent_id: "a", task: "t" } },
    ctx({ permissions: [`tool:${TOOL}`] })
  );
  assert.equal(resultB.status, "SUCCESS");
  assert.deepEqual(withoutHint.calls[0], { targetAgentId: "a", task: "t" }, "缺省 ⇒ 键不出现");
});

// ---------------------------------------------------------------------------
// C 组 · 拒绝映射（策略类 ⇒ DENIED；装配/生命周期类 ⇒ FAILED）
// ---------------------------------------------------------------------------

test("C-1 · 策略类拒绝（深度/并发/安全闸）⇒ DENIED", async () => {
  for (const reason of ["DEPTH_EXCEEDED", "CONCURRENCY_LIMIT", "SAFETY_DENIED:命中注入规则"]) {
    const port = recordingPort(rejected(reason));
    const executor = buildExecutor({ delegation: port });
    const result = await executor.execute(
      { callId: "c1", toolName: TOOL, input: VALID_INPUT },
      ctx({ permissions: [`tool:${TOOL}`] })
    );
    assert.equal(result.status, "DENIED", `${reason} 是策略拒绝，必须保持 DENIED 语义`);
    assert.match(result.error ?? "", new RegExp(reason.split(":")[0]));
  }
});

test("C-2 · 装配/生命周期类拒绝 ⇒ FAILED（含未知原因 fail loud）", async () => {
  const reasons = [
    "PARENT_NOT_VISIBLE",
    "CHILD_DRIVE_FAILED:驱动炸了",
    "NO_GATEWAY",
    "AGENT_VERSION_UNRESOLVED:没这个版本",
    "PARENT_USER_UNRESOLVED",
    "TOTALLY_UNKNOWN_REASON",
  ];
  for (const reason of reasons) {
    const port = recordingPort(rejected(reason));
    const executor = buildExecutor({ delegation: port });
    const result = await executor.execute(
      { callId: "c1", toolName: TOOL, input: VALID_INPUT },
      ctx({ permissions: [`tool:${TOOL}`] })
    );
    assert.equal(result.status, "FAILED", `${reason} 是装配/生命周期异常，必须是 FAILED`);
    assert.match(result.error ?? "", /spawn_agent 被拒/);
  }
});

// ---------------------------------------------------------------------------
// D 组 · 沙箱面（requiresSandbox:false ⇒ 前置不触发；两条返回路径都带端口）
// ---------------------------------------------------------------------------

test("D-1 · 无沙箱 + 端口装配 ⇒ SUCCESS（段 3 的沙箱前置不触发）", async () => {
  const port = recordingPort(accepted());
  const executor = buildExecutor({ delegation: port }); // 无 sandbox

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: VALID_INPUT },
    ctx({ permissions: [`tool:${TOOL}`] })
  );

  assert.equal(result.status, "SUCCESS", "spawn_agent 不需要沙箱 ⇒ 无沙箱也能过");
});

test("D-2 · 无沙箱 + 端口未装配 ⇒ 报的是「端口未装配」而非「需要沙箱」", async () => {
  const executor = buildExecutor(); // 无 sandbox、无 delegation

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: VALID_INPUT },
    ctx({ permissions: [`tool:${TOOL}`] })
  );

  assert.equal(result.status, "FAILED");
  assert.doesNotMatch(result.error ?? "", /需要沙箱/, "不得被沙箱前置拦下（它不是需沙箱工具）");
});

test("D-3 · 有沙箱 + 端口装配 ⇒ SUCCESS（#toolContext 的有沙箱返回路径也带端口）", async () => {
  const port = recordingPort(accepted());
  const executor = buildExecutor({ delegation: port, sandbox: fakeSandbox() });

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: VALID_INPUT },
    ctx({ permissions: [`tool:${TOOL}`] })
  );

  assert.equal(result.status, "SUCCESS", "有沙箱路径的 {...base, sandbox, session} 必须同样带上 delegation");
  assert.equal(port.calls.length, 1);
});

// ---------------------------------------------------------------------------
// E 组 · 输入校验（与 BUILTIN_TOOLS.inputSchema.required 同源）
// ---------------------------------------------------------------------------

test("E-1 · 缺 target_agent_id ⇒ VALIDATION_ERROR 语义的 FAILED（端口零调用）", async () => {
  const port = recordingPort(accepted());
  const executor = buildExecutor({ delegation: port });

  const result = await executor.execute(
    { callId: "c1", toolName: TOOL, input: { task: "t" } },
    ctx({ permissions: [`tool:${TOOL}`] })
  );

  assert.equal(result.status, "FAILED");
  assert.match(result.error ?? "", /target_agent_id 必须是非空字符串/);
  assert.equal(port.calls.length, 0, "校验不过不得到达端口");
});

test("E-2 · 缺 task ⇒ FAILED；budget_hint 非法 ⇒ FAILED", async () => {
  const port = recordingPort(accepted());
  const executor = buildExecutor({ delegation: port });
  const permissions = [`tool:${TOOL}`];

  const noTask = await executor.execute(
    { callId: "c1", toolName: TOOL, input: { target_agent_id: "a" } },
    ctx({ permissions })
  );
  assert.equal(noTask.status, "FAILED");
  assert.match(noTask.error ?? "", /task 必须是非空字符串/);

  const badBudget = await executor.execute(
    { callId: "c2", toolName: TOOL, input: { target_agent_id: "a", task: "t", budget_hint: 0 } },
    ctx({ permissions })
  );
  assert.equal(badBudget.status, "FAILED");
  assert.match(badBudget.error ?? "", /budget_hint 必须是正整数/);
  assert.equal(port.calls.length, 0, "两个非法入参都不得到达端口");
});
