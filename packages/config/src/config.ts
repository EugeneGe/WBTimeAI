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
  /**
   * 优雅关闭的**兜底时长**（毫秒，FIX-07）。
   *
   * 为什么必须是配置而不是常量：它得与部署侧的 `terminationGracePeriodSeconds` 对得上 ——
   * 兜底短于编排宽限期 ⇒ 进程能自己退出并留下日志；长于宽限期 ⇒ 编排系统先 SIGKILL，
   * 兜底形同不存在。默认 10_000（见 `DEFAULTS.shutdownTimeoutMs`）。
   *
   * `0` = **不设兜底**（只 `await close()`）。它只为测试与"必须等完"的特殊环境存在；
   * 生产配 0 等于放弃 FIX-07 的保护，因此 {@link loadConfig} 不拦它，但启动日志要打得出来。
   */
  readonly shutdownTimeoutMs: number;
  /**
   * 未认证 `POST /api/v1/auth/register` 的限速：**每客户端 IP / 每分钟**（FIX-04 / R-34）。
   *
   * 为什么必须限速：注册是**不需要令牌**的入口，且每个请求都会跑一次 `argon2id`
   * （m=64MiB）—— 单个客户端就能把 CPU 与内存打满，这是本版唯一的未认证算力放大面。
   *
   * `0` = **关闭限速**（仅测试与"内网单机"场景）；默认 20（见
   * `DEFAULTS.registerRateLimitPerMinute`）。负数与非整数由 {@link loadConfig} 当场拒绝：
   * 静默夹取会让"配错了"看起来像"配对了"。
   */
  readonly registerRateLimitPerMinute: number;
  /**
   * 主密钥（`WBTIME_AI_SECRET_KEY`）原文；**未配置为 `null`**。
   *
   * 为什么允许 `null` 而不是硬必填：V0.1.0 的 `loadConfig({})` 是**合法调用**
   * （`packages/config/tests/config.test.mjs` 就在用），且"跑不需要令牌的功能
   * （健康检查 / 前端静态面）也要密钥"是错的。真正的门槛在
   * {@link requireSecretKey} —— 需要签令牌的组件（认证装配）必须显式过它，
   * 缺失或不足 32 字节一律 `CONFIGURATION_ERROR`。
   *
   * 注意：字段存在但**太短**时 `loadConfig` 当场抛（"值错 ≠ 没配"，
   * 与 `envAsInt` 对非法整数的口径一致），不会留到运行期。
   */
  /**
   * 模型请求超时（毫秒）。R3-15：默认 60000、**上界 600000**，越界即启动失败。
   */
  readonly modelRequestTimeoutMs: number;
  /**
   * 模型最大重试次数。R3-15：**上界 1（硬钉死）** —— 重试风暴比失败更难排查。
   * 注：`invalid_request` 类错误**恒不重试**（见 `modules/model/errors.ts`）。
   */
  readonly modelMaxRetries: number;
  /**
   * 是否允许装配 `fake` Provider（R3-19）。生产默认 `false` ⇒ 误配即 `CONFIGURATION_ERROR`。
   * 同时认环境变量 `NODE_ENV=test`（工厂内再判一次，双重保险）。
   */
  readonly modelAllowFakeProvider: boolean;
  readonly secretKey: string | null;
}

export const ENV_KEYS = {
  mode: "WBTIME_AI_MODE",
  databaseUrl: "WBTIME_DATABASE_URL",
  sqlitePath: "WBTIME_SQLITE_PATH",
  port: "WBTIME_API_PORT",
  logLevel: "WBTIME_LOG_LEVEL",
  logJson: "WBTIME_LOG_JSON",
  secretKey: "WBTIME_AI_SECRET_KEY",
  /** 优雅关闭兜底时长（毫秒）。`0` = 不设兜底（仅测试/特殊场景）。 */
  shutdownTimeoutMs: "WBTIME_SHUTDOWN_TIMEOUT_MS",
  /** 未认证 register 的限速（每 IP / 每分钟）。`0` = 关闭（仅测试）。 */
  registerRateLimitPerMinute: "WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE",
  /** 模型请求超时（毫秒）。 */
  modelRequestTimeoutMs: "WBTIME_MODEL_TIMEOUT_MS",
  /** 模型最大重试次数（0 或 1；>1 直接拒）。 */
  modelMaxRetries: "WBTIME_MODEL_MAX_RETRIES",
  /** 是否放行 fake provider（与 `NODE_ENV=test` 等价）。 */
  modelAllowFakeProvider: "WBTIME_AI_ALLOW_FAKE_PROVIDER",
} as const;

