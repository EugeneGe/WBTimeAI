// @wbtime/event · 数值上线格式（contracts/sse/channels.json → numeric_format）。
//
// 为什么必须定死：Python `json.dumps(1.0) == '1.0'`，而 JS `JSON.stringify(1.0) == '1'`。
// 只要整数值浮点能上帧，「golden 帧逐字节相同」在原理上就不可达（契约原话）。
// 因此策略 `integers-only-on-the-wire`：
//
//   bool            → 原样（bool 判定先于 int，避免 true → 1）
//   整数            → 原样
//   整数值浮点      → int(value)（如 1.0 → 1；-0.0 → 0）
//   其余有限浮点    → 定点十进制字符串，小数位数由契约给出（0.5 → "0.500000"）
//   NaN / ±Infinity → 抛错（不可上线，静默降级是本项目明令禁止的）
//   对象 / 数组     → 递归，且**键序不变**
//
// 小数位数从契约 example 解析而来（`NUMERIC_FIXED_DECIMALS`），不在此处硬编码。

import { NUMERIC_FIXED_DECIMALS } from "./generated/channels.generated.js";

/** 上线后的数值形态：只能是整数或定点十进制字符串。 */
export type WireNumber = number | string;

/** 单个数值的上线归一化。 */
export function normalizeWireNumber(value: number): WireNumber {
  if (typeof value !== "number" || Number.isNaN(value) || value === Infinity || value === -Infinity) {
    throw new RangeError(`数值不可上线（NaN / Infinity）: ${String(value)}`);
  }
  // -0 必须落到 0：JSON.stringify(-0) 已是 "0"，但显式处理可让 upstream 也能看到 0。
  if (Object.is(value, -0)) return 0;
  if (Number.isInteger(value)) return value;
  return value.toFixed(NUMERIC_FIXED_DECIMALS);
}

/**
 * 递归归一化整个 payload。
 *
 * 键序保持插入序（契约 `sort_keys: false`，键序 == 契约 `payload_keys_in_order`）。
 * 非 plain object（Date / Map / 类实例等）原样透出 —— 它们不在契约数值规则覆盖范围内，
 * 交给上层的 JSON 序列化处理，避免这里静默改语义。
 */
export function normalizePayload(value: unknown): unknown {
  if (typeof value === "boolean" || typeof value === "string" || value === null || value === undefined) {
    return value;
  }
  if (typeof value === "number") {
    return normalizeWireNumber(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizePayload(item));
  }
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      out[key] = normalizePayload(item);
    }
    return out;
  }
  return value;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null) return false;
  const proto = Object.getPrototypeOf(value) as object | null;
  return proto === Object.prototype || proto === null;
}
