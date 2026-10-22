/**
 * T3-14 · 运行时 e2e 的**装配与端口分配**（卡面 `packages/e2e/lib/*`）。
 *
 * 三条硬约束（卡面「e2e 走 mock 而非真端口 ⇒ 必红」）
 * ---------------------------------------------
 *   ① **真端口**：`app.listen({host:"127.0.0.1", port})`，端口由 `freePort()` 向内核要
 *      —— 不写死 8000/3000（撞车会把红变成"环境问题"）。{@link assertRealPort} 用
 *      **真实 TCP 连接**复验：连得上才算真端口。
 *   ② **真 HTTP**：所有请求走 `fetch`，**不用** `app.inject()` —— inject 是"不过 socket
 *      的假请求"，把它当 e2e 就是 mock。
 *   ③ **`node:sqlite`**：文件库（不是 `:memory:`）—— 于是"关掉进程后数据还在"这件事
 *      是真的，回放/续读读的是**同一份持久化事件**。
 *
 * 为什么在**本进程**里 `buildApp` 而不是 spawn `dist/main.js`
 * ------------------------------------------------------
 *   e2e 需要注入**脚本化假 Provider**（`fake-provider.mjs`），而脚本是内存对象，
 *   过不了进程边界。`ts-backend` 冒烟那条腿用 spawn 是因为它验的是"main.js 起得来"；
 *   本文件验的是"运行时主链跑得通"，两者分工不同，都有真端口。
 *
 * 假 Provider 的闸门不绕过：`createScriptedGateway` 内部调
 * `assertFakeProviderAllowed(process.env)`（见 `fake-provider.mjs`）。
 */

import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { buildApp } from "../../../apps/api/dist/app.js";
import { loadConfig } from "../../config/dist/index.js";
import { createSqliteDb } from "../../db/dist/connection.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** 仓根（lib → e2e → packages → 根）。 */
export const REPO_ROOT = path.resolve(HERE, "..", "..", "..");

/** DDL（61 表；与生产同份）。 */
const DDL_PATH = path.join(REPO_ROOT, "output", "ddl.sqlite.sql");

/** 主租户（与 `apps/api` 的 `DEFAULT_TENANT_ID` 同值：register 的前置是租户存在且启用）。 */
export const TENANT_ID = "00000000-0000-4000-8000-000000000001";

/** 测试主密钥（≥32 字节；**不是**任何真实部署的密钥）。 */
export const TEST_SECRET = "wbtime-e2e-runtime-secret-key-0123456789";

/** 测试口令（满足口令策略）。 */
export const TEST_PASSWORD = "E2e-Runtime-Pass!23";

/** 工作区（`conversation.workspace_id` NOT NULL + FK）。 */
export const WORKSPACE_ID = "5e5e5e5e-0000-4000-8000-0000000000e5";

/**
 * 向内核要一个空闲端口（立即释放；极小竞态由"监听失败即红"兜住）。
 *
 * @returns {Promise<number>} 端口号。
 */
export function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

/**
 * **真端口**证据：真实 TCP 连接能建立。
 *
 * @param {number} port 端口。
 * @returns {Promise<boolean>} `true` = 有进程在该端口监听。
 */
export function canConnect(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host: "127.0.0.1", port });
    const settle = (value) => {
      socket.destroy();
      resolve(value);
    };
    socket.on("connect", () => settle(true));
    socket.on("error", () => settle(false));
  });
}

/**
 * 断言"我们打的是真端口"（不是 inject / 不是假对象）。
 *
 * @param {object} server {@link startRuntimeServer} 的返回值。
 * @throws {Error} 端口连不上 / URL 不是 `127.0.0.1:<port>`。
 */
export async function assertRealPort(server) {
  if (!(await canConnect(server.port))) {
    throw new Error(`端口 ${server.port} 无人监听 —— 这不是真端口（e2e 红线）`);
  }
  if (!server.baseUrl.startsWith(`http://127.0.0.1:${server.port}`)) {
    throw new Error(`baseUrl 与端口不符：${server.baseUrl} vs ${server.port}`);
  }
}

/**
 * 启动运行时 e2e 服务（真端口 + 文件库 + 脚本化模型栈）。
 *
 * @param {object} options
 * @param {string} options.label 用例标签（数据库文件名前缀）。
 * @param {Array<Array<object>>} options.turns 每轮的模型脚本。
 * @param {(gateway: object) => object} [options.turnsFactory] （可选）自建网关。
 * @returns {Promise<object>} `{ baseUrl, port, app, raw, stop, token, headers, userId }`。
 */
