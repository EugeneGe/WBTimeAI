// @wbtime/core · 错误码门面。
//
// 错误码本体在 `./generated/errors.generated.ts`，由 scripts/gen_platform_contracts.mjs
// 从 contracts/errors.json 逐字生成 —— **不手抄、不推导**。本文件只做再导出，
// 不在此处新增任何码值。
//
// 唯一的例外是 `dependencyMissing()`：`DEPENDENCY_MISSING` 的 HTTP 状态在契约里
// **非全量成立**（`http_status_uniform=false`，实测 500×2 / 503×8，见
// `contracts/errors.json` → `codes.DEPENDENCY_MISSING`），因此不能只靠生成表
// `ERROR_HTTP_STATUS` 取值 —— 那会把 2 处 500 静默说成 503。参数化活在生成表
// **之外**：状态由 call-site 显式传入，`status` 无默认值 ⇒ 漏传即 `tsc` 报错，
// 从**类型层**消灭「全局 503」。
//
// 生成表本身**不得**改动：`ERROR_HTTP_STATUS.DEPENDENCY_MISSING` 必须保持契约值
// 503，否则 `pnpm gate:platform` 第 ④ 项（逐码全等）立即红。

import { ERROR_CODES } from "./generated/errors.generated.js";
import type { ErrorCode } from "./generated/errors.generated.js";

export {
  ERROR_CODES,
  ERROR_CODE_LIST,
  ERROR_DESCRIPTIONS,
  ERROR_HTTP_STATUS,
  UNKNOWN_ERROR_CODE,
  httpStatusFor,
} from "./generated/errors.generated.js";
export type { ErrorCode } from "./generated/errors.generated.js";

/** `DEPENDENCY_MISSING` 的码值（取自生成表，不写字面量）。 */
export const DEPENDENCY_MISSING_CODE: ErrorCode = ERROR_CODES.DEPENDENCY_MISSING;

/**
 * `DEPENDENCY_MISSING` 允许的 HTTP 状态。
 *
 * 只允许契约实测出现过的两个值：503（8 处显式 `status_code=503`）与 500（2 处未传
 * `status_code` 的构造点回落 `DomainError` 默认 500）。传 502 等臆造值必须在
 * **类型层**就通不过。
 */
export type DependencyMissingStatus = 500 | 503;

/**
 * `DEPENDENCY_MISSING` 的域错误载体。
 *
 * 形态对齐 `@wbtime/domain` 的 `DomainError`（`code` + `data` + `message`），额外
 * 携带**显式** `status`：`DomainError` 本身没有状态字段，而本码的状态必须由
 * call-site 决定，故不能靠「码 → 状态」查表。API 层的统一错误出口按
 * `typeof error.status === "number"` 优先采纳它（见 `apps/api/src/http/error-handler.ts`）。
 */
export class DependencyMissingError extends Error {
  /** 契约错误码，恒为 `"DEPENDENCY_MISSING"`。 */
  readonly code: ErrorCode;
  /** call-site 显式声明的 HTTP 状态（500 或 503，无默认值）。 */
  readonly status: DependencyMissingStatus;
  /** 附加上下文，契约实测形态 = `{capability: <str>}`。 */
  readonly data: Readonly<Record<string, unknown>>;

  constructor(capability: string, status: DependencyMissingStatus) {
    super(`依赖能力未装配：${capability}（该能力对应的实现缺失或未启用）`);
    this.name = "DependencyMissingError";
    this.code = DEPENDENCY_MISSING_CODE;
    this.status = status;
    this.data = Object.freeze({ capability });
  }
}

/**
 * 构造 `DEPENDENCY_MISSING`（可选依赖 / 能力未装配）。
 *
 * **`status` 必填、无默认值**：这是本版对「全局 503」的结构性封堵 —— 少传一个参数
 * 就是编译错误，而不是运行时悄悄回落成 503。取值只允许 `500` 或 `503`（契约实测
 * 分布），传其它数字在类型层不通过。
 *
 * @param capability 缺失的能力名（同时写进 `data.capability`，供下游定位）。
 * @param status call-site 决定的 HTTP 状态：503 = 显式声明依赖未装配；
 *   500 = 契约里那 2 处未传 `status_code` 的构造点语义（回落域错误默认 500）。
 * @returns 可直接 `throw` 的错误对象（`code` / `status` / `data` / `message` 齐备）。
 * @throws {TypeError} `capability` 为空字符串或非字符串时（避免 `data.capability`
 *   落成空值，让失败壳失去定位信息）。
 */
export function dependencyMissing(
  capability: string,
  status: DependencyMissingStatus,
): DependencyMissingError {
  if (typeof capability !== "string" || capability.trim() === "") {
    throw new TypeError("dependencyMissing: capability 必须是非空字符串（写入 data.capability）");
  }
  return new DependencyMissingError(capability, status);
}
