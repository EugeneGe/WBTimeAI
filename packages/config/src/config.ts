// @wbtime/config · 平台配置加载。
//
// 两种档位：
//   * `local`  —— 单机档，SQLite；数据库位置可缺省（有兜底路径）。
//   * `server` —— 服务端档，PostgreSQL；`WBTIME_DATABASE_URL` **必需**，缺失即红。
//
// 缺关键配置抛 `ConfigError`（错误码取 core 的 CONFIGURATION_ERROR，与
// contracts/errors.json 同源，不在此处另立一套码）。

import { ERROR_CODES, httpStatusFor } from "@wbtime/core";
import type { ErrorCode } from "@wbtime/core";

import { envAsInt, envWithDefault, readEnv, requireEnv } from "./env.js";
import type { EnvSource } from "./env.js";

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
  /** 是否开启 JSON 日志（server 档默认开）。 */
  readonly logJson: boolean;
}

/** 配置缺失 / 非法。错误码与 HTTP 状态均来自 contracts/errors.json。 */
export class ConfigError extends Error {
  readonly name = "ConfigError";
  readonly code: ErrorCode = ERROR_CODES.CONFIGURATION_ERROR;
  /** 缺失的环境变量键（可能是多个，一次性报全，逐个补太慢）。 */
  readonly missingKeys: readonly string[];

  constructor(message: string, missingKeys: readonly string[] = []) {
    super(message);
    this.missingKeys = missingKeys;
  }

  /** 该错误对应的 HTTP 状态码（契约：CONFIGURATION_ERROR → 422）。 */
  get httpStatus(): number {
    return httpStatusFor(this.code);
  }
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
 * @throws {ConfigError} 缺关键配置或档位非法。
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
    logJson: mode === "server",
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
