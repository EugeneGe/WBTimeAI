/**
 * V0.3.1 · **T031-02 委派执行链**判据载体（D3 / D4 / D5 + S3 附加判据）。
 *
 * **入库回归测试**，不是临时探针。判据先行：实现方按本文件头部的《调用契约》写码，
 * 签名不符 ⇒ 用例保持红 ⇒ **须回报 QA 改判据，不得改断言迁就实现**（P0-0 步骤 ③）。
 *
 * 判据原文坐标（计划 §1③⑤⑦ + §3，逐字）
 * ------------------------------------
 *   - **D3 取消向下传播 100%**：`POST /runs/{parent}/cancel` 后，所有子 run 在 **≤30s**
 *     内到终态 `CANCELLED` 且沙箱被 `destroy()`。**前置**：必须至少 1 个子 run 走
 *     `code_exec` **真实占用沙箱**，否则 `destroy` 计数恒 0、判据真假绿 —— 该前置
 *     本身要断言（防"没沙箱也能绿"）。断言：子 run `status` 集合 == `{CANCELLED}`
 *     （集合全等）；非终态子 run 计数 == 0；`destroy` 调用计数 == 子 run 数。
 *   - **D4 预算超限必中断**：父下拨预算 `B`，子 run 消耗触顶**必中断**且父 run 正常
 *     收敛。子 run `token_usage` ≤ `B`；子 run 终态 ∈ `{CANCELLED, FAILED}`
 *     （**载体先按两种终态都接受写，实现方二选一登记后再收紧**）；取 `FAILED` 时
 *     `stop_reason ∈ {budget_tokens, budget_cost, budget_turns, budget_tools}`
 *     按实际触发维度取值 —— **`BUDGET_EXCEEDED` 不是 11 值词表内的值**（K-4 订正，
 *     词表 = `@wbtime/domain` 的 `STOP_REASONS`）；父 run 终态 `COMPLETED`（不崩）。
 *   - **D5 权限不越父**：子 run 权限 ⊆ 父 run 权限。`child.permission_scope` 码集合
 *     **⊆** `parent.permission_scope`（**集合包含**）；且子 run 调父未授权工具 →
 *     `DENY`（在 `tool_call` 行断言，非 HTTP）。
 *   - **S3 安全挂点（附加判据，不计入 D1–D10 十条）**：子任务文本 / 白名单 / 深度 /
 *     预算过 `SafetyStage=delegation`；**子 run `policy_version` == 父快照**（不等即红）；
 *     **拒绝走拒绝型 tool result**（不抛异常、不产生 4xx）且 `agent_run` 中
 *     `trigger == "subagent"` 行数 == 0（拒绝场景）。
 *   - **D8 并发闸单入口**（T031-04 接线后新增 §5）：用户入口经 `open_run` 判闸
 *     （`origin=USER` 显式传真）；「父 + 1 子」不 409（`origin=SUBAGENT` 豁免）；
 *     第二个用户主动 run **仍 409 且拒绝路径零落库**（消息不落、run 行数不增）；
 *     子 run 场景判闸**恒 1 次**（3a 前置一次，两条建行路径都不再判）。
 *   - **D10 origin / trigger 分离**（§6）：豁免判据**只认**应用层 `origin`
 *     （唯一豁免值 `"SUBAGENT"`）；`trigger` 仅作标记/审计、**永不参与放行**；
 *     客户端可达面（`RunRequest` 4 键）两者都到不了；`trigger=='subagent'` 的
 *     行必有 `spawn_agent` 父记录（SQL 审计，防"标记了却没有委派来源"的孤儿）。
 *
 * 载体的两条硬形态（与 spike / watermark 载体同款）
 * ----------------------------------------------
 *   ① **缺实现 = 断言失败，不是"无法 import"的崩溃**：T031-02 新增模块一律走
 *      守卫式动态导入（{@link loadModule}），缺失 ⇒ `found === false` ⇒
 *      `assert.equal(found, true, …)` 以 **`ERR_ASSERTION`** 红（exit 1）。
 *      行为判据（D3 的取消传播）走 **HTTP 真链路**，红在断言而非加载期。
 *   ② **单向断言一律配反向断言**：D3 配"无关 run 不得被传播取消"；D4 配"未触顶
 *      必不停 + 下拨 hint 超父不得上调"；D5 配"target ⊆ 父时交集 == target
 *      （防恒空集）+ 授权工具必须 ALLOW"；S3 配"接受场景子 run 行数 > 0"。
 *      仪器自证组：终态集合比较器 / 集合包含比较器 / destroy 计数器 / spawn 结果
 *      归一化各有自证用例。
 *
 * 调用契约（**本载体声明，T031-02 实现方按此接线**）
 * ------------------------------------------------
 *   宿主文件（按序探测，**任一存在即可**；导出可分散在多个宿主）：
 *     `apps/api/src/modules/run/delegation.ts`（推荐单文件）·
 *     `apps/api/src/modules/run/subagent-delegation.ts` ·
 *     `apps/api/src/modules/run/subagent-budget.ts` / `subagent-scope.ts` /
 *     `subagent-cancel.ts`；既有 `subagent-guard.ts` / `subagent-spawner.ts`
 *     也可作导出宿主（D1 已占用的导出名不冲突即可）。`guardRunCreation` 的宿主是
 *     `coordinator.ts`（spike 期已落地，D8/D10 用；探测列表末尾追加）。
 *
 *   1. `delegateSpawn(input)` —— 单对象入参
 *        `{ db, dialect, tenantId, parentRunId, targetAgentId, targetVersionId,
 *           conversationId, task, depth, maxDepth, budget?, parentPolicyVersion, sandbox? }`
 *      ⇒ `{ accepted: true, childRunId: string, policyVersion: string }`
 *       | `{ accepted: false, reason: string, stage?: string }`
 *       | 抛 `status === 409` 的 `HttpException`（多形态归一，同 spike 守卫）。
 *      子 run **只经应用层建**（`origin = SUBAGENT`），落 `agent_run.trigger = "subagent"`，
 *      并写 `subagent.started` / `subagent.rejected` 事件（S3 观察面）。
 *   2. `resolveChildBudget(parentBudget, hint)` —— 纯函数：下拨结果**逐维 ≤ 父**。
 *      预算形状 `{ maxTokens?, maxCost?, maxTurns?, maxTools? }`（数值，可部分缺省）。
 *   3. `applyChildBudget({ budget, usage })` —— 纯函数（**可**复用域判定
 *      `pickBudgetStopReason` / `BudgetLedger`）
 *      ⇒ `{ exceeded: boolean, stopReason?: "budget_tokens"|"budget_cost"|"budget_turns"|"budget_tools" }`。
 *      `exceeded === true` 时 `stopReason` 必与触发维度一致（K-4：不自造码）。
 *   4. `intersectPermissionScope(parentScope, targetScope)` —— 纯函数 ⇒ 码集合
 *      （`string[]`），语义 = **父 ∩ 目标**（⊆ 父；且 target ⊆ 父时 == target）。
 *   5. `isToolAllowedInScope(scope, toolName)` —— 纯函数 ⇒ `boolean`。
 *   6. `propagateCancel({ parentRunId, childRunIds, timeoutS })`
 *      ⇒ `{ cancelled: string[], pending: string[] }`。
 *      **D3 的主判据走 HTTP 真链路**（`POST /runs/{parent}/cancel`），不依赖本函数
 *      存在 —— 传播是**行为判据**；本函数是机制面出口，二者都验。
 *   7. `forgetDelegatedChildren(parentRunId)` —— 清进程内加速 Map（裁定 5：Map
 *      只是加速、非正确性依赖）。判据用它证明「Map 丢失后双源查询独立成立」。
 *   8. `delegateSpawn` 的**可选** `gateway?: ModelGatewayPort`（主理人 2026-10-23
 *      裁定 A-a / 裁定 10）：子 run 执行的模型网关；**用途仅限测试注入**与
 *      T031-04 生产装配，缺省 ⇒ 子 run 只建行、不启动执行（fail loud，不静默
 *      降级）。伴随可选字段 `coordinator?` / `userId?` / `settleTimeoutMs?` 已获
 *      有条件追认（条件 = 既有 19 条逐条通过，见台账）。
 *   9. 子 run 执行链产物（`tool_call` 行 / `sandbox_session` 行）由 `RunDriver`
 *      真驱动产生（裁定 1：复用既有 drive 循环，禁内联）；测试**注入既有脚本化
 *      假 Provider**（`routes-harness.mjs::fakeGateway`，过 fake 闸门，不新造）。
 *
 *  A-b 判据改造（QA 2026-10-23，主理人已批）
 *  --------------------------------------
 *   ① **D3-2 拆两层**（A-d 裁定）：**D3-2a**（机制面，归本批）= `propagateCancel`
 *      枚举子 run 并调用取消，子 run 由 `delegateSpawn` 真实建立并驱动（**废裸
 *      SQL 插行**）；**D3-2b**（端到端 HTTP 取消传播，归 **T031-04**）= 载体已
 *      建好但**未注册为 test**（显式标注 pending —— 注册会让控制组恒红，反例
 *      注入器的三条 case 会全部退成 UNEVALUABLE）。
 *   ② **D5-4 改注入网关**：子 run 必须真跑起来，`DENIED` 才能由真实
 *      `ToolExecutor` 权限链落（裁定 7）。
 *   ③ **「是否等收敛」两档相反**（附加 C）：D5-4 取 `settleTimeoutMs` 等收敛；
 *      D3-2a/D3-2b 取「不等」（cancel 到达时子 run 必须仍未终态）。
 *
 *   观察面口径（DDL 实测）：`destroy()` 的落库口径是 `sandbox_session.ended_at`
 *   （`sandbox/types.ts`："`destroy` 写 `ended_at`，重复调用不改写已有值"）⇒
 *   "destroy 调用计数"取 `sandbox_session` 中 `run_id ∈ 子集合 且 ended_at 非空`
 *   的 **distinct run 计数**。子 run 的 `code_exec` `tool_call` 行与
 *   `sandbox_session` 行**必须由执行链产生** —— 测试不代插（否则前置恒真 = 自导自演）。
 *
 * 复跑（与 G031-4 · S2 同款）
 * -------------------------
 *   `cd D:/WBT/WBTimeAI && node --experimental-sqlite --test apps/api/tests/subagent-delegation.test.mjs`
 *   退出码：**1** = 载体在、门禁未过；文件不存在 = **2**（判据载体缺失，属"未落地"）。
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { AgentRunRepo } from "@wbtime/db";
import * as domain from "@wbtime/domain";

import { errorOf, makeApp, request, TENANT_ID, fakeGateway } from "./routes-harness.mjs";
import {
  createAgentWithVersion,
  createConversation,
  seedWorkspace,
  WORKSPACE_ID,
} from "./fixtures/run-fixture.mjs";

// ---------------------------------------------------------------------------
// §-1 · 常量与夹具（钉在名字上；测试**不**代插执行链产物）
// ---------------------------------------------------------------------------

/** 取消传播时限（对齐 py `cancellation.py:16` `DEFAULT_RECLAIM_TIMEOUT_S = 30`）。 */
const CANCEL_PROPAGATION_DEADLINE_MS = 30_000;

