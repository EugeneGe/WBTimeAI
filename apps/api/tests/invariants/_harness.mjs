/**
 * T3-14 · 不变量测试的共用夹具（**不是** test 文件 —— 文件名不带 `.test.mjs`）。
 *
 * 为什么需要一个独立夹具（不复用 `routes-harness.mjs`）
 * -----------------------------------------------
 *   不变量测试要**控制模型侧的脚本**（"先请求工具、再给答复"、慢速多轮、输出命中
 *   安全规则……），而 `routes-harness.makeApp` 给的是固定脚本。本夹具因此自带
 *   **脚本化 Provider**（R3-19 明确允许：`provider.kind='fake'` 按脚本化 chunk 序列输出），
 *   其余（真库 `node:sqlite` + 整份 DDL + 真 `buildApp` + 真 HTTP 路由）与生产一致。
 *
 * 假 Provider 的闸门**不绕过**
 * ----------------------
 *   `assertFakeProviderAllowed(process.env)` 在 {@link createScriptedGateway} 里调用：
 *   没有 `NODE_ENV=test` 或 `WBTIME_AI_ALLOW_FAKE_PROVIDER=1` ⇒ 直接抛（fail loud），
 *   与 `buildModelStack` 的 `fake` 分支同一道闸。测试进程由 `run-api-tests.mjs` 起，
 *   `NODE_ENV` 未被强制设成 test ⇒ 本文件在模块加载时自查一次并给出明确提示。
 *
 * 用法
 * ---
 * ```js
 * const f = await makeRunApp({ turns: [toolTurn("c1", "shell", {...}), finalTurn()] });
 * const run = await f.startRun({ runtimeConfig: {} });
 * const terminal = await f.waitTerminal(run.id);
 * ```
 */

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "@wbtime/config";
import { createSqliteDb } from "@wbtime/db/connection";

import { buildApp } from "../../dist/app.js";
import { ModelGateway } from "../../dist/modules/model/gateway.js";
import { assertFakeProviderAllowed } from "../../dist/modules/model/providers/factory.js";

// 假 Provider 的放行开关：本文件在 `createScriptedGateway` 里通过
// `assertFakeProviderAllowed(process.env)` 过同一道闸门。用**文档化的开关**
// （`WBTIME_AI_ALLOW_FAKE_PROVIDER=1`，R3-19 ② 的原文载体）而不是伪造 `NODE_ENV`：
// 生产配置里没有这个变量 ⇒ `buildModelStack` 的 fake 分支仍然启动失败。
process.env.WBTIME_AI_ALLOW_FAKE_PROVIDER = "1";

/** 仓库根（apps/api/tests/invariants → … → 根）。 */
export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");

/** 测试主密钥（≥32 字节；**不是**任何真实部署的密钥）。 */
export const TEST_SECRET = "wbtime-test-secret-key-0123456789abcdef";

/** 主租户。 */
export const TENANT_ID = "11111111-1111-4111-8111-111111111111";

/** 工作区（`conversation.workspace_id` NOT NULL + FK）。 */
export const WORKSPACE_ID = "3d3d3d3d-0000-4000-8000-0000000000d3";

/** `run` 的终态集合。 */
export const TERMINAL_STATUSES = ["SUCCEEDED", "FAILED", "CANCELLED"];

const DDL = readFileSync(join(ROOT, "output", "ddl.sqlite.sql"), "utf8");

/** 只含"注册即可用"所需的最小配置。 */
export function testConfig(extra = {}) {
  return loadConfig({ WBTIME_AI_MODE: "local", WBTIME_AI_SECRET_KEY: TEST_SECRET, ...extra });
}

// ---------------------------------------------------------------------------
// 脚本化 Provider（R3-19 ①：按脚本化 chunk 序列输出，usage 为固定常量）
// ---------------------------------------------------------------------------

/** 三键 usage（**不含** cache 键：未提供 ≠ 0，R3-19 ④）。 */
export const FIXED_USAGE = Object.freeze({ prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 });

/**
 * 一轮"模型请求工具"的脚本。
 *
 * @param {string} callId 工具调用 id（同一轮内唯一）。
 * @param {string} name 工具名（`shell` / `filesystem` / `code_exec` / `mcp:x/y`）。
 * @param {unknown} input 工具入参。
 * @param {string} [text] 附带的文本增量。
 * @returns {Array<object>} ProviderChunk 序列。
 */
