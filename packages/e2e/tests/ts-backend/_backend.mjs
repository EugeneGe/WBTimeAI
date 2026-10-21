/**
 * T2-10 · TS 后端冒烟的**真进程启动器**（4 个 case 共用）。
 *
 * 与 `tests/e2e/_harness.mjs`（py legacy）的三点不同：
 *
 * 1. **打的是 TS 后端**：spawn `node <repo>/apps/api/dist/main.js` —— 编译产物、
 *    真进程、真端口（**不是** `app.inject()`，冒烟必须过真实 TCP 栈）。
 * 2. **零 py 依赖**：不 import legacy launcher，不设 `E2E_RUN_NONCE` —— 因此 TS 后端
 *    的响应**不会**带 `X-E2E-Nonce`（那是 py runner 注入给 py 后端回显的），这恰好
 *    成了「打的是谁」的反向证据（见 {@link assertTsEvidence}）。
 * 3. **SQLite 文件库**：先在本 runner 进程灌 `output/ddl.sqlite.sql`（61 表），
 *    再把文件路径交给子进程（`WBTIME_SQLITE_PATH`）—— 每个case独立库，互不污染。
 *
 * 端口：`node:net` 探随机空闲端口（**不用** 8000/3000，避免与常见服务撞车）。
 * 就绪判定：轮询 `GET /healthz` 直到 200（带超时）；起不来抛 PreconditionError，
 * 绝不挂死也绝不静默继续。
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

import { DEFAULT_TENANT_ID } from "../../../../apps/api/dist/app.js";

/** 本目录（`packages/e2e/tests/ts-backend/`）。 */
const HERE = path.dirname(fileURLToPath(import.meta.url));

/** 仓根（ts-backend → tests → e2e → packages → 根）。 */
const REPO_ROOT = path.resolve(HERE, "..", "..", "..", "..");

/** TS 后端进程入口（编译产物 —— 冒烟打的就是它）。 */
export const MAIN_JS = path.join(REPO_ROOT, "apps", "api", "dist", "main.js");

/** DDL（61 表）—— 冒烟库的唯一定义源，与生产同份。 */
const DDL_PATH = path.join(REPO_ROOT, "output", "ddl.sqlite.sql");

/** 临时产物目录（DDL 预灌后的 SQLite 文件库落这里，不动仓内任何路径）。
 *
 * V0.2.0 起改为**可移植**：此前硬编码 `D:/Temp/WBTimeAI/...`（Windows 专有盘符），
 * 在 Linux runner 上会被解释成相对路径 `D:/Temp/...` ⇒ `DatabaseSync` 打不开 ⇒
 * 冒烟在"建库"这一步就红，而那是**环境**的红，不是被测行为的红。
 * 现在默认落 `os.tmpdir()` 下的固定子目录（三平台都有），可用
 * `WBTIME_E2E_TEMP_DIR` 覆盖（想把产物收进指定目录时用）。
 */
const TEMP_DIR = process.env.WBTIME_E2E_TEMP_DIR !== undefined
  && process.env.WBTIME_E2E_TEMP_DIR !== ""
  ? path.resolve(process.env.WBTIME_E2E_TEMP_DIR)
  : path.join(os.tmpdir(), "wbtime-ts-backend-smoke");

// 目录必须存在：`new DatabaseSync(file)` 不会替你建父目录。
mkdirSync(TEMP_DIR, { recursive: true });

/** 测试主密钥（≥ 32 UTF-8 字节；实际 47 字节）。 */
export const TS_SECRET_KEY = "wbtime-ts-backend-smoke-secret-key-0123456789";

/** 冒烟口令（满足口令策略）。 */
export const TS_PASSWORD = "E2e-Passw0rd!23";

/** healthz 就绪等待上限（ms）。 */
const READY_TIMEOUT_MS = 30_000;

/** 轮询间隔（ms）。 */
const POLL_INTERVAL_MS = 250;

/**
 * 探随机空闲端口（内核分配后立即释放；存在极小竞态，但撞上已用端口的概率可忽略，
 * 且后续 `/healthz` 等不到会立刻红，不会被掩盖）。
 *
 * @returns 空闲端口号。
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
 * 探测端口是否处于监听。
 *
 * @param port 端口号。
 * @returns `true` = 有监听者接受连接。
 */