export async function startRuntimeServer(options) {
  const label = options.label ?? "runtime";

  // ---- 方言闸（R3-20）----------------------------------------------------
  // CI 只跑 SQLite。PG 档**只提供入口**：缺环境 ⇒ fail loud（非 0 退出，**不 skip**），
  // 且本版**没有** PG 运行时 e2e 的实现 —— 任何"用 SQLite 结果宣称 PG 通过"都是假证。
  if ((process.env.WBTIME_RUNTIME_DIALECT ?? "sqlite") === "pg") {
    if (process.env.WBTIME_PG_URL === undefined || process.env.WBTIME_PG_URL === "") {
      throw new Error(
        "PG 档运行时 e2e 缺环境：WBTIME_PG_URL 未设置（fail loud，禁止 skip —— R3-20 ③）"
      );
    }
    throw new Error(
      "PG 档运行时 e2e **本版未实现**（V0.3.0 CI 只跑 SQLite，R3-20 ①）。" +
        "入口与 fail-loud 已就位；PG 补测需在窗口期人工执行，且**不得**以 SQLite 结果冒充（R3-20 ④）"
    );
  }
  const tempDir = mkdtempSync(path.join(tmpdir(), `wbtime-e2e-${label}-`));
  const dbPath = path.join(tempDir, `${label}.db`);
  // run 工作区根：用例要能检查工具副作用（写文件是否真的发生）。
  process.env.WBTIME_RUN_WORKSPACE_ROOT = path.join(tempDir, "runs");

  const connection = createSqliteDb(dbPath);
  connection.raw.exec(readFileSync(DDL_PATH, "utf8"));
  connection.raw
    .prepare("insert into tenant (id, name, slug, is_active) values (?, ?, ?, 1)")
    .run(TENANT_ID, "e2e-runtime-tenant", "e2e-runtime");

  // 动态 import：`fake-provider.mjs` 在模块加载期就要读 env（闸门），放这里更可控。
  const { createScriptedGateway } = await import("./fake-provider.mjs");
  const gateway = options.turnsFactory === undefined
    ? createScriptedGateway(options.turns ?? [])
    : options.turnsFactory();

  const config = loadConfig({
    WBTIME_AI_MODE: "local",
    WBTIME_AI_SECRET_KEY: TEST_SECRET,
    WBTIME_AI_ALLOW_FAKE_PROVIDER: "1",
  });

  const app = buildApp({
    config,
    enableLogging: false,
    database: connection.db,
    dialect: "sqlite",
    tenantId: TENANT_ID,
    modelGateway: gateway,
  });

  const port = await freePort();
  await app.listen({ host: "127.0.0.1", port });
  const baseUrl = `http://127.0.0.1:${port}`;

  // 注册（真 HTTP；走到 bcrypt/argon2 与令牌签发）
  const username = `e2e-${label}-${Date.now()}`;
  const registered = await call({
    baseUrl,
    method: "POST",
    path: "/api/v1/auth/register",
    body: { username, email: `${username}@e2e.test`, password: TEST_PASSWORD },
  });
  if (registered.status !== 201) {
    await app.close();
    connection.close();
    throw new Error(`register 失败：${registered.status} ${registered.text.slice(0, 400)}`);
  }
  const token = registered.json.data.access_token;
  const userId = JSON.parse(
    Buffer.from(token.split(".")[1], "base64url").toString("utf8")
  ).sub;
  const headers = { authorization: `Bearer ${token}` };

  // 工作区：没有创建 op（契约无该 op）⇒ 直接落库（e2e 拥有这份库）
  connection.raw
    .prepare(
      "insert into workspace (id, tenant_id, organization_id, owner_id, name, workspace_type) " +
        "values (?, ?, NULL, ?, 'e2e 工作区', 'PERSONAL')"
    )
    .run(WORKSPACE_ID, TENANT_ID, userId);

  let stopped = false;
  return {
    baseUrl,
    port,
    app,
    raw: connection.raw,
    gateway,
    token,
    userId,
    headers,
    tempDir,
    /** run 工作区根（工具副作用的观测点）。 */
    workspaceRoot: process.env.WBTIME_RUN_WORKSPACE_ROOT,
    async stop() {
      if (stopped) return;
      stopped = true;
      await app.close();
      connection.close();
      rmSync(tempDir, { recursive: true, force: true });
    },
  };
}

/**
 * 发一个 JSON 请求（**真 HTTP**）。
 *
 * @param {object} options `{baseUrl, method, path, body?, token?, headers?, raw?}`.
 * @returns {Promise<{status:number, json:any, text:string, headers:Headers}>}
 */
