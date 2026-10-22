// apps/api · 进程入口。
//
// 职责仅三件：读配置 → `buildApp()` → `listen()`。业务装配一律在 `app.ts` 里，
// 这样测试可以拿同一个 `buildApp()` 起实例而完全不经过本文件（不绑端口、不读 argv）。
//
// 端口来源：`@wbtime/config` 的 `WBTIME_API_PORT`（缺省值由 config 的 `DEFAULTS` 给）。
// **本文件不写任何端口字面量** —— 兜底值也取自 `DEFAULTS.port`，否则「配置里改了端口
// 却有一处硬编码」这种偏差会在部署时才暴露。
//
// 绑定地址：`127.0.0.1`。本版没有任何鉴权以外的网络前提需要监听公网；显式绑回环
// 可以保证开发机上的实例不会意外对局域网敞开（需要对外时改这里，而不是靠防火墙）。

import { pathToFileURL } from "node:url";

import { ConfigError, DEFAULTS, loadConfig, requireSecretKey } from "@wbtime/config";
import type { Config } from "@wbtime/config";
import { createPgDb, createSqliteDb } from "@wbtime/db/connection";
import type { DrizzleDatabase, SqlDialect } from "@wbtime/db";
import { createLogger } from "@wbtime/logging";

import { buildApp, type ModelStackOptions } from "./app.js";
import { assertKnownProviderKind } from "./modules/model/providers/factory.js";
import { createShutdownHandler, type ShutdownLogger } from "./shutdown.js";

/** 监听地址（回环）。 */
export const HOST = "127.0.0.1";

/** 退出码：配置非法（启动前的可预期失败）。 */
export const EXIT_CONFIG_INVALID = 2;

/** 退出码：监听失败（端口占用 / 权限等）。 */
export const EXIT_LISTEN_FAILED = 3;

/** 端口合法区间。 */
const MIN_PORT = 1;
const MAX_PORT = 65535;

/** 一个已建好的数据库句柄（含方言与关闭钩子）。 */
export interface DatabaseHandle {
  readonly database: DrizzleDatabase;
  readonly dialect: SqlDialect;
  readonly close: () => Promise<void>;
}

/**
 * 按档位建数据库句柄。
 *
 * `local` 档用 `node:sqlite`（零原生依赖，纪律 §4.10.1 禁 `better-sqlite3`）；
 * `server` 档用 `pg`（Pool 惰性，构造不建连）。
 *
 * @param config 已加载配置。
 * @returns 句柄 + 方言 + `close()`。
 */
export function createDatabase(config: Config): DatabaseHandle {
  if (config.mode === "local") {
    const sqlite = createSqliteDb(config.sqlitePath ?? ":memory:");
    return {
      database: sqlite.db,
      dialect: "sqlite",
      close: async (): Promise<void> => {
        sqlite.close();
      },
    };
  }
  const pg = createPgDb(config.databaseUrl);
  return {
    database: pg.db,
    dialect: "pg",
    close: async (): Promise<void> => {
      await pg.close();
    },
  };
}

/**
 * 取实际监听端口：配置里的合法端口优先，否则回落 `@wbtime/config` 的默认端口。
 *
 * @param config 已加载的配置。
 * @returns 1..65535 的整数端口。
 */
export function resolvePort(config: Config): number {
  const port = config.port;
  if (Number.isInteger(port) && port >= MIN_PORT && port <= MAX_PORT) return port;
  return DEFAULTS.port;
}

/**
 * 从环境读模型栈装配选项（T3-14）。
 *
 * 为什么必须在生产路径上装配：T3-02 的 `buildModelStack` 建好之后一直没有调用点
 * （`main` 从不传 `model`），于是"有没有模型能力"取决于测试夹具 —— 而 run 执行
 * （T3-14）需要一个真网关。未配置 ⇒ **不装配**（返回 `undefined`），`runEntry`
 * 随即 fail loud（`CONFIGURATION_ERROR`）：未配置 ≠ 降级。
 *
 * 只读一个变量：`WBTIME_MODEL_PROVIDER`（`openai` / `anthropic` / `google` /
 * `openai-compatible` / `fake`）。key / baseURL 仍由 `buildModelStack` 按既有约定
 * 从 `*_API_KEY` / `OPENAI_COMPATIBLE_BASE_URL` 取 —— 本函数不复制那套映射。
 *
 * @param env 环境变量源（缺省 `process.env`）。
 * @returns 装配选项；未设置 provider ⇒ `undefined`。
 * @throws {ConfigError} provider 不在白名单（`assertKnownProviderKind`，QA F-2）。
 */
export function modelStackFromEnv(
  env: NodeJS.ProcessEnv = process.env
): ModelStackOptions | undefined {
  const raw = env.WBTIME_MODEL_PROVIDER;
  if (raw === undefined || raw.trim() === "") return undefined;
  const kind = assertKnownProviderKind(raw.trim());
  return {
    kind,
    env,
    ...(env.OPENAI_COMPATIBLE_BASE_URL === undefined
      ? {}
      : { baseURL: env.OPENAI_COMPATIBLE_BASE_URL }),
  };
}