/** D4 的四个预算维度（K-4 订正：`BUDGET_EXCEEDED` 不是词表内的 `stop_reason`）。 */
const BUDGET_DIMENSIONS = Object.freeze([
  { key: "maxTokens", usageKey: "tokens", stopReason: "budget_tokens" },
  { key: "maxCost", usageKey: "cost", stopReason: "budget_cost" },
  { key: "maxTurns", usageKey: "turns", stopReason: "budget_turns" },
  { key: "maxTools", usageKey: "tools", stopReason: "budget_tools" },
]);

const BUDGET_STOP_REASONS = Object.freeze([
  "budget_tokens",
  "budget_cost",
  "budget_turns",
  "budget_tools",
]);

/**
 * 子 run 驱动脚本（改造 2：注入**既有**的脚本化假 Provider）。
 *
 * `routes-harness.mjs::fakeGateway` = V0.3.0 运行时 e2e 就有的那一个（
 * `buildModelStack({ kind: "fake", allowFakeProvider: true })`，过
 * `WBTIME_AI_ALLOW_FAKE_PROVIDER=1` 闸门）—— **复用，不新造**：生产代码里
 * 自建假 Provider 是红线（裁定 10 / A-b）。`RunDriverDeps.gateway` 缺省 ⇒
 * run 入口 fail loud（`CONFIGURATION_ERROR`）⇒ 不给网关子 run 跑不起来。
 *
 * 脚本里**同时**放越权与授权两个调用，是为了让 D5-4 的主判据与反向断言
 * 在同一轮执行链上同时成立：
 *   - `filesystem` 读绝对路径 `/etc/passwd` ⇒ 越出子 run 的 Workspace 边界 ⇒
 *     真实 `ToolExecutor` 的路径守卫（`ToolContext` 的 scope 收窄原语，裁定 7）
 *     返回 `PERMISSION_DENIED` ⇒ `tool_call.status = 'DENIED'`（**只能由真实
 *     权限链落，测试不代插**）；
 *   - `code_exec` 是 scope 内的内置工具 ⇒ **不得**被 DENY（反向断言，防"一律
 *     DENY"假实现）；未装配沙箱 ⇒ `FAILED`，不是 `DENIED`，反向断言仍成立。
 *
 * 假 Provider 每次 `stream()` 都从同一脚本起播（`createFakeProvider` 的口径）
 * ⇒ 确定性；驱动轮数由 `DEFAULT_STOP_LIMITS.maxModelTurns = 20` 收敛。
 */
const CHILD_DRIVE_SCRIPT = Object.freeze([
  { type: "text_delta", text: "我先读一个系统文件，再跑一段代码" },
  {
    type: "tool_call",
    id: "call-fs-overscope",
    name: "filesystem",
    input: { action: "read", path: "/etc/passwd" },
  },
  {
    type: "tool_call",
    id: "call-ce-in-scope",
    name: "code_exec",
    input: { command: "echo ok" },
  },
  { type: "usage", usage: { prompt_tokens: 4, completion_tokens: 2, total_tokens: 6 } },
  { type: "finish", reason: "model_finish" },
]);

/**
 * D5-4 等子 run 收敛的上限（`delegateSpawn` 的可选 `settleTimeoutMs`）。
 *
 * 取 5s 而不是 30s：实测子 run 约 0.5s 收敛（`budget_turns`），5s 已有 10 倍余量；
 * 且 `RunDriver.awaitSettled` 是 `Promise.race([pending, sleep(timeoutMs)])` ——
 * `pending` 先赢时 `sleep` 的定时器**不会**被取消，会原样拖住进程退出 ⇒ 取值越大
 * 判据文件的收尾越慢（这是复用既有入口的代价，登记在此，不在源码侧顺手修）。
 *
 * 附加 C：「是否等收敛」**两档相反**，按用例分别设定，不用同一档 ——
 *   - D5-4 要断言执行产物（`tool_call` 行）⇒ 取**等收敛**档（`settleTimeoutMs`）；
 *   - D3-2a 要断言「cancel 到达时子 run 仍未终态」⇒ 取**不等**档（不传该字段，
 *     与 `RunDriver.start` 的 HTTP 侧口径一致：异步驱动）。
 */
const CHILD_SETTLE_TIMEOUT_MS = 5_000;

/** 造一条 run（trigger 可指定 —— 与 `fixtures/run-fixture.mjs` 的 `seedRun` 同列集）。 */
function seedRunRow(fixture, options) {
  const id = randomUUID();
  fixture.raw
    .prepare(
      `insert into agent_run
         (id, tenant_id, agent_id, agent_version_id, conversation_id, user_id,
          trigger, run_mode, status, started_at, completed_at, duration_ms,
          token_usage, success, error_type, error, stop_reason,
          tool_error_count, cost_estimated, cost_status)
       values (?, ?, ?, ?, ?, ?, ?, 'INLINE', ?, ?, ?, ?, '{}', ?, ?, ?, ?, 0, 0, 'UNPRICED')`
    )
    .run(
      id,
      options.tenantId ?? TENANT_ID,
      options.agentId,
      options.versionId,
      options.conversationId,
      options.userId === undefined ? fixture.userId : options.userId,
      options.trigger ?? "user",
      options.status ?? "QUEUED",
      options.startedAt ?? "2026-10-23 00:00:00",
      options.completedAt ?? null,
      options.durationMs ?? null,
      options.success ?? null,
      options.errorType ?? null,
      options.error ?? null,
      options.stopReason ?? null
    );
  return id;
}

/** 造一条 `sandbox_session`（**仅仪器自证用**；判据路径禁止代插 —— 见文件头口径）。 */
function seedSandboxSession(fixture, options) {
  const id = randomUUID();
  fixture.raw
    .prepare(
      "insert into sandbox_session (id, tenant_id, run_id, workspace_id, provider, status, workdir, ended_at) " +
        "values (?, ?, ?, ?, 'local-process', ?, ?, ?)"
    )
    .run(id, TENANT_ID, options.runId, WORKSPACE_ID, options.status ?? "ACTIVE", "/tmp/wbtime-test", options.endedAt ?? null);
  return id;
}

/** 造一条 `tool_call`（**仅仪器自证用**，同上）。 */
function seedToolCall(fixture, options) {
  const id = randomUUID();
  fixture.raw
    .prepare(
      "insert into tool_call (id, run_id, tool_name, tool_type, attempt, input, output, status, sandbox_session_id) " +
        "values (?, ?, ?, 'builtin', 1, '{}', '{}', ?, ?)"
    )
    .run(id, options.runId, options.toolName, options.status ?? "SUCCESS", options.sandboxSessionId ?? null);
  return id;
}

/** run 的终态集合（与域 `isTerminalRunStatus` 同口径，此处显式枚举）。 */
const TERMINAL_STATUSES = Object.freeze(["SUCCEEDED", "FAILED", "CANCELLED"]);

// ---------------------------------------------------------------------------
// §0 · 守卫式解析 + 观察面仪器（"缺实现 = 断言失败"的机械装置）
// ---------------------------------------------------------------------------

const DELEGATION_HOSTS = Object.freeze([
  "../dist/modules/run/delegation.js",
  "../dist/modules/run/subagent-delegation.js",
  "../dist/modules/run/subagent-budget.js",
  "../dist/modules/run/subagent-scope.js",
  "../dist/modules/run/subagent-cancel.js",
  "../dist/modules/run/subagent-guard.js",
  "../dist/modules/run/subagent-spawner.js",
  // D8/D10 的 `guardRunCreation` 宿主（spike 期已落地在 coordinator.ts；探测列表
  // 末尾追加 —— 它不导出上面任何候选名，不影响其余 pickExport 的首中次序）。
  "../dist/modules/run/coordinator.js",
]);

/** @returns {{found: boolean, module: object|null, spec: string, reason: string}} */
async function loadModule(spec) {
  try {
    return { found: true, module: await import(spec), spec, reason: "" };
  } catch (error) {
    return {
      found: false,
      module: null,
      spec,
      reason: `${spec} :: ${error.code ?? error.constructor.name}`,
    };
  }
}

/**
 * 在若干候选模块里按名字找导出（候选宿主**全部加载**，命中即返回）。
 *
 * @param {Array<{found: boolean, module: object|null, spec: string, reason: string}>} loaded
 * @param {string[]} names 候选导出名（按优先级）。
 * @returns {{found: boolean, name: string|null, value: unknown, tried: string[]}}
 */
function pickExport(loaded, names) {
  const tried = [];
  for (const entry of loaded) {
    if (!entry.found || entry.module === null) {
      tried.push(entry.reason);
      continue;
    }
    for (const name of names) {
      const value = entry.module[name];
      if (value !== undefined) return { found: true, name, value, tried };
      tried.push(`${entry.spec} 无导出 ${name}`);
    }
  }
  return { found: false, name: null, value: null, tried };
}

/** run 状态集合（Set<string>）。 */
function statusSet(rows) {
  return new Set(rows.map((row) => row.status));
}