export async function call(options) {
  const method = options.method ?? "GET";
  const headers = { ...(options.headers ?? {}) };
  if (options.token !== undefined) headers.authorization = `Bearer ${options.token}`;
  let body;
  if (options.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(`${options.baseUrl}${options.path}`, {
    method,
    headers,
    ...(body === undefined ? {} : { body }),
    signal: AbortSignal.timeout(options.timeoutMs ?? 30_000),
  });
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = null;
  }
  return { status: response.status, json, text, headers: response.headers };
}

/**
 * 建 Agent + 发布版本（真 HTTP；`runtime_config` 决定技能 / 审批 / 限额）。
 *
 * @param {object} server {@link startRuntimeServer} 产物。
 * @param {object} [input] `{systemPrompt, modelConfig, runtimeConfig, name}`.
 * @returns {Promise<{agentId: string, versionId: string}>}
 */
export async function createAgent(server, input = {}) {
  const created = await call({
    baseUrl: server.baseUrl,
    method: "POST",
    path: "/api/v1/agents",
    token: server.token,
    body: { name: input.name ?? `e2e-agent-${Date.now()}` },
  });
  if (created.status !== 201) throw new Error(`create agent 失败：${created.status} ${created.text}`);
  const agentId = created.json.data.id;

  const published = await call({
    baseUrl: server.baseUrl,
    method: "POST",
    path: `/api/v1/agents/${agentId}/publish`,
    token: server.token,
    body: {
      system_prompt: input.systemPrompt ?? "你是运行时 e2e 助手。",
      model_config: input.modelConfig ?? { model: "fake-1", provider: "fake" },
      runtime_config: input.runtimeConfig ?? {},
      ...(input.tools === undefined ? {} : { tools: input.tools }),
    },
  });
  if (published.status !== 201) {
    throw new Error(`publish 失败：${published.status} ${published.text}`);
  }
  return { agentId, versionId: published.json.data.id };
}

/**
 * 发起一次 run（真 HTTP）。
 *
 * @returns {Promise<object>} `RunResponse`（21 键）。
 */
export async function startRun(server, agentId, body = {}) {
  const response = await call({
    baseUrl: server.baseUrl,
    method: "POST",
    path: `/api/v1/agents/${agentId}/run`,
    token: server.token,
    body: { message: body.message ?? "跑一下", workspace_id: body.workspace_id ?? WORKSPACE_ID, ...body },
  });
  if (response.status !== 200) throw new Error(`run 失败：${response.status} ${response.text}`);
  return response.json.data;
}

/** 取 run 当前行（真 HTTP）。 */
export async function getRun(server, runId) {
  const response = await call({
    baseUrl: server.baseUrl,
    method: "GET",
    path: `/api/v1/runs/${runId}`,
    token: server.token,
  });
  if (response.status !== 200) throw new Error(`GET run 失败：${response.status} ${response.text}`);
  return response.json.data;
}

/** 终态集合。 */
export const TERMINAL_STATUSES = ["SUCCEEDED", "FAILED", "CANCELLED"];

/**
 * 等 run 到终态（真 HTTP 轮询）。
 *
 * @returns {Promise<object>} 终态的 run 行。
 */
export async function waitTerminal(server, runId, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const run = await getRun(server, runId);
    if (TERMINAL_STATUSES.includes(run.status)) return run;
    if (Date.now() > deadline) {
      throw new Error(`run ${runId} 在 ${timeoutMs}ms 内未到终态：${JSON.stringify(run)}`);
    }
    await sleep(50);
  }
}

/**
 * 把 SSE 响应体切成帧块（`id: / event: / data:` 三行 + 空行）。
 *
 * @param {string} text 响应体。
 * @returns {Array<string>} 帧块。
 */
export function splitFrames(text) {
  return String(text)
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter((chunk) => chunk !== "");
}

/** 一帧的 `event:` 名。 */
export function channelOf(frame) {
  return /^event: (.+)$/m.exec(frame)?.[1];
}

/** 一帧的 `id:`（游标）。 */
export function idOf(frame) {
  return Number(/^id: (\d+)$/m.exec(frame)?.[1]);
}

/** 一帧的 `data:` 解析结果。 */
export function dataOf(frame) {
  const raw = /^data: (.+)$/m.exec(frame)?.[1];
  return raw === undefined ? null : JSON.parse(raw);
}

