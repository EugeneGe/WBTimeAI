// @wbtime/config · 环境变量读取原语。
//
// 只做「取值 / 判空 / 类型转换」三件事，不做业务判定（「哪些键缺失才算致命」的
// 判定在 ./config.ts）。所有键都以 `WBTIME_` 前缀，避免与宿主进程变量撞名。
//
// 错误类型统一：值非法（不是整数 / 不是布尔）与键缺失**都**抛 `ConfigError`。
// 为什么不再抛 `TypeError`：启动期只应有一种可判别的错误形态，调用方按
// `error.code === "CONFIGURATION_ERROR"` 就能统一走「配置非法 ⇒ 退出码 78」的路径；
// 混入 TypeError 会迫使每个调用点写两套判断，且很容易被上层 catch 漏掉。
// 导入方向固定为 ./errors.ts（**禁止**从 ./config.ts 取，那会形成循环依赖）。

import { ConfigError } from "./errors.js";

export type EnvSource = Readonly<Record<string, string | undefined>>;

/** 读取环境变量：空串按「未提供」处理（shell 里 `FOO=` 是常见误配）。 */
export function readEnv(env: EnvSource, key: string): string | undefined {
  const raw = env[key];
  if (raw === undefined) return undefined;
  const trimmed = raw.trim();
  return trimmed === "" ? undefined : trimmed;
}

/** 读必需键；缺失或空串时把 key 记进 missing 列表（由调用方统一抛错）。 */
export function requireEnv(env: EnvSource, key: string, missing: string[]): string | undefined {
  const value = readEnv(env, key);
  if (value === undefined) missing.push(key);
  return value;
}

/** 读可选键，带默认值。 */
export function envWithDefault(env: EnvSource, key: string, fallback: string): string {
  return readEnv(env, key) ?? fallback;
}

/** 读整数键：非法值不是「缺失」，直接抛 ConfigError（值错 ≠ 没配）。 */
export function envAsInt(env: EnvSource, key: string, fallback: number): number {
  const raw = readEnv(env, key);
  if (raw === undefined) return fallback;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed)) {
    throw new ConfigError(
      `环境变量 ${key} 不是整数: ${JSON.stringify(raw)}（合法取值：十进制整数，如 8000）`,
    );
  }
  return parsed;
}

/** 读布尔键：接受 1/0/true/false/yes/no/on/off（大小写不敏感）。 */
export function envAsBool(env: EnvSource, key: string, fallback: boolean): boolean {
  const raw = readEnv(env, key);
  if (raw === undefined) return fallback;
  const lower = raw.toLowerCase();
  if (["1", "true", "yes", "on"].includes(lower)) return true;
  if (["0", "false", "no", "off"].includes(lower)) return false;
  throw new ConfigError(
    `环境变量 ${key} 不是布尔值: ${JSON.stringify(raw)}（合法取值：1/0/true/false/yes/no/on/off）`,
  );
}