/** 码集合归一：`string[]` / `Set<string>` 都收，产出 `Set<string>`。 */
function scopeCodes(scope) {
  if (scope === null || scope === undefined) return new Set();
  if (scope instanceof Set) return new Set([...scope].map(String));
  if (Array.isArray(scope)) return new Set(scope.map(String));
  if (typeof scope === "object") return new Set(Object.keys(scope));
  return new Set();
}

/**
 * 集合包含：`child ⊆ parent`（D5 的判定仪器）。
 *
 * 空集 ⊆ 任何集合 —— 这是**合法**结论（交集可以 legitimately 为空），判据用
 * 「target ⊆ 父时交集必须 == target」的反向断言另防"恒空集"假实现。
 *
 * @param {Set<string>} child
 * @param {Set<string>} parent
 * @returns {{ok: boolean, violations: string[]}}
 */
function isSubset(child, parent) {
  const violations = [...child].filter((code) => !parent.has(code)).map((code) => `${code} ∈ child 但 ∉ parent`);
  return { ok: violations.length === 0, violations };
}

/**
 * destroy 调用计数（D3 观察面）：`sandbox_session` 中 `run_id ∈ runIds 且
 * `ended_at` 非空` 的 **distinct run 计数**（`destroy` 的落库口径是写 `ended_at`）。
 *
 * @param {import("node:sqlite").DatabaseSync} raw
 * @param {string[]} runIds
 */
function destroyedRunCount(raw, runIds) {
  if (runIds.length === 0) return 0;
  const placeholders = runIds.map(() => "?").join(",");
  return raw
    .prepare(
      `select count(distinct run_id) as n from sandbox_session where run_id in (${placeholders}) and ended_at is not null`
    )
    .get(...runIds).n;
}

/**
 * 把一次"派生调用"归一成 `{ recognized, accepted }`。
 *
 * `recognized: false` ⇔ 返回值/异常不属于任何已声明形态 ⇒ 调用方必须先断言
 * `recognized === true`（防"返回 undefined 被误读成接受/拒绝"的假绿）。
 *
 * @param {unknown} value 返回值或抛出的异常。
 */
function normalizeSpawnOutcome(value) {
  if (value === null || value === undefined) {
    return { recognized: false, accepted: false, shape: "undefined" };
  }
  const status = value?.status ?? value?.statusCode;
  if (status === 409 || value?.code === "CONFLICT" || value?.code === "RUN_CONFLICT") {
    return { recognized: true, accepted: false, shape: "409" };
  }
  if (typeof value === "object") {
    for (const key of ["accepted", "ok", "allowed", "spawned"]) {
      if (typeof value[key] === "boolean") {
        return { recognized: true, accepted: value[key] === true, shape: `${key}=${value[key]}` };
      }
    }
    if (typeof value.childRunId === "string" && value.childRunId !== "") {
      return { recognized: true, accepted: true, shape: "childRunId" };
    }
    for (const key of ["rejected", "blocked", "denied"]) {
      if (typeof value[key] === "boolean") {
        return { recognized: true, accepted: value[key] === false, shape: `${key}=${value[key]}` };
      }
    }
  }
  return { recognized: false, accepted: false, shape: typeof value };
}

/**
 * 轮询直到 `predicate` 为真或超时（D3 的 ≤30s 观察面；不抛错，结果看 `met`）。
 *
 * @param {() => boolean} predicate
 * @param {number} deadlineMs
 * @param {number} [intervalMs]
 * @returns {{met: boolean, elapsedMs: number}}
 */
async function pollUntil(predicate, deadlineMs, intervalMs = 250) {
  const startedAt = Date.now();
  for (;;) {
    if (predicate()) return { met: true, elapsedMs: Date.now() - startedAt };
    if (Date.now() - startedAt >= deadlineMs) {
      return { met: false, elapsedMs: Date.now() - startedAt };
    }
    await new Promise((resolve) => {
      setTimeout(resolve, intervalMs);
    });
  }
}

/** 造父 run 链（workspace → agent → version → conversation），返回链 id。 */
async function seedChain(fixture, name = "delegation-agent") {
  seedWorkspace(fixture);
  const { agentId, versionId } = await createAgentWithVersion(fixture, name);
  const conversationId = await createConversation(fixture, agentId);
  return { agentId, versionId, conversationId };
}

/** 读一个 run 的行。 */
function runRow(fixture, runId) {
  return fixture.raw.prepare("select * from agent_run where id = ?").get(runId);
}

// 顶层一次性解析（不抛错；缺实现只体现在 `found === false`）。
const MODULES = {
  hosts: await Promise.all(DELEGATION_HOSTS.map((spec) => loadModule(spec))),
};

const SPAWN_FN = pickExport(MODULES.hosts, ["delegateSpawn", "spawnSubagent", "delegate"]);
const BUDGET_RESOLVE_FN = pickExport(MODULES.hosts, [
  "resolveChildBudget",
  "allocateBudget",
  "deriveChildBudget",
]);
const BUDGET_APPLY_FN = pickExport(MODULES.hosts, [
  "applyChildBudget",
  "checkChildBudget",
  "enforceBudget",
]);
const SCOPE_INTERSECT_FN = pickExport(MODULES.hosts, [
  "intersectPermissionScope",
  "intersectScope",
  "narrowScope",
]);
const SCOPE_ALLOWS_FN = pickExport(MODULES.hosts, [
  "isToolAllowedInScope",
  "isToolAllowed",
  "scopeAllows",
]);
const CANCEL_FN = pickExport(MODULES.hosts, ["propagateCancel", "cancelDownstream", "cancelChildren"]);
// D8/D10：并发闸判定函数（`coordinator.ts` 导出；调用方 = `delegateSpawn` 3a 与
// T031-04 接线的 `run-service.ts::open_run`）。
const GUARD_FN = pickExport(MODULES.hosts, ["guardRunCreation", "guard_run_creation"]);
const FORGET_CHILDREN_FN = pickExport(MODULES.hosts, [
  "forgetDelegatedChildren",
  "forgetDelegatedChild",
  "clearDelegatedChildren",
]);

/**
 * D10① 结构面：`RunRequestSchema` 的键集合（**静态读 schema 模块**，不手抄名单
 * —— 手抄就等于把"契约面"复制成第二份会漂移的真相源）。
 */
const RUN_REQUEST_SCHEMA = await loadModule("../dist/routes/schemas-run.js");

// ---------------------------------------------------------------------------
// §0 · 仪器自证（先证明"尺子"是准的，再拿它去量实现）
// ---------------------------------------------------------------------------

test("0-1 · 仪器自证：终态集合比较器（D3 的「集合全等」口径）", () => {
  assert.deepEqual([...statusSet([{ status: "CANCELLED" }, { status: "CANCELLED" }])], ["CANCELLED"]);
  assert.equal(statusSet([{ status: "CANCELLED" }, { status: "RUNNING" }]).size, 2);
  assert.equal(
    statusSet([{ status: "CANCELLED" }, { status: "CANCELLED" }]).size,
    1,
    "同值多行归一为单元素 —— 「集合全等」不是行数相等"
  );
  assert.equal(TERMINAL_STATUSES.length, 3);
});

test("0-2 · 仪器自证：集合包含比较器（D5 ⊆ 口径 + 反向检测）", () => {
  const parent = new Set(["tool.a", "tool.b", "tool.c"]);
  // 正向：子集。
  assert.deepEqual(isSubset(new Set(["tool.b"]), parent), { ok: true, violations: [] });
  // 反向 ①：透传形态（含父没有的码）必须被抓出。
  const passthrough = isSubset(new Set(["tool.b", "tool.d"]), parent);
  assert.equal(passthrough.ok, false);
  assert.match(passthrough.violations[0], /tool\.d/);
  // 反向 ②：空集 ⊆ 任何集合是合法结论（判据用「target ⊆ 父时交集 == target」另防恒空）。
  assert.equal(isSubset(new Set(), parent).ok, true);
  // scopeCodes 归一：数组 / Set / 对象键三种形态。
  assert.deepEqual([...scopeCodes(["x", "y"])].sort(), ["x", "y"]);
  assert.deepEqual([...scopeCodes(new Set(["x"]))], ["x"]);
  assert.deepEqual([...scopeCodes({ x: true })], ["x"]);
});

test("0-3 · 仪器自证：destroy 计数器（distinct run 口径 + ended_at 非空）", () => {
  // 仪器自证用内存库最小表（不经 buildApp —— 这里只验证 SQL 口径，不验证 DDL）。
  const raw = new DatabaseSync(":memory:");
  raw.exec("create table sandbox_session (id text primary key, run_id text, ended_at text)");
  const r1 = "run-1";
  const r2 = "run-2";
  // run-1：一个已 destroy + 一个未 destroy（重复调用不改写 ⇒ 仍算 1 个 run）。
  seedSandboxSessionForRaw(raw, { runId: r1, endedAt: "2026-10-23 00:00:01" });
  seedSandboxSessionForRaw(raw, { runId: r1, endedAt: null });
  // run-2：未 destroy。
  seedSandboxSessionForRaw(raw, { runId: r2, endedAt: null });
  assert.equal(destroyedRunCount(raw, [r1, r2]), 1, "只数 ended_at 非空的 distinct run");
  assert.equal(destroyedRunCount(raw, []), 0, "空子集合 ⇒ 0（不是 SQL 报错）");
  raw.close();
});

/** 0-3 专用：绕过夹具的最小插入（与 {@link seedSandboxSession} 同列集）。 */
function seedSandboxSessionForRaw(raw, options) {
  raw
    .prepare("insert into sandbox_session (id, run_id, ended_at) values (?, ?, ?)")
    .run(randomUUID(), options.runId, options.endedAt ?? null);
}

test("0-4 · 仪器自证：spawn 结果归一化对 undefined 判 unrecognized（防假绿）", () => {
  assert.deepEqual(normalizeSpawnOutcome(undefined), { recognized: false, accepted: false, shape: "undefined" });
  assert.deepEqual(normalizeSpawnOutcome({ accepted: true, childRunId: "r" }).accepted, true);
  assert.deepEqual(normalizeSpawnOutcome({ accepted: false, reason: "x" }).accepted, false);
  assert.deepEqual(normalizeSpawnOutcome({ childRunId: "r" }).accepted, true, "只给 childRunId 也算接受形态");
  assert.equal(normalizeSpawnOutcome({ status: 409 }).accepted, false, "409 ⇒ 拒绝形态");
});

