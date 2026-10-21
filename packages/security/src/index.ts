/**
 * `@wbtime/security` —— 安全原语出口（V0.2.0 · M-04）。
 *
 * 本版**只有一个**原语：`scanSensitive`（及其常量）。
 * `redactSensitive` / `SafetyGate` / 七挂点 / 语义审核归 V0.3.0
 * （依据 `docs/V1.0/00-安全拦截链-设计补充.md` §15 / R16），不在此处预留空壳 ——
 * 空壳会被误当"已实现"，比缺函数更危险。
 *
 * 常量与函数的导出面**就是** M-04 的等价性判据面（计划 §6）：
 * `SENSITIVE_KEY_PATTERN` / `TOKEN_VALUE_PATTERNS` 必须可被测试逐项对齐 py 源码，
 * 因此两者是 public export 而不是模块内部细节。
 */

export {
  scanSensitive,
  SENSITIVE_KEY_PATTERN,
  TOKEN_VALUE_PATTERNS,
  PLACEHOLDER_MARKERS,
  REFERENCE_PREFIXES,
  HIGH_ENTROPY_MIN_LENGTH,
  HIGH_ENTROPY_THRESHOLD,
  MAX_SCAN_DEPTH,
  MAX_FINDINGS,
} from "./scan-sensitive.js";

export type {
  Finding,
  FindingReason,
  ScanSensitiveOptions,
  ScanSensitiveData,
  TooDeepData,
} from "./scan-sensitive.js";