export function toolTurn(callId, name, input, text = "我调用工具。") {
  return [
    { type: "text_delta", text },
    { type: "tool_call", id: callId, name, input },
    { type: "usage", usage: { ...FIXED_USAGE } },
    { type: "finish", reason: "tool_calls" },
  ];
}

/**
 * 一轮"模型给出最终答复"的脚本。
 *
 * @param {string} [text] 答复正文。
 * @returns {Array<object>} ProviderChunk 序列。
 */
export function finalTurn(text = "已完成。") {
  return [
    { type: "text_delta", text },
    { type: "usage", usage: { ...FIXED_USAGE } },
    { type: "finish", reason: "model_finish" },
  ];
}

/** 一轮"只吐文本、不发 finish 前先等一会儿"的脚本（慢速 run 用）。 */
export function slowToolTurn(callId, name, input, delayMs = 60) {
  return [
    { type: "text_delta", text: "慢慢来。", delayMs },
    { type: "tool_call", id: callId, name, input },
    { type: "usage", usage: { ...FIXED_USAGE } },
    { type: "finish", reason: "tool_calls" },
  ];
}

/**
 * 脚本化网关：**每次 `stream()` 消耗一个脚本**（最后一个脚本重复）。
 *
 * 与产品 `createFakeProvider` 的差别只有一个：后者每次重放同一脚本，
 * 因此"工具回路"永远停在第一轮（模型反复请求同一个工具直到预算耗尽）。
 * 运行时 e2e / 不变量要的是"第一轮请求工具、第二轮给答复"这种**跨轮**序列。
 *
 * @param {Array<Array<object>>} turns 每轮的 chunk 序列。
 * @returns {ModelGateway} 可注入 `buildApp({modelGateway})` 的网关。
 * @throws {Error} 假 Provider 未被放行（`assertFakeProviderAllowed`）。
 */
export function createScriptedGateway(turns) {
  // 闸门：与 `buildModelStack` 的 fake 分支同一道判断（不绕过）。
  assertFakeProviderAllowed(process.env);
  const scripts = turns.length === 0 ? [finalTurn()] : turns;
  let index = 0;
  const provider = {
    kind: "fake",
    providerName: "fake",
    async *stream() {
      const script = scripts[Math.min(index, scripts.length - 1)];
      index += 1;
      for (const chunk of script) {
        if (chunk.delayMs !== undefined) {
          await new Promise((resolve) => setTimeout(resolve, chunk.delayMs));
        }
        yield chunk;
      }
    },
  };
  return new ModelGateway({ provider });
}

// ---------------------------------------------------------------------------
// 应用夹具
// ---------------------------------------------------------------------------

/**
 * 建一个**带脚本化模型栈**的应用（真库 + 真 HTTP 路由 + 真 run 驱动）。
 *
 * @param {{turns?: Array<Array<object>>, env?: Record<string,string>}} [options]
 * @returns 夹具对象（`app` / `raw` / `headers` / `startRun` / `waitTerminal` / …）。
 */