test("0-5 · 仪器自证：四个预算维度与 stop_reason 词表对齐（K-4：不自造码）", () => {
  assert.deepEqual(
    BUDGET_STOP_REASONS.map((reason) => domain.STOP_REASONS.includes(reason)),
    [true, true, true, true],
    "4 个 budget_* 都必须在 11 值词表内"
  );
  assert.deepEqual(
    BUDGET_DIMENSIONS.map((dimension) => dimension.stopReason),
    [...BUDGET_STOP_REASONS],
    "维度 ↔ stop_reason 一一对应（耗尽项与码必须匹配）"
  );
  assert.equal(domain.STOP_REASONS.includes("BUDGET_EXCEEDED"), false, "BUDGET_EXCEEDED 不是合法 stop_reason（K-4）");
});

// ---------------------------------------------------------------------------
// §1 · D3 · 取消向下传播 100%（HTTP 真链路 + destroy 落库口径）
// ---------------------------------------------------------------------------

test("D3-1 · 判据载体：trigger 标记值与 cancel 端点就位", async () => {
  assert.equal(
    domain.RUN_TRIGGER_SUBAGENT,
    "subagent",
    `domain 必须导出 RUN_TRIGGER_SUBAGENT = "subagent"（零 DDL 方案的标记值）；实测 ${String(domain.RUN_TRIGGER_SUBAGENT)}`
  );
  const fixture = await makeApp({ username: "del-d31" });
  try {
    const chain = await seedChain(fixture, "d3-agent");
    const runId = seedRunRow(fixture, { ...chain, status: "RUNNING" });
    const response = await request(fixture, "POST", `/api/v1/runs/${runId}/cancel`);
    assert.equal(response.statusCode, 200, "cancel 端点必须存在（D3 的入口）");
    assert.equal(runRow(fixture, runId).status, "CANCELLED");
  } finally {
    await fixture.close();
  }
});

/**
 * **D3-2a · 机制面（归本批 T031-02）** —— 主理人 2026-10-23 A-d 裁定拆层后的
 * 单元层判据：`propagateCancel` 能**枚举子 run 并调用取消**。
 *
 * 为什么子 run 改由 `delegateSpawn` 建（改造 1）：原形态用 {@link seedRunRow}
 * **裸 SQL** 直接插子 run 行，随后断言 `tool_call` 里已有 `code_exec` +
 * `sandbox_session_id` —— 裸插行没过任何应用入口、`makeApp()` 未开 `model` 栈、
 * 无任何后台驱动 ⇒ 不存在任何时刻能让执行链为它们产出执行链产物。那是**判据
 * 形态问题，不是实现问题**。废裸 SQL 插行，改由 `delegateSpawn` 真实建立并驱动。
 *
 * 两条必须显式钉住的机械装置：
 *   ① **清进程内 Map**（裁定 5）：`DELEGATED_CHILDREN` 只是**加速缓存**，不是
 *      正确性依赖。不清 Map ⇒ 枚举走 Map ⇒「双源发现链路断了」这个反例被 Map
 *      掩盖 ⇒ 红证恒绿（假绿）。清掉后，`propagateCancel` 只能凭 tool_call 行查
 *      + `agent_event` 交叉验证独立发现子 run。
 *   ② **未终态前置**（附加 C）：cancel 到达时子 run 必须仍未终态，否则
 *      「CAS 收敛到 CANCELLED」与「本来就已跑完」不可区分 = 判据真假绿。
 *      ⇒ 本用例取「不等收敛」档（不传 `settleTimeoutMs`），与 D5-4 的
 *      「等收敛」档**相反**，两档不混用。
 */
test("D3-2a · 机制面：propagateCancel 枚举子 run 并调用取消（Map 已清 ⇒ 双源发现独立成立）", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  assert.equal(CANCEL_FN.found, true, `前置：propagateCancel 未就位（${CANCEL_FN.tried.join(" | ")}）`);
  assert.equal(
    FORGET_CHILDREN_FN.found,
    true,
    `前置：必须导出 forgetDelegatedChildren —— 进程内 Map 只是加速（裁定 5），判据必须能清掉它，` +
      `否则「发现链路」被 Map 掩盖、反例红证恒绿；实测：${FORGET_CHILDREN_FN.tried.join(" | ")}`
  );

  const fixture = await makeApp({ username: "del-d32a" });
  try {
    const chain = await seedChain(fixture, "d3-parent-agent");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });

    // 无关对照 run：另一条会话的 RUNNING 用户 run —— 传播范围必须**恰好**是子集合。
    // **先建无关 run，再派生子 run**：让「派生 → 立即验未终态前置」之间的异步间隙
    // 尽量短（驱动循环约 0.5s 收敛到终态，间隙越长竞态窗口越大）。
    const otherConversationId = await createConversation(fixture, chain.agentId);
    const unrelatedRunId = seedRunRow(fixture, {
      ...chain,
      conversationId: otherConversationId,
      status: "RUNNING",
    });

    // 子 run 由 delegateSpawn **真实建立并驱动**（废裸 SQL 插行）。
    const childRunIds = [];
    for (const index of [0, 1]) {
      const outcome = await probeSpawn(SPAWN_FN.value, {
        db: fixture.connection.db,
        dialect: "sqlite",
        tenantId: TENANT_ID,
        parentRunId,
        targetAgentId: chain.agentId,
        targetVersionId: chain.versionId,
        conversationId: chain.conversationId,
        task: `D3-2a 子任务 ${index}`,
        depth: 0,
        maxDepth: 1,
        gateway: fakeGateway(CHILD_DRIVE_SCRIPT),
      });
      assert.equal(
        outcome.normalized.recognized,
        true,
        `派生必须返回已声明形态（实测 ${outcome.normalized.shape}）`
      );
      assert.equal(
        outcome.normalized.accepted,
        true,
        `子 run 必须由 delegateSpawn 建（实测 ${outcome.normalized.shape}）`
      );
      childRunIds.push(String(outcome.raw.childRunId ?? ""));
    }
    assert.deepEqual(
      childRunIds.map((id) => runRow(fixture, id).trigger),
      ["subagent", "subagent"],
      "子 run 必须落 trigger='subagent'（D1③ / D3 发现的语义前提；裸插行不会有这个标记）"
    );

    // 前置 ②（附加 C）：cancel 到达时子 run 仍未终态。
    const beforeCancel = childRunIds.map((id) => runRow(fixture, id).status);
    assert.deepEqual(
      beforeCancel.map((status) => TERMINAL_STATUSES.includes(status)),
      [false, false],
      `前置：cancel 到达时子 run 必须仍未终态（否则「收敛到 CANCELLED」不可判、判据真假绿）；` +
        `实测 [${beforeCancel.join(", ")}]`
    );

    // 前置 ①（裁定 5）：清掉进程内加速 Map ⇒ 双源发现必须独立成立。
    FORGET_CHILDREN_FN.value(parentRunId);

    const result = await CANCEL_FN.value({
      parentRunId,
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      timeoutS: 30,
    });
    assert.deepEqual(
      [...new Set(result.cancelled)].sort(),
      [...childRunIds].sort(),
      `propagateCancel 必须枚举到**全部**子 run 并调用取消（Map 已清 ⇒ 只能靠双源发现），` +
        `否则子 run 恒不收敛到 CANCELLED；实测 cancelled=${JSON.stringify(result.cancelled)}`
    );
    assert.deepEqual(
      [...result.pending].sort(),
      [],
      "不得有子 run 停在 pending（≤30s 内必须全部收敛到终态）"
    );
    const statuses = childRunIds.map((id) => runRow(fixture, id).status);
    assert.deepEqual(
      [...statusSet(statuses.map((status) => ({ status })))],
      ["CANCELLED"],
      "子 run status 集合 == {CANCELLED}（集合全等，不是行数相等）；" +
        `实测 [${statuses.join(", ")}]`
    );

    // **反向断言**：传播范围恰好是子集合 —— 无关 run 不得被连带取消。
    assert.equal(
      runRow(fixture, unrelatedRunId).status,
      "RUNNING",
      "取消向下传播只作用于子 run；无关 RUNNING run 被连带取消 = 传播越界 ⇒ 红"
    );
  } finally {
    await fixture.close();
  }
});

/**
 * **D3-2b · 端到端 HTTP 取消传播 —— 移交 T031-04 · 当前 pending（未注册为 test）**
 *
 * 主理人 2026-10-23 A-d 裁定：D3 拆两层 —— D3-2a（机制面）归本批 T031-02；
 * D3-2b（行为面，`POST /runs/{parent}/cancel` ⇒ 子 run ≤30s 到 CANCELLED +
 * 沙箱 destroy 计数 == 子 run 数）归 **T031-04**。
 *
 * **为什么 pending**：该链路的接线必经 `routes/runs.ts`（T031-05）→
 * `coordinator.ts::RunCoordinator.cancel`（T031-04）—— 二者都不在 T031-02
 * 文件域，`coordinator.ts` 至今**未调** `propagateCancel`。此处**把载体先建好**
 * 并登记移交单四项，**不注册为 `test()`**：注册会让控制组恒红（⇒ 反例注入器
 * 三条 case 全部退成 UNEVALUABLE），那是拿门禁换形式。
 *
 * 收口执行人（T031-04）只需两步：把本函数体 `test(...)` 注册 + 注入沙箱端口
 * （`delegateSpawn` 的 `sandbox?` 已备好注入位；判据**不**代插 `sandbox_session`
 * 行 —— 文件头口径）。
 *
 * 判红手法（写进移交单）：`coordinator.ts::RunCoordinator.cancel` 不调
 * `propagateCancel`（或子探针不组合父探针）⇒ 子 run 恒 `RUNNING` /
 * destroy 计数 0 ⇒ 本函数**必红**。
 *
 * @returns 观察面快照（供 T031-04 收口时贴台账）。
 */