export const DEFAULTS = {
  mode: "local" as AiMode,
  sqlitePath: "./.wbtime/wbtime.db",
  port: 8000,
  logLevel: "info",
  /** 10 秒：给"关闭监听 + 等在途请求 + 关连接池"留足时间，又短于常见 30s 宽限期。 */
  shutdownTimeoutMs: 10_000,
  /**
   * 20 次/分钟/每 IP：够一个团队在同一出口 IP 后连续开户，又不足以把 argon2 打满。
   * 阈值来源见施工期裁定 R-34（不是拍脑袋：按"argon2id 单次 ≈ 60ms × 20 = 1.2s CPU/分钟/IP"
   * 折算，单 IP 最多占用 2% 的单核）。
   */
  registerRateLimitPerMinute: 20,
  /** 60 秒：与 py 线 `DEFAULT_TIMEOUT_SECONDS=60.0` 同值（跨实现可比）。 */
  modelRequestTimeoutMs: 60_000,
  /** 只重试一次：配合退避已足够扛 429/5xx 抖动，再多就是重试风暴。 */
  modelMaxRetries: 1,
  modelAllowFakeProvider: false,
} as const;

/**
 * `WBTIME_AI_SECRET_KEY` 的最小长度（**UTF-8 字节**，不是字符数）。
 *
 * 口径原样继承 py 线 `wbtime_ai_security/constants.py` 的 `MIN_SECRET_KEY_BYTES`：
 * HS256 的密钥空间至少应与哈希输出等强（≥ 256 bit = 32 字节），同时对齐 AES-256。
 * 用**字节**而非字符数是关键：`"密钥"` 只有 2 个字符却有 6 个字节，按字符算会
 * 放过一个强度远不如 32 字节的密钥。
 */
export const MIN_SECRET_KEY_BYTES = 32;

/** 密钥的 UTF-8 字节长度（不依赖 Buffer，浏览器/Node 同口径）。 */
export function secretKeyByteLength(secret: string): number {
  return new TextEncoder().encode(secret).length;
}

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
    shutdownTimeoutMs: resolveShutdownTimeoutMs(env),
    registerRateLimitPerMinute: resolveRegisterRateLimit(env),
    modelRequestTimeoutMs: resolveModelRequestTimeoutMs(env),
    modelMaxRetries: resolveModelMaxRetries(env),
    modelAllowFakeProvider: envAsBool(env, ENV_KEYS.modelAllowFakeProvider, DEFAULTS.modelAllowFakeProvider),
    secretKey: resolveSecretKey(env),
  };
}

/**
 * 读模型请求超时（毫秒）。
 *
 * 拒 **≤0 与 >600000**：0 会让每次调用立刻超时（不是"不超时"），越上界会把
 * 一个卡死的上游变成占满 worker 的长尾。
 */
function resolveModelRequestTimeoutMs(env: EnvSource): number {
  const value = envAsInt(env, ENV_KEYS.modelRequestTimeoutMs, DEFAULTS.modelRequestTimeoutMs);
  if (value <= 0 || value > 600_000) {
    throw new ConfigError(
      `${ENV_KEYS.modelRequestTimeoutMs} 必须在 1..600000 之间：${value}（毫秒）`,
      [ENV_KEYS.modelRequestTimeoutMs],
    );
  }
  return value;
}

/**
 * 读模型最大重试次数。
 *
 * 只接受 **0 或 1**：`0` = 不重试（更保守，允许）；`>1` 一律拒（R3-15 上界硬钉死）。
 */
function resolveModelMaxRetries(env: EnvSource): number {
  const value = envAsInt(env, ENV_KEYS.modelMaxRetries, DEFAULTS.modelMaxRetries);
  if (value < 0 || value > 1) {
    throw new ConfigError(
      `${ENV_KEYS.modelMaxRetries} 只能是 0 或 1：${value}（重试上界硬钉死，防重试风暴）`,
      [ENV_KEYS.modelMaxRetries],
    );
  }
  return value;
}