/**
 * 收一次事件流（**不重连**）：读完整响应体再切帧。
 *
 * 服务端是**有限订阅**（终态或 40 轮后收尾），所以"读完整响应体"是正常形态；
 * 需要续传时调用方带 `lastEventId` 再收一次（见 {@link collectRunFrames}）。
 *
 * @param {object} server {@link startRuntimeServer} 产物。
 * @param {string} runId run 标识。
 * @param {object} [options] `{lastEventId, afterSeq, timeoutMs}`.
 * @returns {Promise<Array<string>>} 帧块（**不含**心跳注释帧）。
 */
export async function streamOnce(server, runId, options = {}) {
  const headers = { ...server.headers };
  if (options.lastEventId !== undefined) headers["last-event-id"] = String(options.lastEventId);
  const query = options.afterSeq === undefined ? "" : `?after_seq=${options.afterSeq}`;
  const response = await fetch(`${server.baseUrl}/api/v1/runs/${runId}/events${query}`, {
    headers,
    signal: AbortSignal.timeout(options.timeoutMs ?? 30_000),
  });
  if (response.status !== 200) {
    throw new Error(`events 失败：${response.status} ${await response.text()}`);
  }
  const body = await response.text();
  return splitFrames(body).filter((frame) => frame.startsWith("id:"));
}

/**
 * 收完整一次 run 的帧（**带 Last-Event-ID 续传**，直到 run 终态）。
 *
 * 这是 DoD#4「`agent_event` 回放 + `Last-Event-ID` gap-aware 续读」的机器形态：
 * 第一轮从头收，之后每轮带上一轮的游标续读 —— 断流就重连，语义上不丢帧。
 *
 * @param {object} server 服务。
 * @param {string} runId run 标识。
 * @param {object} [options] `{maxRounds, timeoutMs, startCursor}`.
 *   `startCursor` 用于"已经收过一段"的场景（续传）：从该游标之后开始收，
 *   否则会从 0 重放，把已收到的帧重复计一遍（调用方的并集就会重复）。
 * @returns {Promise<{frames: string[], channels: Set<string>, rounds: number}>}
 */
export async function collectRunFrames(server, runId, options = {}) {
  const maxRounds = options.maxRounds ?? 40;
  const frames = [];
  let cursor = options.startCursor;
  let rounds = 0;

  for (let round = 0; round < maxRounds; round += 1) {
    rounds += 1;
    const batch = await streamOnce(server, runId, {
      ...(cursor === undefined ? {} : { lastEventId: cursor }),
      ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
    });
    for (const frame of batch) frames.push(frame);
    if (batch.length > 0) cursor = idOf(batch[batch.length - 1]);

    const run = await getRun(server, runId);
    if (TERMINAL_STATUSES.includes(run.status) && batch.length === 0) break;
    if (TERMINAL_STATUSES.includes(run.status)) {
      // 终态后可能还有一批尾帧没读到：再收一轮，空批即收尾。
      const tail = await streamOnce(server, runId, {
        ...(cursor === undefined ? {} : { lastEventId: cursor }),
        ...(options.timeoutMs === undefined ? {} : { timeoutMs: options.timeoutMs }),
      });
      for (const frame of tail) frames.push(frame);
      if (tail.length > 0) cursor = idOf(tail[tail.length - 1]);
      break;
    }
  }

  return { frames, channels: new Set(frames.map(channelOf)), rounds };
}

/**
 * 等某个条件成立（HTTP 轮询用）。
 *
 * @param {() => Promise<boolean>} predicate 条件。
 * @param {string} label 失败信息里的名字。
 * @param {number} [timeoutMs] 上限。
 */
export async function waitFor(predicate, label, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (await predicate()) return;
    if (Date.now() > deadline) throw new Error(`${label} 在 ${timeoutMs}ms 内未成立`);
    await sleep(50);
  }
}

/** 最小 sleep。 */
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 启动一个 stdio MCP server fixture 子进程所需的注册参数（command + args）。
 *
 * @returns {{command: string, args: string[]}} 可原样 POST 给 `/mcp/servers`。
 */
export function mcpEchoServerSpec() {
  return {
    command: process.execPath,
    args: [path.join(HERE, "fixtures", "mcp-echo-server.mjs")],
  };
}

/**
 * `spawn` 一个一次性的子进程并收集输出（诊断用；e2e 不依赖它做判据）。
 *
 * @param {string} file 可执行文件。
 * @param {string[]} args 参数。
 * @returns {import("node:child_process").ChildProcess}
 */
export function spawnChild(file, args) {
  return spawn(file, args, { cwd: REPO_ROOT, stdio: "ignore" });
}