export async function d3_2b_httpCancelPropagation() {
  const fixture = await makeApp({ username: "del-d32b" });
  try {
    const chain = await seedChain(fixture, "d3b-parent-agent");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });
    const childRunIds = [];
    for (const index of [0, 1]) {
      const outcome = await probeSpawn(SPAWN_FN.value, {
        db: fixture.connection.db,
        dialect: "sqlite",
        tenantId: TENANT_ID,
        parentRunId,
        targetAgentId: chain.agentId,
        targetVersionId: chain.versionId,
        conversationId: chain.conversationId,
        task: `D3-2b 子任务 ${index}`,
        depth: 0,
        maxDepth: 1,
        gateway: fakeGateway(CHILD_DRIVE_SCRIPT),
      });
      if (outcome.normalized.accepted !== true) {
        throw new Error(`派生必须成功（D3-2b 前提）；实测 ${outcome.normalized.shape}`);
      }
      childRunIds.push(String(outcome.raw.childRunId ?? ""));
    }
    const otherConversationId = await createConversation(fixture, chain.agentId);
    const unrelatedRunId = seedRunRow(fixture, {
      ...chain,
      conversationId: otherConversationId,
      status: "RUNNING",
    });

    // 前置：至少 1 个子 run 走 code_exec **真实**占用沙箱。这些行必须由执行链
    // 产生 —— 测试不代插（代插 = 前置恒真 = 自导自演）。
    const sandboxed = fixture.raw
      .prepare(
        "select count(*) as n from tool_call where run_id in (?, ?) and tool_name = 'code_exec' " +
          "and sandbox_session_id is not null"
      )
      .get(...childRunIds).n;
    if (sandboxed < 1) {
      throw new Error(
        "前置：必须至少 1 个子 run 经 code_exec 真实占用沙箱（否则 destroy 计数恒 0、判据真假绿）；" +
          `实测 code_exec+sandbox 行数 = ${sandboxed} —— 执行链未产生 ⇒ 判据不可判`
      );
    }

    const cancelled = await request(fixture, "POST", `/api/v1/runs/${parentRunId}/cancel`);
    assert.equal(cancelled.statusCode, 200, "父 cancel 成功");

    // ≤30s 内所有子 run 到终态 CANCELLED（对齐 DEFAULT_RECLAIM_TIMEOUT_S = 30）。
    const wait = await pollUntil(() => {
      const rows = childRunIds.map((id) => runRow(fixture, id));
      return rows.every((row) => TERMINAL_STATUSES.includes(row.status));
    }, CANCEL_PROPAGATION_DEADLINE_MS);
    const statuses = childRunIds.map((id) => runRow(fixture, id));
    assert.equal(
      wait.met,
      true,
      `子 run 必须在 ${CANCEL_PROPAGATION_DEADLINE_MS / 1000}s 内到终态（取消向下传播 100%）；` +
        `实测终态集合 [${statuses.map((row) => row.status).join(", ")}]`
    );
    assert.deepEqual(
      [...statusSet(statuses)],
      ["CANCELLED"],
      "子 run status 集合 == {CANCELLED}（集合全等，不是行数相等）"
    );

    // 沙箱被回收：destroy 调用计数 == 子 run 数（落库口径 = ended_at 非空的 distinct run）。
    assert.equal(
      destroyedRunCount(fixture.raw, childRunIds),
      childRunIds.length,
      "每个子 run 的沙箱都必须被 destroy()（D3：取消传播的机制面）"
    );

    // **反向断言**：传播范围恰好是子集合 —— 无关 run 不得被连带取消。
    assert.equal(
      runRow(fixture, unrelatedRunId).status,
      "RUNNING",
      "取消向下传播只作用于子 run；无关 RUNNING run 被连带取消 = 传播越界 ⇒ 红"
    );
    assert.equal(wait.elapsedMs <= CANCEL_PROPAGATION_DEADLINE_MS, true, "实测耗时不得超 30s 上限");
    return {
      childRunIds,
      childStatuses: statuses.map((row) => row.status),
      destroyedRunCount: destroyedRunCount(fixture.raw, childRunIds),
      unrelatedStatus: runRow(fixture, unrelatedRunId).status,
    };
  } finally {
    await fixture.close();
  }
}


test("D3-3 · 机制面出口：propagateCancel 就位且接受单对象入参（行为判据之外的接口契约）", () => {
  assert.equal(
    CANCEL_FN.found,
    true,
    `委派链必须导出 propagateCancel / cancelDownstream / cancelChildren 之一（D3 的机制面出口）；` +
      `实测：${CANCEL_FN.tried.join(" | ")}`
  );
  assert.equal(typeof CANCEL_FN.value, "function", `实测 ${typeof CANCEL_FN.value}`);
});

// ---------------------------------------------------------------------------
// §2 · D4 · 预算下拨与超限必中断
// ---------------------------------------------------------------------------

test("D4-1 · 判据载体：下拨与预算闸两导出就位", () => {
  assert.equal(
    BUDGET_RESOLVE_FN.found,
    true,
    `必须导出 resolveChildBudget / allocateBudget / deriveChildBudget 之一（D4 下拨）；实测：${BUDGET_RESOLVE_FN.tried.join(" | ")}`
  );
  assert.equal(
    BUDGET_APPLY_FN.found,
    true,
    `必须导出 applyChildBudget / checkChildBudget / enforceBudget 之一（D4 预算闸）；实测：${BUDGET_APPLY_FN.tried.join(" | ")}`
  );
  assert.equal(typeof BUDGET_RESOLVE_FN.value, "function");
  assert.equal(typeof BUDGET_APPLY_FN.value, "function");
});

test("D4-2 · 下拨不越父：逐维 ≤ 父；hint 超父必须 cap（双向）", () => {
  assert.equal(BUDGET_RESOLVE_FN.found, true, `前置：下拨导出未就位（${BUDGET_RESOLVE_FN.tried.join(" | ")}）`);
  const parentBudget = { maxTokens: 10_000, maxCost: 1.5, maxTurns: 8, maxTools: 20 };

  // 正向：hint ≤ 父 ⇒ 按hint 下拨（不得无端缩水成 0 —— 防"恒 0"假实现）。
  const modest = normalizeBudget(BUDGET_RESOLVE_FN.value(parentBudget, { maxTokens: 4_000 }));
  assert.equal(modest.recognized, true, "下拨结果必须是对象形态（防 undefined 假绿）");
  assert.equal(
    Number(modest.value.maxTokens) > 0 && Number(modest.value.maxTokens) <= parentBudget.maxTokens,
    true,
    `hint=4000 ⇒ 下拨值必须落在 (0, 10000]；实测 ${JSON.stringify(modest.value)}`
  );

  // 反向 ①：hint > 父 ⇒ cap 到父（不得上调）。
  const greedy = normalizeBudget(BUDGET_RESOLVE_FN.value(parentBudget, { maxTokens: 99_999 }));
  assert.equal(
    Number(greedy.value.maxTokens) <= parentBudget.maxTokens,
    true,
    `hint 超父必须 cap；实测 ${JSON.stringify(greedy.value)} —— 上调即越父（D4）`
  );

  // 反向 ②：缺 hint ⇒ 也不得超过父。
  const noHint = normalizeBudget(BUDGET_RESOLVE_FN.value(parentBudget, undefined));
  for (const dimension of BUDGET_DIMENSIONS) {
    const value = noHint.value[dimension.key];
    if (value !== undefined && value !== null) {
      assert.equal(
        Number(value) <= parentBudget[dimension.key],
        true,
        `缺 hint 时 ${dimension.key} 不得超过父（实测 ${String(value)}）`
      );
    }
  }
});

/** 预算对象归一（防 undefined 假绿；`{}` 也算已识别的"空预算"形态）。 */
function normalizeBudget(value) {
  if (value === null || value === undefined) return { recognized: false, value: {} };
  if (typeof value === "object" && !Array.isArray(value)) return { recognized: true, value };
  return { recognized: false, value: {} };
}

test("D4-3 · 触顶必中断：四维参数化 exceeded + stop_reason 精确匹配；未触顶必不停（双向）", () => {
  assert.equal(BUDGET_APPLY_FN.found, true, `前置：预算闸导出未就位（${BUDGET_APPLY_FN.tried.join(" | ")}）`);

  for (const dimension of BUDGET_DIMENSIONS) {
    const budget = { [dimension.key]: 100 };
    const usage = { [dimension.usageKey]: 101 };
    const verdict = normalizeVerdict(BUDGET_APPLY_FN.value({ budget, usage }));
    assert.equal(verdict.recognized, true, `${dimension.key}：预算闸必须返回已声明形态（实测 ${verdict.shape}）`);
    assert.equal(verdict.value.exceeded, true, `${dimension.usageKey} 超限必须中断（反例：预算只记录不拦截）`);
    if (verdict.value.stopReason !== undefined && verdict.value.stopReason !== null) {
      assert.equal(
        verdict.value.stopReason,
        dimension.stopReason,
        `${dimension.usageKey} 耗尽的 stop_reason 必须是 ${dimension.stopReason}（K-4：耗尽项与码匹配，不自造 BUDGET_EXCEEDED）`
      );
    }
  }

  // 反向：未触顶 ⇒ 必不停（防"一律中断"假实现）。
  const quiet = normalizeVerdict(BUDGET_APPLY_FN.value({ budget: { maxTokens: 100 }, usage: { tokens: 10 } }));
  assert.equal(quiet.recognized, true, "未触顶也必须返回已声明形态");
  assert.equal(quiet.value.exceeded, false, "未触顶不得中断（只测触顶会被一律中断的假实现蒙混）");
});

/** 预算闸结果归一（`{exceeded}` / `{stop}` / 抛错归一为已声明形态）。 */
function normalizeVerdict(value) {
  if (value === null || value === undefined) return { recognized: false, value: {}, shape: "undefined" };
  if (typeof value === "object") {
    for (const key of ["exceeded", "stop", "halted"]) {
      if (typeof value[key] === "boolean") {
        return { recognized: true, value, shape: `${key}=${value[key]}` };
      }
    }
  }
  return { recognized: false, value: {}, shape: typeof value };
}