export async function makeRunApp(options = {}) {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  connection.raw
    .prepare("insert into tenant (id, name, slug, is_active) values (?, ?, ?, 1)")
    .run(TENANT_ID, "租户 T3-14", "t314");

  const gateway = createScriptedGateway(options.turns ?? [finalTurn()]);
  const app = buildApp({
    config: testConfig(options.env ?? {}),
    enableLogging: false,
    database: connection.db,
    dialect: "sqlite",
    tenantId: TENANT_ID,
    modelGateway: gateway,
  });
  await app.ready();

  const raw = connection.raw;
  const registered = await app.inject({
    method: "POST",
    url: "/api/v1/auth/register",
    payload: { username: "inv-user", email: "inv@t314.example", password: "inv-password-2026" },
  });
  assert.equal(registered.statusCode, 201, registered.body);
  const token = JSON.parse(registered.body).data.access_token;
  const userId = JSON.parse(
    Buffer.from(token.split(".")[1], "base64url").toString("utf8"),
  ).sub;
  const headers = { authorization: `Bearer ${token}`, "content-type": "application/json" };

  raw
    .prepare(
      "insert into workspace (id, tenant_id, organization_id, owner_id, name, workspace_type) " +
        "values (?, ?, NULL, ?, '不变量工作区', 'PERSONAL')",
    )
    .run(WORKSPACE_ID, TENANT_ID, userId);

  /** 真 HTTP：创建 agent + 发布版本（`runtime_config` 决定 harness / 审批 / 限额）。 */
  const createAgent = async (overrides = {}) => {
    const created = await app.inject({
      method: "POST",
      url: "/api/v1/agents",
      headers,
      payload: { name: overrides.name ?? "不变量 Agent" },
    });
    assert.equal(created.statusCode, 201, created.body);
    const agentId = JSON.parse(created.body).data.id;
    const published = await app.inject({
      method: "POST",
      url: `/api/v1/agents/${agentId}/publish`,
      headers,
      payload: {
        system_prompt: overrides.systemPrompt ?? "你是运行时测试助手。",
        model_config: overrides.modelConfig ?? { model: "fake-1" },
        runtime_config: overrides.runtimeConfig ?? {},
      },
    });
    assert.equal(published.statusCode, 201, published.body);
    return { agentId, versionId: JSON.parse(published.body).data.id };
  };

  /** 真 HTTP：发起一次 run（返回 `RunResponse` 21 键）。 */
  const startRun = async (input = {}) => {
    const agent = input.agent ?? (await createAgent(input));
    const response = await app.inject({
      method: "POST",
      url: `/api/v1/agents/${agent.agentId}/run`,
      headers,
      payload: {
        message: input.message ?? "跑一下",
        workspace_id: input.workspaceId === undefined ? WORKSPACE_ID : input.workspaceId,
        ...(input.conversationId === undefined ? {} : { conversation_id: input.conversationId }),
      },
    });
    return { response, agent };
  };

  return {
    app,
    raw,
    connection,
    gateway,
    headers,
    userId,
    tenantId: TENANT_ID,
    createAgent,
    startRun,
    /** 取 run 行（不存在 ⇒ `undefined`）。 */
    runRow: (runId) => raw.prepare("select * from agent_run where id = ?").get(runId),
    /** 取某 run 的事件（按 seq 升序）。 */
    eventsOf: (runId) =>
      raw
        .prepare("select seq, type, payload from agent_event where run_id = ? order by seq asc")
        .all(runId),
    /** 取某 run 的事件类型清单。 */
    channelsOf: (runId) =>
      raw
        .prepare("select type from agent_event where run_id = ? order by seq asc")
        .all(runId)
        .map((row) => row.type),
    /** 取某 run 的 tool_call 行。 */
    toolCallsOf: (runId) =>
      raw.prepare("select * from tool_call where run_id = ? order by created_at asc").all(runId),
    /** 计数（跨表通用）。 */
    count: (sql, ...params) => raw.prepare(sql).get(...params).n,
    /** 安全审计行（按 stage 过滤）。 */
    safetyRows: (stage) =>
      raw
        .prepare(
          "select * from audit_log where action = 'safety.decision' and resource_id = ? order by created_at asc",
        )
        .all(stage),
    /** 等 run 到终态（超时抛错并带上当前行）。 */
    waitTerminal: async (runId, timeoutMs = 20_000) => {
      const deadline = Date.now() + timeoutMs;
      for (;;) {
        const row = raw.prepare("select * from agent_run where id = ?").get(runId);
        if (row !== undefined && TERMINAL_STATUSES.includes(row.status)) return row;
        if (Date.now() > deadline) {
          throw new Error(`run ${runId} 在 ${timeoutMs}ms 内未到终态：${JSON.stringify(row)}`);
        }
        await sleep(20);
      }
    },
    /** 等某个条件成立（条件为异步函数；超时抛错）。 */
    waitFor: async (predicate, label = "条件", timeoutMs = 20_000) => {
      const deadline = Date.now() + timeoutMs;
      for (;;) {
        if (await predicate()) return;
        if (Date.now() > deadline) throw new Error(`${label} 在 ${timeoutMs}ms 内未成立`);
        await sleep(20);
      }
    },
    close: async () => {
      await app.close();
      connection.close();
    },
  };
}

/** 最小 sleep。 */
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 建一个临时目录（run 工作区的根；调用方负责 `cleanup()`）。 */
export function makeTempDir(prefix = "wbtime-t314-") {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  return { dir, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

/** 该 run 的工作目录（与 `RunDriver.#workspaceRootOf` 同口径）。 */
export function runWorkspaceDir(baseDir, runId) {
  return join(baseDir, runId);
}
