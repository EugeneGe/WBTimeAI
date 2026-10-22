/**
 * `@wbtime/security` —— 安全原语出口。
 *
 * M-04（V0.2.0）：`scanSensitive` 及其常量（detect-only，凭据子集）。
 * T3-13（V0.3.0）：`redactSensitive`（R3-16 同源脱敏）+ 规则注册表 + 风险等级映射。
 *
 * `SafetyGate` 的**编排**不在这里（R3-16 ①：编排归 `apps/api/src/modules/safety`）；
 * 本包不进 `@wbtime/contracts` / `packages/ports`（`gate:extpoints` 仍 **9**）。
 * 依赖仅 `@wbtime/core`（值）+ `@wbtime/domain`（`DomainError`，V0.2.0 R-11 裁定）。
 */

// ---- M-04（V0.2.0，detect-only 凭据扫描）----------------------------------
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

// ---- T3-13（V0.3.0，同源规则注册表 + 脱敏 + 等级映射）----------------------
export {
  SAFETY_RULES,
  detectSensitive,
  redactSensitive,
  registeredRuleIds,
  baselineRuleIds,
  COVERAGE_STATEMENT,
} from "./rule-registry.js";

export type {
  SafetyRule,
  SafetyCategory,
  SafetyHit,
  DetectOptions,
  RedactResult,
} from "./rule-registry.js";

export { riskLevelOf } from "./classify.js";
export type { Stage, Provenance, RiskLevel } from "./classify.js";