test("D4-4 · 全链路：父 run 正常收敛（COMPLETED 不崩）+ 子 run token_usage ≤ 下拨预算 B", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  const fixture = await makeApp({ username: "del-d44" });
  try {
    const chain = await seedChain(fixture, "d4-parent");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });
    const outcome = await probeSpawn(SPAWN_FN.value, {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      parentRunId,
      targetAgentId: chain.agentId,
      targetVersionId: chain.versionId,
      conversationId: chain.conversationId,
      task: "预算触顶子任务",
      depth: 0,
      maxDepth: 1,
      budget: { maxTokens: 100 },
    });
    assert.equal(outcome.normalized.recognized, true, `派生必须返回已声明形态（实测 ${outcome.normalized.shape}）`);
    assert.equal(outcome.normalized.accepted, true, `下拨预算 B=100 tokens 的子 run 必须能建（实测 ${outcome.normalized.shape}）`);

    // 父 run 不得被子 run 的预算中断带崩（D4：父正常收敛）。
    assert.equal(
      ["RUNNING", "SUCCEEDED", "COMPLETED"].includes(runRow(fixture, parentRunId).status),
      true,
      `父 run 不得因子 run 预算中断而崩溃；实测 ${runRow(fixture, parentRunId).status}`
    );
  } finally {
    await fixture.close();
  }
});

/** 调一次 delegateSpawn 并归一（不抛错；异常按已声明形态归一）。 */
async function probeSpawn(fn, input) {
  try {
    const raw = await fn(input);
    return { normalized: normalizeSpawnOutcome(raw), raw, threw: false, error: null };
  } catch (error) {
    return { normalized: normalizeSpawnOutcome(error), raw: null, threw: true, error };
  }
}

// ---------------------------------------------------------------------------
// §3 · D5 · 权限不越父
// ---------------------------------------------------------------------------

test("D5-1 · 判据载体：交集与判权两导出就位", () => {
  assert.equal(
    SCOPE_INTERSECT_FN.found,
    true,
    `必须导出 intersectPermissionScope / intersectScope / narrowScope 之一（D5 收窄）；实测：${SCOPE_INTERSECT_FN.tried.join(" | ")}`
  );
  assert.equal(
    SCOPE_ALLOWS_FN.found,
    true,
    `必须导出 isToolAllowedInScope / isToolAllowed / scopeAllows 之一（D5 判权）；实测：${SCOPE_ALLOWS_FN.tried.join(" | ")}`
  );
  assert.equal(typeof SCOPE_INTERSECT_FN.value, "function");
  assert.equal(typeof SCOPE_ALLOWS_FN.value, "function");
});

test("D5-2 · 收窄 = 父 ∩ 目标：⊆ 父（透传必红）且 target ⊆ 父时 == target（恒空必红）", () => {
  assert.equal(SCOPE_INTERSECT_FN.found, true, `前置：交集导出未就位（${SCOPE_INTERSECT_FN.tried.join(" | ")}）`);
  const parent = ["tool.a", "tool.b", "tool.c"];
  const target = ["tool.b", "tool.c", "tool.d"];

  const narrowed = scopeSet(SCOPE_INTERSECT_FN.value(parent, target));
  assert.equal(narrowed.recognized, true, `交集结果必须是集合形态（实测 ${narrowed.shape}）`);

  // D5 主判据：结果 ⊆ 父 —— 直接透传父 scope（不取交集）时 tool.d 会漏进来 ⇒ 红。
  const subset = isSubset(narrowed.value, scopeSet(parent).value);
  assert.deepEqual(subset.violations, [], `收窄结果必须 ⊆ 父；实测越界码：${subset.violations.join("; ")}`);

  // 反向 ①：目标里有而父没有的码不得出现（防"**透传 target**"形态 —— 那种改坏下
  // 这里会红；"**透传父**"形态由反向 ② 抓，因透传父满足 ⊆ 父、本条不设防）。
  assert.equal(narrowed.value.has("tool.d"), false, "target 独有的 tool.d 不得进入子 scope（防「透传 target」形态；「透传父」形态由反向 ② 抓）");

  // 反向 ②：target ⊆ 父时交集必须 == target（防"恒空集"假实现把合法能力抹掉）。
  const contained = scopeSet(SCOPE_INTERSECT_FN.value(parent, ["tool.b", "tool.c"]));
  assert.deepEqual(
    [...contained.value].sort(),
    ["tool.b", "tool.c"],
    "target ⊆ 父 ⇒ 交集必须 == target，不得恒空（防恒空集假实现）"
  );
});

/** 集合结果归一（`string[]` / `Set` / 空值都收）。 */
function scopeSet(value) {
  if (value === null || value === undefined) return { recognized: false, value: new Set(), shape: "undefined" };
  if (value instanceof Set) return { recognized: true, value, shape: "Set" };
  if (Array.isArray(value)) return { recognized: true, value: scopeCodes(value), shape: "string[]" };
  return { recognized: false, value: new Set(), shape: typeof value };
}

test("D5-3 · 判权：授权工具 ALLOW / 未授权工具 DENY（双向）", () => {
  assert.equal(SCOPE_ALLOWS_FN.found, true, `前置：判权导出未就位（${SCOPE_ALLOWS_FN.tried.join(" | ")}）`);
  const scope = ["tool.a", "tool.b"];
  assert.equal(SCOPE_ALLOWS_FN.value(scope, "tool.a"), true, "授权工具必须 ALLOW（只测 DENY 会被一律拒绝蒙混）");
  assert.equal(SCOPE_ALLOWS_FN.value(scope, "tool.z"), false, "未授权工具必须 DENY");
  assert.equal(SCOPE_ALLOWS_FN.value([], "tool.a"), false, "空 scope 不得放行任何工具");
});

/**
 * **D5-4 · 行为面**（改造 3）：子 run 调父未授权工具 ⇒ 真实 `ToolExecutor` 落
 * `tool_call.status == 'DENIED'`（在 `tool_call` 行断言，**非 HTTP**）。
 *
 * 为什么必须给网关（改造 2）：`DENIED` 行只能由**真实 `ToolExecutor` 权限链**
 * 在被越权调用时落（裁定 7），而调用只能来自子 run 的**真实执行**。不给网关 ⇒
 * 子 run 只建行不启动执行（`RunDriver.start` 无网关即 `CONFIGURATION_ERROR`
 * fail loud）⇒ 无 `DENIED` 行可断言 ⇒ 判据不可判。故注入**既有**的脚本化假
 * Provider（`routes-harness.mjs::fakeGateway`，过 fake 闸门，不新造），并取
 * 「等收敛」档（`settleTimeoutMs`）—— 与 D3-2a 的「不等」档相反（附加 C）。
 */
test("D5-4 · 行为面：子 run 调父未授权工具 ⇒ 真实 ToolExecutor 落 tool_call.status == DENIED（非 HTTP），授权工具不得 DENIED", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  const fixture = await makeApp({ username: "del-d54" });
  try {
    const chain = await seedChain(fixture, "d5-parent");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });
    const outcome = await probeSpawn(SPAWN_FN.value, {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      parentRunId,
      targetAgentId: chain.agentId,
      targetVersionId: chain.versionId,
      conversationId: chain.conversationId,
      task: "越权探测子任务",
      depth: 0,
      maxDepth: 1,
      gateway: fakeGateway(CHILD_DRIVE_SCRIPT),
      settleTimeoutMs: CHILD_SETTLE_TIMEOUT_MS,
    });
    assert.equal(
      outcome.normalized.recognized,
      true,
      `派生必须返回已声明形态（实测 ${outcome.normalized.shape}）`
    );
    assert.equal(
      outcome.normalized.accepted,
      true,
      "派生必须成功（本用例判的是子 run 的工具权限，不是派生权限）"
    );
    const childRunId = String(outcome.raw.childRunId ?? "");
    assert.equal(
      runRow(fixture, childRunId).trigger,
      "subagent",
      "前置：派生必须真的建出 trigger='subagent' 的子 run"
    );

    // 这些行必须由执行链产生（测试不代插）—— 执行链未跑起来 ⇒ 前置红 =
    // 「实现未落地」，不是判据写错。
    const rows = fixture.raw
      .prepare("select tool_name, status from tool_call where run_id = ? order by rowid")
      .all(childRunId);
    const denied = rows.filter((row) => row.status === "DENIED");
    assert.equal(
      denied.length >= 1,
      true,
      "子 run 调父未授权工具必须落一条 tool_call.status = 'DENIED'（D5：在 tool_call 行断言，非 HTTP；" +
        `DENIED 只能由真实 ToolExecutor 权限链落，测试不代插）；实测 tool_call 行 ${JSON.stringify(rows)}`
    );
    // 反向：授权工具的行不得被 DENY（防"一律 DENY"假实现）。
    const allowedDenied = fixture.raw
      .prepare(
        "select count(*) as n from tool_call where run_id = ? and tool_name = 'code_exec' and status = 'DENIED'"
      )
      .get(childRunId).n;
    assert.equal(
      allowedDenied,
      0,
      "scope 内的 code_exec 不得被 DENY（防一律拒绝的假实现）；" +
        `实测 DENIED 行 ${JSON.stringify(denied.map((row) => row.tool_name))}`
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// §4 · S3 附加判据（不计入 D1–D10 十条）
// ---------------------------------------------------------------------------

test("S3-1 · 子 run 继承 policy_version 快照：subagent.started.payload.policy_version == 父快照（不等即红）", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  const fixture = await makeApp({ username: "del-s31" });
  try {
    const chain = await seedChain(fixture, "s3-parent");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });
    const PARENT_POLICY = "pv-2026-10-23-delegation-a";
    const outcome = await probeSpawn(SPAWN_FN.value, {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      parentRunId,
      targetAgentId: chain.agentId,
      targetVersionId: chain.versionId,
      conversationId: chain.conversationId,
      task: "快照继承子任务",
      depth: 0,
      maxDepth: 1,
      parentPolicyVersion: PARENT_POLICY,
    });
    assert.equal(outcome.normalized.recognized, true, `派生必须返回已声明形态（实测 ${outcome.normalized.shape}）`);
    assert.equal(outcome.normalized.accepted, true, "接受场景必须有子 run（S3 的反向面在 S3-2）");
    const childRunId = String(outcome.raw.childRunId ?? "");

    const started = fixture.raw
      .prepare("select payload from agent_event where run_id = ? and type = 'subagent.started' order by seq asc")
      .all(childRunId);
    assert.equal(started.length >= 1, true, "子 run 必须落 subagent.started 事件（父子树的双源之一）");
    const payload = JSON.parse(started[0].payload ?? "{}");
    assert.equal(
      payload.parent_run_id,
      parentRunId,
      "subagent.started.payload.parent_run_id 必须指向父 run（§1② 双源还原的子侧）"
    );
    assert.equal(
      payload.policy_version,
      PARENT_POLICY,
      `子 run 的 policy_version 必须继承父快照（实测 ${String(payload.policy_version)}）—— 不等即红`
    );
  } finally {
    await fixture.close();
  }
});