/**
 * 启动服务（可被测试 / 脚本复用；不读 `process.argv`）。
 *
 * @param config 已加载的配置。
 * @param options.database 已建好的数据库句柄；缺省按档位现建（`createDatabase`）。
 * @returns `{ url, port, close }`：`close()` 关闭实例与数据库（幂等）。
 * @throws 配置非法（`ConfigError`）或监听失败时抛出（由 {@link main} 翻译成退出码）。
 */
export async function start(
  config: Config,
  options: { readonly database?: DatabaseHandle } = {}
): Promise<{ readonly url: string; readonly port: number; readonly close: () => Promise<void> }> {
  // 配置闸在**建连之前**：密钥缺失 / 太短是纯配置问题，不该先花时间连库再失败。
  requireSecretKey(config);
  const handle = options.database ?? createDatabase(config);
  const model = modelStackFromEnv();
  const app = buildApp({
    config,
    database: handle.database,
    dialect: handle.dialect,
    ...(model === undefined ? {} : { model }),
  });
  const port = resolvePort(config);
  try {
    await app.listen({ host: HOST, port });
  } catch (error) {
    // 监听失败也必须把实例与数据库关掉：否则已注册的 hook / 计时器 / 连接留在事件循环里，
    // 进程会「退不干净」，而调用方只看到一个退出码，很难归因。
    await app.close();
    await handle.close();
    throw error;
  }
  return {
    url: `http://${HOST}:${port}`,
    port,
    close: async (): Promise<void> => {
      await app.close();
      await handle.close();
    },
  };
}

/**
 * 进程主流程。
 *
 * 退出码约定：`0` = 启动成功且未退出；`EXIT_CONFIG_INVALID` = 配置非法；
 * `EXIT_LISTEN_FAILED` = 监听失败。收到 SIGINT / SIGTERM 后由
 * {@link createShutdownHandler} 接管：正常关闭 `exit(0)`，超时或关闭失败 `exit(1)`
 * （见 `./shutdown.ts` 的 FIX-07 说明）。
 *
 * @param argv 命令行参数（本版无参数，保留形参以便将来加 `--port` 之类的显式覆盖）。
 * @returns 上述启动期退出码。
 */
export async function main(argv: readonly string[] = process.argv.slice(2)): Promise<number> {
  // argv 本版未使用，显式 void 掉以免 lint 误报，同时保留扩展点。
  void argv;

  let config: Config;
  try {
    config = loadConfig();
    // L-3 / R-22：密钥闸**必须在启动路径上**。`TokenService` 只校非空、不校 32 字节，
    // 所以这一行是把"密钥不足 ⇒ CONFIGURATION_ERROR"接上线的唯一位置。
    requireSecretKey(config);
  } catch (error) {
    if (error instanceof ConfigError) {
      process.stderr.write(`api 启动失败：配置非法 — ${error.message}\n`);
      return EXIT_CONFIG_INVALID;
    }
    throw error;
  }

  const log = createLogger({ level: config.logLevel });
  const port = resolvePort(config);

  let close: (() => Promise<void>) | null = null;
  try {
    const handle = await start(config);
    close = handle.close;
  } catch (error) {
    log.error({ err: error, host: HOST, port }, "api 监听失败");
    return EXIT_LISTEN_FAILED;
  }

  log.info({ host: HOST, port, mode: config.mode }, "api 已启动");

  // 关闭流程（FIX-07）：close 可能被空闲 keep-alive 连接 / 租借中的 PG 连接挂住，
  // 因此走「兜底超时」而不是无限 await —— 超时后强制 exit(1) 并留日志，
  // 否则进程"收到 SIGTERM 却永不退出"，编排系统只能等宽限期到了再 SIGKILL。
  const shutdownLog: ShutdownLogger = {
    info: (fields, message) => {
      log.info(fields, message);
    },
    error: (fields, message) => {
      log.error(fields, message);
    },
  };

  const handler = createShutdownHandler({
    close: async (): Promise<void> => {
      await close?.();
    },
    timeoutMs: config.shutdownTimeoutMs,
    // 直接把退出码交给 process：关闭流程结束后本进程不该再留在事件循环里。
    // `process.exit` 是同步终止，故要求此前的日志写入已经落盘（pino 默认同步写目标）。
    exit: (code: number) => {
      process.exit(code);
    },
    log: shutdownLog,
  });

  // SIGINT 与 SIGTERM 各接一次；`process.once` 只挡同名信号重入，
  // 「先 SIGTERM 再 SIGINT」的去重由 handler 的首次调用闸门负责。
  process.once("SIGINT", () => {
    void handler.shutdown("SIGINT");
  });
  process.once("SIGTERM", () => {
    void handler.shutdown("SIGTERM");
  });

  return 0;
}

/** 是否被当作入口脚本直接执行（而非 `import`）。 */
function isInvokedAsScript(): boolean {
  const entry = process.argv[1];
  if (entry === undefined) return false;
  try {
    return import.meta.url === pathToFileURL(entry).href;
  } catch {
    return false;
  }
}

if (isInvokedAsScript()) {
  main()
    .then((code) => {
      if (code !== 0) process.exitCode = code;
    })
    .catch((error: unknown) => {
      process.stderr.write(`api 启动失败：未捕获异常 — ${String(error)}\n`);
      process.exitCode = 1;
    });
}
