// @wbtime/config · 平台配置加载。
//
// 两种档位：
//   * `local`  —— 单机档，SQLite；数据库位置可缺省（有兜底路径）。
//   * `server` —— 服务端档，PostgreSQL；`WBTIME_DATABASE_URL` **必需**，缺失即红。
//
// 缺关键配置抛 `ConfigError`（错误码取 core 的 CONFIGURATION_ERROR，与
// contracts/errors.json 同源，不在此处另立一套码）。
//
// `ConfigError` 类型定义已下沉到 ./errors.ts（`env.ts` 也要用它，而 env.ts 不能
// 反向依赖本文件，否则成环）。此处只 re-export，公共导出面保持不变。

import { envAsBool, envAsInt, envWithDefault, readEnv, requireEnv } from "./env.js";
import type { EnvSource } from "./env.js";
import { ConfigError } from "./errors.js";

export { ConfigError } from "./errors.js";

export type AiMode = "local" | "server";

export const AI_MODES: readonly AiMode[] = ["local", "server"];

export interface Config {
  /** 运行档位。 */
  readonly mode: AiMode;
  /** 数据库连接串；local 档有兜底，server 档必填。 */
  readonly databaseUrl: string;
  /** SQLite 档的文件路径（仅 local 档有意义）。 */
  readonly sqlitePath: string | null;
  /** 服务监听端口。 */
  readonly port: number;
  /** 日志级别（交给 @wbtime/logging）。 */
  readonly logLevel: string;
  /** 是否开启 JSON 日志（server 档默认开，可由 `WBTIME_LOG_JSON` 显式覆盖）。 */
  readonly logJson: boolean;
}

export const ENV_KEYS = {
  mode: "WBTIME_AI_MODE",
  databaseUrl: "WBTIME_DATABASE_URL",
  sqlitePath: "WBTIME_SQLITE_PATH",
  port: "WBTIME_API_PORT",
  logLevel: "WBTIME_LOG_LEVEL",
  logJson: "WBTIME_LOG_JSON",
} as const;

export const DEFAULTS = {
  mode: "local" as AiMode,
  sqlitePath: "./.wbtime/wbtime.db",
  port: 8000,
  logLevel: "info",
} as const;

/** local 档的兜底 SQLite 连接串。 */
export function defaultSqliteUrl(path: string): string {
  return `sqlite:${path}`;
}

export function isAiMode(value: string): value is AiMode {
  return (AI_MODES as readonly string[]).includes(value);
}

/**
 * 加载配置。
 *
 * @param env 环境变量源，默认 `process.env`（传参是为了可测，测试不需要真改环境）。
 * @throws {ConfigError} 缺关键配置、档位非法，或数值 / 布尔键取值非法。
 */
export function loadConfig(env: EnvSource = process.env): Config {
  const missing: string[] = [];

  const rawMode = envWithDefault(env, ENV_KEYS.mode, DEFAULTS.mode).toLowerCase();
  if (!isAiMode(rawMode)) {
    throw new ConfigError(
      `${ENV_KEYS.mode} 非法: ${JSON.stringify(rawMode)}（合法值: ${AI_MODES.join(" | ")}）`,
    );
  }
  const mode: AiMode = rawMode;

  const sqlitePath = envWithDefault(env, ENV_KEYS.sqlitePath, DEFAULTS.sqlitePath);

  let databaseUrl: string | undefined;
  if (mode === "server") {
    databaseUrl = requireEnv(env, ENV_KEYS.databaseUrl, missing);
  } else {
    databaseUrl = readEnv(env, ENV_KEYS.databaseUrl) ?? defaultSqliteUrl(sqlitePath);
  }

  if (missing.length > 0) {
    throw new ConfigError(
      `缺少必需环境变量（mode=${mode}）: ${missing.join(", ")}`,
      [...missing],
    );
  }

  return {
    mode,
    databaseUrl: databaseUrl as string,
    sqlitePath: mode === "local" ? sqlitePath : null,
    port: envAsInt(env, ENV_KEYS.port, DEFAULTS.port),
    logLevel: envWithDefault(env, ENV_KEYS.logLevel, DEFAULTS.logLevel),
    // 默认值随档位走，但**允许** `WBTIME_LOG_JSON` 显式覆盖：
    // 以前这里硬编码 `mode === "server"`，等于让 ENV_KEYS.logJson 成为死配置
    // （声明了却永不生效），运维按文档设了 `WBTIME_LOG_JSON=false` 也关不掉 JSON 日志。
    logJson: envAsBool(env, ENV_KEYS.logJson, mode === "server"),
  };
}

/** 不抛错版本：配置缺失时返回 `null`，供启动期「先打印诊断再退出」的场景。 */
export function tryLoadConfig(env: EnvSource = process.env): Config | null {
  try {
    return loadConfig(env);
  } catch (error) {
    if (error instanceof ConfigError) return null;
    throw error;
  }
}