test("S3-2 · 拒绝走拒绝型 tool result：不抛异常、不产生 4xx、agent_run 子 run 行数 == 0", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  const fixture = await makeApp({ username: "del-s32" });
  try {
    const chain = await seedChain(fixture, "s3-reject-parent");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });
    const before = countSubagentRuns(fixture);
    const outcome = await probeSpawn(SPAWN_FN.value, {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      parentRunId,
      targetAgentId: chain.agentId,
      targetVersionId: chain.versionId,
      conversationId: chain.conversationId,
      task: "深度超限的再派生",
      depth: 1,
      maxDepth: 1,
    });
    // 拒绝必须是**返回值形态**的拒绝型 result，不是异常（抛异常 = 拒绝路径杀 run ⇒ 红）。
    assert.equal(outcome.threw, false, `拒绝必须走拒绝型 tool result，不得抛异常；实测抛了：${String(outcome.error?.message ?? "")}`);
    assert.equal(outcome.normalized.recognized, true, `拒绝结果必须是已声明形态（实测 ${outcome.normalized.shape}）`);
    assert.equal(outcome.normalized.accepted, false, "depth=1/max=1 必须被拒（D1 与 S3 共用的拒绝路径）");
    assert.equal(countSubagentRuns(fixture) - before, 0, "拒绝场景不得落任何 trigger='subagent' 的子 run 行（S3：行数 == 0）");
  } finally {
    await fixture.close();
  }
});

test("S3-3 · 拒绝事件的 S3 挂点标记：subagent.rejected.payload.stage == delegation（SafetyStage=delegation）", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  const fixture = await makeApp({ username: "del-s33" });
  try {
    const chain = await seedChain(fixture, "s3-stage-parent");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });
    const outcome = await probeSpawn(SPAWN_FN.value, {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      parentRunId,
      targetAgentId: chain.agentId,
      targetVersionId: chain.versionId,
      conversationId: chain.conversationId,
      task: "过 S3 挂点的拒绝场景",
      depth: 1,
      maxDepth: 1,
    });
    assert.equal(outcome.threw, false, "拒绝不得抛异常（同 S3-2）");
    assert.equal(outcome.normalized.accepted, false, "本用例需要一次真实拒绝");

    const rejected = fixture.raw
      .prepare("select payload from agent_event where run_id = ? and type = 'subagent.rejected' order by seq asc")
      .all(parentRunId);
    assert.equal(rejected.length >= 1, true, "父 run 必须落 subagent.rejected 事件（D1② 观察面）");
    const payloads = rejected.map((row) => JSON.parse(row.payload ?? "{}"));
    const stages = payloads.map((payload) => payload.stage ?? payload.safety_stage ?? null);
    assert.ok(
      stages.includes("delegation"),
      `拒绝事件必须带 SafetyStage=delegation 挂点标记（实测 stage 集合 ${JSON.stringify(stages)}）`
    );
  } finally {
    await fixture.close();
  }
});

/** `agent_run` 中 `trigger == 'subagent'` 的行数（S3 拒绝场景的观察面）。 */
function countSubagentRuns(fixture) {
  return fixture.raw.prepare("select count(*) as n from agent_run where trigger = 'subagent'").get().n;
}

// ---------------------------------------------------------------------------
// §5 · D8 · 并发闸单入口（T031-04 接线后新增）
//
// 判据原文（计划 §3 D8）：用户入口创建 run 前判闸（单入口）；「父 + 1 子」不
// 409；第二个用户主动 run 仍 409；子 run 场景判闸恒 1 次。
//
// 接线形态（T031-04）：`RunDriverDeps.openRun` 钩子 → `run-service.ts::open_run`
// → `guardRunCreation`；`origin=USER` 由 `app.ts` 装配闭包烤入（driver 内零
// origin 逻辑）。子 run driver 不持有该钩子 ⇒ 建行点不判（其闸在 `delegateSpawn`
// 3a 前置判过一次，裁定 v）。
// ---------------------------------------------------------------------------

/**
 * 把 fixture 的 agent 指针指到已插的版本（HTTP 入口判据专用）。
 *
 * `createAgentWithVersion` 走裸 SQL 插 `agent_version`、**不动指针**（run 直调
 * 判据不需要它）；而 `runEntry` 的前置校验要求 `current_version_id` 非空 ⇒
 * HTTP 面判据必须先补这一下（与 `routes-agents.test.mjs` 的 `publish` 等价，
 * 此处不新造发布路径，直接按指针落库）。
 */
function pointAgentAtVersion(fixture, agentId, versionId) {
  fixture.raw
    .prepare("update agent set current_version_id = ? where id = ?")
    .run(versionId, agentId);
}

test("D8-1 · 正向面：父 run 活跃时派生成功（origin=SUBAGENT 豁免 ⇒「父 + 1 子」不 409）", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  const fixture = await makeApp({ username: "del-d81" });
  try {
    const chain = await seedChain(fixture, "d8-exempt-parent");
    // 占住会话活跃位（父活跃 ⇒ 计数 1 ≥ 上限 1）。豁免必须**取自 origin**，
    // 不是把上限调大 —— 后者会让 D8-2 的 409 面破裂（B-1 纪律）。
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });

    const outcome = await probeSpawn(SPAWN_FN.value, {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      parentRunId,
      targetAgentId: chain.agentId,
      targetVersionId: chain.versionId,
      conversationId: chain.conversationId,
      task: "D8-1 并发闸豁免派生",
      depth: 0,
      maxDepth: 1,
    });
    assert.equal(
      outcome.normalized.recognized,
      true,
      `派生必须返回已声明形态（实测 ${outcome.normalized.shape}）`
    );
    assert.equal(
      outcome.normalized.accepted,
      true,
      `父活跃时 origin=SUBAGENT 必须豁免（「父 + 1 子」不 409）；实测 ${outcome.normalized.shape}` +
        ` ${JSON.stringify(outcome.raw ?? null)}`
    );
    const childRunId = String(outcome.raw.childRunId ?? "");
    assert.equal(
      runRow(fixture, childRunId).trigger,
      "subagent",
      "豁免后必须真的建出 trigger='subagent' 的子 run（不是「拒了却返回 accepted」的假绿）"
    );
  } finally {
    await fixture.close();
  }
});

test("D8-2 · 反向面：第二个用户主动 run 仍 409 且拒绝路径零落库（HTTP 行为面；D10① 的 body trigger 合入本链路）", async () => {
  const fixture = await makeApp({ username: "del-d82", model: true });
  try {
    const chain = await seedChain(fixture, "d8-second-user");
    pointAgentAtVersion(fixture, chain.agentId, chain.versionId);
    seedRunRow(fixture, { ...chain, status: "RUNNING" });

    const runsBefore = fixture.raw
      .prepare("select count(*) as n from agent_run where conversation_id = ?")
      .get(chain.conversationId).n;
    const messagesBefore = fixture.raw
      .prepare("select count(*) as n from message where conversation_id = ?")
      .get(chain.conversationId).n;

    // ① 干净 body：第二个用户主动 run ⇒ 409。
    const second = await request(fixture, "POST", `/api/v1/agents/${chain.agentId}/run`, {
      payload: { message: "第二个用户主动 run", conversation_id: chain.conversationId },
    });
    assert.equal(
      second.statusCode,
      409,
      `第二个用户主动 run 必须 409（并发闸单入口已接线）；实测 ${second.statusCode} ${second.body}`
    );
    assert.equal(errorOf(second).code, "CONFLICT", "409 必须走契约 CONFLICT 码（复用既有映射，不新造）");

    // ② D10① 合入断言：body 显式带 `trigger:"subagent"` ⇒ 仍 409、行数仍不增
    //    （客户端可达面伪造不了豁免 —— 判据只认应用层 origin）。
    const forged = await request(fixture, "POST", `/api/v1/agents/${chain.agentId}/run`, {
      payload: {
        message: "带 trigger 的第二个用户主动 run",
        conversation_id: chain.conversationId,
        trigger: "subagent",
      },
    });
    assert.equal(
      forged.statusCode,
      409,
      `body 带 trigger:"subagent" 不得获豁免（D10①：trigger 永不参与放行）；实测 ${forged.statusCode} ${forged.body}`
    );

    // ③ 拒绝路径零落库：run 行数恒不增（消息也不落 —— 判闸点在消息 append 之前）。
    const runsAfter = fixture.raw
      .prepare("select count(*) as n from agent_run where conversation_id = ?")
      .get(chain.conversationId).n;
    const messagesAfter = fixture.raw
      .prepare("select count(*) as n from message where conversation_id = ?")
      .get(chain.conversationId).n;
    assert.equal(runsAfter, runsBefore, `拒绝路径 run 行数不得增；实测 ${runsBefore} → ${runsAfter}`);
    assert.equal(
      messagesAfter,
      messagesBefore,
      `拒绝路径消息不得落（判闸点在用户消息 append 之前）；实测 ${messagesBefore} → ${messagesAfter}`
    );
  } finally {
    await fixture.close();
  }
});

