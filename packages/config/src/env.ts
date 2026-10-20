// @wbtime/config · 环境变量读取原语。
//
// 只做「取值 / 判空 / 类型转换」三件事，不做业务判定；缺关键配置的抛错在
// ./config.ts。所有键都以 `WBTIME_` 前缀，避免与宿主进程变量撞名。

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
    throw new TypeError(`环境变量 ${key} 不是整数: ${JSON.stringify(raw)}`);
  }
  return parsed;
}

/** 读布尔键：接受 1/0/true/false/yes/no（大小写不敏感）。 */
export function envAsBool(env: EnvSource, key: string, fallback: boolean): boolean {
  const raw = readEnv(env, key);
  if (raw === undefined) return fallback;
  const lower = raw.toLowerCase();
  if (["1", "true", "yes", "on"].includes(lower)) return true;
  if (["0", "false", "no", "off"].includes(lower)) return false;
  throw new TypeError(`环境变量 ${key} 不是布尔值: ${JSON.stringify(raw)}`);
}