/**
 * 读未认证注册的限速阈值（每 IP / 每分钟）。
 *
 * 只拒**负数**：`0` 是显式的"关闭限速"（测试 / 内网单机），语义清晰；
 * 负数没有语义，属于配错，必须当场炸（与 `envAsInt` 对非整数的口径一致）。
 */
function resolveRegisterRateLimit(env: EnvSource): number {
  const value = envAsInt(
    env,
    ENV_KEYS.registerRateLimitPerMinute,
    DEFAULTS.registerRateLimitPerMinute,
  );
  if (value < 0) {
    throw new ConfigError(
      `${ENV_KEYS.registerRateLimitPerMinute} 不能为负数：${value}（0 = 关闭限速，仅测试可用；正整数为每分钟每 IP 的次数）`,
      [ENV_KEYS.registerRateLimitPerMinute],
    );
  }
  return value;
}

/**
 * 读优雅关闭兜底时长（毫秒）。
 *
 * 只拒**负数**：`0` 是显式的"不设兜底"（测试 / 特殊环境），语义清晰且被文档与
 * 启动日志覆盖；负数没有语义，属于配错，必须当场炸（与 `envAsInt` 的口径一致）。
 */
function resolveShutdownTimeoutMs(env: EnvSource): number {
  const value = envAsInt(env, ENV_KEYS.shutdownTimeoutMs, DEFAULTS.shutdownTimeoutMs);
  if (value < 0) {
    throw new ConfigError(
      `${ENV_KEYS.shutdownTimeoutMs} 不能为负数：${value}（0 表示不设兜底，正整数为毫秒）`,
      [ENV_KEYS.shutdownTimeoutMs],
    );
  }
  return value;
}

/**
 * 读主密钥：**未配置 ⇒ `null`；配了但太短 ⇒ 当场抛**。
 *
 * 这两种情形的区别是刻意的："没配"是部署选择（可能这个进程不需要签令牌），
 * "配了个 8 字节的"是**配错**——配错必须在启动期炸，而不是等到第一个用户登录
 * 才发现签出来的令牌可被离线爆破。错误信息只带**长度**，绝不回显密钥内容
 * （py 线 `ensure_secret_key_length` 的同一约定）。
 */
function resolveSecretKey(env: EnvSource): string | null {
  const raw = readEnv(env, ENV_KEYS.secretKey);
  if (raw === undefined) return null;
  const bytes = secretKeyByteLength(raw);
  if (bytes < MIN_SECRET_KEY_BYTES) {
    throw new ConfigError(
      `${ENV_KEYS.secretKey} 太短：${bytes} 字节 < ${MIN_SECRET_KEY_BYTES} 字节（UTF-8 字节数）；` +
        "HS256 的密钥空间至少应与哈希输出等强（≥256 bit）",
      [ENV_KEYS.secretKey],
    );
  }
  return raw;
}

/**
 * 取主密钥，缺失或不达标即 `CONFIGURATION_ERROR`。
 *
 * 需要签发/校验令牌的组件（认证装配）**必须**经此入口取密钥，不要在别处
 * 直接读 `config.secretKey` 再自己判空 —— 那样"忘了判空"就会变成运行期的
 * `TypeError: key must be a Uint8Array`，错误码从 422 变成 500。
 *
 * @param config 已加载的配置。
 * @throws {ConfigError} 未配置或不足 {@link MIN_SECRET_KEY_BYTES} 字节。
 */
export function requireSecretKey(config: Config): string {
  const secret = config.secretKey;
  if (secret === null) {
    throw new ConfigError(
      `缺少必需环境变量: ${ENV_KEYS.secretKey}（签发 / 校验 JWT 所必需）`,
      [ENV_KEYS.secretKey],
    );
  }
  const bytes = secretKeyByteLength(secret);
  if (bytes < MIN_SECRET_KEY_BYTES) {
    throw new ConfigError(
      `${ENV_KEYS.secretKey} 太短：${bytes} 字节 < ${MIN_SECRET_KEY_BYTES} 字节（UTF-8 字节数）`,
      [ENV_KEYS.secretKey],
    );
  }
  return secret;
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