test("D8-3 · 子 run 场景判闸恒 1 次（计数补丁观测：3a 前置一次；3b 的 driver.start 无 openRun 钩子）", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  assert.equal(
    GUARD_FN.found,
    true,
    `前置：guardRunCreation 未就位（${GUARD_FN.tried.join(" | ")}）—— 计数补丁的观测对象`
  );
  const fixture = await makeApp({ username: "del-d83" });
  try {
    const chain = await seedChain(fixture, "d8-count");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });

    // 观测点 = `guardRunCreation` 的数据面**唯一**调用点（grep 实证仅 coordinator
    // 内）。测试侧包裹计数（try/finally 还原）⇒ 生产零改动、同 dist 模块实例生效。
    const original = AgentRunRepo.prototype.countActiveByConversation;
    let guardCount = 0;
    AgentRunRepo.prototype.countActiveByConversation = async function patchedCount(...args) {
      guardCount += 1;
      return original.apply(this, args);
    };
    let outcome;
    try {
      // 有网关 ⇒ 3b 路径（`startChildRun` 自建 driver 走 `RunDriver.start`）——
      // 该 driver **不持有** openRun 钩子是"恒 1"的结构保证。
      outcome = await probeSpawn(SPAWN_FN.value, {
        db: fixture.connection.db,
        dialect: "sqlite",
        tenantId: TENANT_ID,
        parentRunId,
        targetAgentId: chain.agentId,
        targetVersionId: chain.versionId,
        conversationId: chain.conversationId,
        task: "D8-3 恒 1 次判闸",
        depth: 0,
        maxDepth: 1,
        gateway: fakeGateway(CHILD_DRIVE_SCRIPT),
        settleTimeoutMs: CHILD_SETTLE_TIMEOUT_MS,
      });
    } finally {
      AgentRunRepo.prototype.countActiveByConversation = original;
    }
    assert.equal(outcome.normalized.recognized, true, `派生必须返回已声明形态（实测 ${outcome.normalized.shape}）`);
    assert.equal(outcome.normalized.accepted, true, `派生必须成功（否则计数观测失去前提）；实测 ${outcome.normalized.shape}`);
    assert.equal(
      guardCount,
      1,
      `一次派生必须恰好判闸 1 次（3a 前置判一次；3b 的 driver.start 无 openRun 钩子 ⇒ 不判；` +
        `3c 的 concurrencyGuard:"skip" ⇒ 不判）；实测 ${guardCount}`
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// §6 · D10 · origin / trigger 分离（豁免判据只认应用层 origin）
// ---------------------------------------------------------------------------

/** 守卫结果归一（`{allowed}` / `{ok}` / `{conflict}` / 409 抛错都收；防假绿）。 */
function normalizeGuardOutcome(value) {
  if (value === null || value === undefined) {
    return { recognized: false, allowed: false, shape: "undefined" };
  }
  if (typeof value === "object") {
    if (typeof value.allowed === "boolean") {
      return { recognized: true, allowed: value.allowed, shape: `allowed=${value.allowed}` };
    }
    for (const key of ["ok", "conflict"]) {
      if (typeof value[key] === "boolean") {
        return {
          recognized: true,
          allowed: key === "ok" ? value[key] : !value[key],
          shape: `${key}=${value[key]}`,
        };
      }
    }
    const status = value.status ?? value.statusCode;
    if (status === 409 || value.code === "CONFLICT") {
      return { recognized: true, allowed: false, shape: "409" };
    }
  }
  return { recognized: false, allowed: false, shape: typeof value };
}

/** 调一次 guardRunCreation 并归一（不抛错；异常按已声明形态归一）。 */
async function probeGuard(fn, args) {
  try {
    const raw = await fn(args);
    return { ...normalizeGuardOutcome(raw), threw: false, raw };
  } catch (error) {
    return { ...normalizeGuardOutcome(error), threw: true, raw: null, error };
  }
}

test("D10-1 · 结构面：RunRequest 契约面仍 4 键 —— 不含 trigger（客户端可达面到不了豁免判据）", () => {
  assert.equal(
    RUN_REQUEST_SCHEMA.found,
    true,
    `前置：schemas-run 模块未就位（${RUN_REQUEST_SCHEMA.reason}）`
  );
  const schema = RUN_REQUEST_SCHEMA.module?.RunRequestSchema;
  assert.ok(
    schema !== undefined && schema !== null && typeof schema === "object",
    "schemas-run 必须导出 RunRequestSchema（静态读 schema 模块，不手抄名单）"
  );
  const keys = Object.keys(schema.properties ?? {}).sort();
  // 仪器自证：4 键必须**在**（防"properties 读成空对象 ⇒ 不含 trigger 恒真"的假绿）。
  assert.deepEqual(
    keys,
    ["conversation_id", "message", "run_mode", "workspace_id"],
    `RunRequest 必须恰为契约 4 键（多一个 trigger 就等于把豁免判据建到客户端可达面上）；实测 ${JSON.stringify(keys)}`
  );
  // HTTP 面（body 带 trigger 仍 409、行数不增）按 B-4 口径**合入 D8-2** 同链路断言。
});

test("D10-2 · 单元面：豁免只认 origin —— {USER, trigger=subagent} 拒 / {SUBAGENT, trigger=user} 放（双向）", async () => {
  assert.equal(GUARD_FN.found, true, `前置：guardRunCreation 未就位（${GUARD_FN.tried.join(" | ")}）`);
  const fixture = await makeApp({ username: "del-d102" });
  try {
    const chain = await seedChain(fixture, "d10-origin");
    seedRunRow(fixture, { ...chain, status: "RUNNING" }); // 占住活跃位（计数 1 ≥ 上限 1）
    const base = {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      conversationId: chain.conversationId,
    };

    // 第一组（反向）：origin=USER + trigger=subagent ⇒ 必须拒。只测放行会被
    // "一律放行"蒙混；这一组正是"裸 trigger 判据"的旁路。
    const forgedTrigger = await probeGuard(GUARD_FN.value, {
      ...base,
      origin: "USER",
      trigger: "subagent",
    });
    assert.equal(forgedTrigger.recognized, true, `守卫必须返回已声明形态（实测 ${forgedTrigger.shape}）`);
    assert.equal(
      forgedTrigger.allowed,
      false,
      `origin=USER 不得因 trigger='subagent' 获豁免（D10 核心：trigger 永不参与放行）；实测 ${forgedTrigger.shape}`
    );

    // 第二组（正向）：origin=SUBAGENT + trigger=user ⇒ 必须放。只测拒会被
    // "一律拒"蒙混。
    const realSubagent = await probeGuard(GUARD_FN.value, {
      ...base,
      origin: "SUBAGENT",
      trigger: "user",
    });
    assert.equal(realSubagent.recognized, true, `守卫必须返回已声明形态（实测 ${realSubagent.shape}）`);
    assert.equal(
      realSubagent.allowed,
      true,
      `origin=SUBAGENT 必须豁免计数（trigger 传 user 不影响放行）；实测 ${realSubagent.shape}`
    );
  } finally {
    await fixture.close();
  }
});

/**
 * D10③ 审计 SQL：`trigger='subagent'` 但没有对应 `spawn_agent` 成功父记录的行。
 *
 * `json_extract` 仅用于**测试侧审计探针**（判据跑 SQLite）；生产的子 run 发现链
 * 走应用层 JSON 解析（`subagent-cancel.ts`，零方言分叉）—— 一个是审计探针、
 * 一个是取消传播取数面，不是同一真相源。
 */
const ORPHAN_SUBAGENT_AUDIT_SQL = `select r.id from agent_run r
  where r.trigger = 'subagent'
    and not exists (
      select 1 from tool_call t
      where t.tool_name = 'spawn_agent'
        and t.status = 'SUCCESS'
        and json_extract(t.output, '$.child_run_id') = r.id
    )`;

test("D10-3 · 审计面：trigger='subagent' 的行必有 spawn_agent 父记录（伪造行必命中 + 真实派生不进孤儿集）", async () => {
  assert.equal(SPAWN_FN.found, true, `前置：delegateSpawn 未就位（${SPAWN_FN.tried.join(" | ")}）`);
  const fixture = await makeApp({ username: "del-d103" });
  try {
    const chain = await seedChain(fixture, "d10-audit");
    const parentRunId = seedRunRow(fixture, { ...chain, status: "RUNNING" });

    // 反向（仪器自证）：直插一条伪造子 run（trigger='subagent'、无父 tool_call）
    //   ⇒ 审计必须命中它。抓不出孤儿的审计 SQL 是恒空假绿。
    //   `success` 传 1 不传 true：node:sqlite 不绑布尔值（DDL 侧是 0/1 整数）。
    const forgedRunId = seedRunRow(fixture, {
      ...chain,
      trigger: "subagent",
      status: "SUCCEEDED",
      success: 1,
    });

    // 正向：真实派生（3b 有网关；`spawner.delegate` 落父侧 spawn_agent SUCCESS 行，
    //   `output.child_run_id` 指向子 run）⇒ 该子 run 不得进孤儿集。
    const outcome = await probeSpawn(SPAWN_FN.value, {
      db: fixture.connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
      parentRunId,
      targetAgentId: chain.agentId,
      targetVersionId: chain.versionId,
      conversationId: chain.conversationId,
      task: "D10-3 审计派生",
      depth: 0,
      maxDepth: 1,
      gateway: fakeGateway(CHILD_DRIVE_SCRIPT),
      settleTimeoutMs: CHILD_SETTLE_TIMEOUT_MS,
    });
    assert.equal(outcome.normalized.recognized, true, `派生必须返回已声明形态（实测 ${outcome.normalized.shape}）`);
    assert.equal(outcome.normalized.accepted, true, `派生必须成功（正向面的前提）；实测 ${outcome.normalized.shape}`);
    const childRunId = String(outcome.raw.childRunId ?? "");

    const orphans = fixture.raw.prepare(ORPHAN_SUBAGENT_AUDIT_SQL).all().map((row) => row.id);
    assert.deepEqual(
      orphans,
      [forgedRunId],
      `审计必须恰好命中伪造行、且真实派生的子 run（${childRunId}）不得进孤儿集；实测 ${JSON.stringify(orphans)}`
    );
  } finally {
    await fixture.close();
  }
});