export function isListening(port) {
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
 * 启动 TS 后端（真进程真端口）。
 *
 * @param label case 名（用作 SQLite 文件名前缀，便于日志归档）。
 * @returns `{ baseUrl, port, pid, stop }`；`stop()` 终止进程并等其退出（幂等）。
 * @throws {Error} 进程提前退出或 `/healthz` 超时（PreconditionError 语义，绝不挂死）。
 */
export async function startTsBackend(label) {
  const port = await freePort();
  const dbPath = path.join(TEMP_DIR, `ts-backend-${label}-${Date.now()}-${randomUUID()}.db`);

  // 先灌 DDL：main.js 的 `createDatabase` 只建连不建表（schema 归 DDL 管理）。
  // 再种默认租户：register/login 的前置是「租户存在且启用」（`assertTenantActive`），
  // 而 main.js 的默认租户 id 是 `DEFAULT_TENANT_ID`（`WBTIME_AI_TENANT_ID` 未设时）——
  // 纯 DDL 库没有这行，register 会折 401。
  const bootstrap = new DatabaseSync(dbPath);
  try {
    bootstrap.exec(readFileSync(DDL_PATH, "utf8"));
    bootstrap
      .prepare("INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, 1)")
      .run(DEFAULT_TENANT_ID, "ts-smoke-tenant", "ts-smoke-tenant");
  } finally {
    bootstrap.close();
  }

  const child = spawn(process.execPath, [MAIN_JS], {
    cwd: REPO_ROOT,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      WBTIME_AI_MODE: "local",
      WBTIME_AI_SECRET_KEY: TS_SECRET_KEY,
      WBTIME_SQLITE_PATH: dbPath,
      WBTIME_API_PORT: String(port),
      WBTIME_LOG_LEVEL: "error",
    },
  });

  let stderrTail = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => {
    stderrTail = (stderrTail + chunk).slice(-4000);
  });

  const exited = new Promise((resolve) => {
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });

  const baseUrl = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + READY_TIMEOUT_MS;

  // 就绪轮询：进程先死 ⇒ PreconditionError（带 stderr 尾巴）；超时 ⇒ PreconditionError。
  for (;;) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(
        `PreconditionError：TS 后端进程在就绪前退出（code=${child.exitCode} signal=${child.signalCode}）`
        + ` :: stderr 尾部: ${stderrTail.slice(-600)}`,
      );
    }
    try {
      const response = await fetch(`${baseUrl}/healthz`, { signal: AbortSignal.timeout(2000) });
      if (response.ok) break;
    } catch {
      // 尚未就绪 —— 继续轮询，直到 deadline。
    }
    if (Date.now() > deadline) {
      child.kill();
      throw new Error(
        `PreconditionError：/healthz 在 ${READY_TIMEOUT_MS}ms 内未就绪（port=${port}）`
        + ` :: stderr 尾部: ${stderrTail.slice(-600)}`,
      );
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }

  let stopped = false;
  return {
    baseUrl,
    port,
    /** spawn 出的 `node dist/main.js` 进程 pid —— 「打的是 TS 后端」的进程级证据。 */
    pid: child.pid,
    /** 启动参数自证（pid 归属：这个 pid 跑的正是 MAIN_JS）。 */
    command: `node ${MAIN_JS}`,
    async stop() {
      if (stopped) return;
      stopped = true;
      child.kill();
      const outcome = await Promise.race([
        exited,
        new Promise((resolve) => setTimeout(() => resolve(null), 10_000)),
      ]);
      if (outcome === null) {
        // 优雅退出超时（Windows 上 kill() 直接终止，通常到不了这里）；硬保证端口释放。
        child.kill("SIGKILL");
        await exited;
      }
    },
  };
}

/**
 * 「打的是 TS 后端」的可区分证据（每个 case 至少调用一次）：
 *
 * 1. `x-request-id` 响应头存在 —— TS 中间件（`request-context.ts`）的契约行为，且
 *    值必须等于响应体 `request_id`（「体 == 头」）；
 * 2. `x-e2e-nonce` **不存在** —— 那是 py runner 注入、py 后端回显的头；TS 后端
 *    不经过 py runner，出现它反而说明打错了对象；
 * 3. spawn 的 pid 存活（`process.kill(pid, 0)`）—— 响应来自我们起的
 *    `node dist/main.js` 进程，不是环境里恰好在跑的别的服务。
 *
 * @param response 已收到的 fetch Response。
 * @param backend {@link startTsBackend} 的返回值。
 */
export function assertTsEvidence(response, backend) {
  const requestId = response.headers.get("x-request-id");
  assert.equal(
    typeof requestId,
    "string",
    `TS 后端证据缺失：x-request-id 响应头不存在（status=${response.status}）`,
  );
  assert.ok(requestId.length > 0, "x-request-id 不得为空串");
  assert.equal(
    response.headers.get("x-e2e-nonce"),
    null,
    "出现了 X-E2E-Nonce：这不是 TS 后端的行为（那是 py runner 的标记）",
  );
  assert.equal(
    typeof backend.pid,
    "number",
    "TS 后端证据缺失：spawn 的 pid 不是数字",
  );
  assert.doesNotThrow(
    () => process.kill(backend.pid, 0),
    `spawn 的 dist/main.js 进程（pid=${backend.pid}）应存活：响应不是来自我们起的进程`,
  );
  return requestId;
}

/**
 * 注册 + 登录（真实 HTTP 链），返回 access token。
 *
 * @param baseUrl 后端基地址。
 * @param username 用户名。
 * @returns `{ token, registerStatus, loginStatus }`。
 */
export async function registerAndLogin(baseUrl, username) {
  const registerResponse = await fetch(`${baseUrl}/api/v1/auth/register`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      username,
      email: `${username}@ts-smoke.test`,
      password: TS_PASSWORD,
      display_name: username,
    }),
    signal: AbortSignal.timeout(10_000),
  });
  const registerBody = await registerResponse.json();
  assert.equal(registerResponse.status, 201, `register 期望 201，实得 ${registerResponse.status}`);

  const loginResponse = await fetch(`${baseUrl}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password: TS_PASSWORD }),
    signal: AbortSignal.timeout(10_000),
  });
  const loginBody = await loginResponse.json();
  assert.equal(loginResponse.status, 200, `login 期望 200，实得 ${loginResponse.status}`);

  const token = loginBody?.data?.access_token;
  assert.equal(typeof token, "string", "login 必须回 access_token");
  return { token, registerStatus: registerResponse.status, loginStatus: loginResponse.status };
}
