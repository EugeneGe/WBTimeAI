// apps/api · 错误码 → HTTP 状态（30 码 → 13 类）+ 框架层状态 → 码。
//
// **不手抄状态表**：唯一数据源是生成物 `@wbtime/core` 的 `ERROR_HTTP_STATUS`
// （由 `scripts/gen_platform_contracts.mjs` 从 `contracts/errors.json` →
// `codes[*].http_status` 逐码生成）。本文件只做**派生与读取**：
//   * 13 类 = `new Set(Object.values(ERROR_HTTP_STATUS))` 的取值集合（不是手数）；
//   * 反查索引 = 由同一张表翻转而来，不在代码里另立一份。
//
// 为什么不能用 `contracts/errors.json` → `reverse_map_by_http_status` 当 13 类映射源：
// 它只有 6 项（仅收「无专属异常类」的码），口径陷阱已写进 `02-响应壳与SSE.md` §3.1
// 的引用框。那份 6 项表在本文件里只有一个用途 —— **框架层**（Fastify 404/405 之类
// 没有业务码的出口）挑一个默认码，见 `FRAMEWORK_BASE_CODE_BY_STATUS` 的注释。

import { ERROR_CODES, ERROR_HTTP_STATUS, UNKNOWN_ERROR_CODE, httpStatusFor } from "@wbtime/core";
import type { ErrorCode } from "@wbtime/core";

/** 码 → 状态（生成表的只读再导出，禁止在此改动任何一项）。 */
export const HTTP_STATUS_BY_CODE: Readonly<Record<ErrorCode, number>> = ERROR_HTTP_STATUS;

/**
 * 13 类 HTTP 状态的升序清单（由生成表派生）。
 *
 * 实测应为 `[401,403,404,405,409,410,422,423,429,500,501,503,504]`（13 项）；
 * 数量与取值由 `apps/api/tests/errors-contract.test.mjs`（K-5）逐项比对契约。
 */
export const HTTP_STATUS_CLASSES: readonly number[] = Object.freeze([
  ...new Set(Object.values(ERROR_HTTP_STATUS)),
].sort((left, right) => left - right));

/**
 * 状态 → 码的反查索引（由生成表翻转；同一状态多码时保持 `ERROR_CODE_LIST` 之外的
 * 字典序稳定，避免依赖对象键序这种实现细节）。
 */
export const CODES_BY_HTTP_STATUS: Readonly<Record<number, readonly ErrorCode[]>> = (() => {
  const index: Record<number, ErrorCode[]> = {};
  for (const code of Object.keys(ERROR_HTTP_STATUS) as ErrorCode[]) {
    const status = ERROR_HTTP_STATUS[code];
    (index[status] ??= []).push(code);
  }
  for (const status of Object.keys(index)) {
    index[Number(status)]?.sort();
  }
  return Object.freeze(index);
})();

/**
 * 框架层出口的默认码（只覆盖契约 `reverse_map_by_http_status` 的 6 个状态）。
 *
 * 用途单一：Fastify 自己产生的 404 / 405 之类**没有业务错误码**，只能按状态挑一个
 * 通用码。这 6 项与 `contracts/errors.json` → `reverse_map_by_http_status` **逐项相等**，
 * 由 `apps/api/tests/errors-contract.test.mjs` 运行时读契约断言 —— 也就是说，这里
 * 虽然是字面量，但它是**被门禁盯住的字面量**，改了立刻红，不会静默漂移。
 *
 * 契约之外的状态（400 / 413 / 415 等）一律回落 `UNKNOWN`，并**原样保留**实际 HTTP
 * 状态（见 `frameworkCodeForHttpStatus`）—— 不把 413 说成 500。
 */
export const FRAMEWORK_BASE_CODE_BY_STATUS: Readonly<Record<number, ErrorCode>> = Object.freeze({
  401: ERROR_CODES.UNAUTHORIZED,
  403: ERROR_CODES.PERMISSION_DENIED,
  404: ERROR_CODES.NOT_FOUND,
  405: ERROR_CODES.METHOD_NOT_ALLOWED,
  409: ERROR_CODES.CONFLICT,
  422: ERROR_CODES.VALIDATION_ERROR,
});

/**
 * 按错误码取 HTTP 状态（表驱动，未知码回落 `UNKNOWN` 的状态而不是硬编码 500）。
 *
 * ⚠️ `DEPENDENCY_MISSING` 虽然在这张表里有值，但它的状态**必须**由 call-site 决定
 * （契约 `http_status_uniform=false`）。因此域错误出口会**优先**采纳错误对象上的
 * 显式 `status`，只有在没有显式状态时才走本函数 —— 「全局兜底」在结构上不存在。
 *
 * @param code 契约错误码。
 * @returns 契约登记的状态码。
 */
export function httpStatusOf(code: ErrorCode): number {
  return httpStatusFor(code);
}

/**
 * 框架层（无业务码）状态 → 默认错误码。
 *
 * @param status 框架层实际状态码。
 * @returns `FRAMEWORK_BASE_CODE_BY_STATUS` 命中项，否则 `UNKNOWN`。
 */
export function frameworkCodeForHttpStatus(status: number): ErrorCode {
  return FRAMEWORK_BASE_CODE_BY_STATUS[status] ?? UNKNOWN_ERROR_CODE;
}

/**
 * 该状态是否在契约的 13 类之内（用于「框架层状态是否可信」的判断与日志）。
 *
 * @param status 待判定状态码。
 */
export function isKnownHttpStatus(status: number): boolean {
  return HTTP_STATUS_CLASSES.includes(status);
}

/**
 * 运行时判定一个值是否是契约错误码（30 个字面值之一）。
 *
 * 刻意不用 `instanceof`：跨包 / 跨 realm 的 `Error` 子类会失效，而契约的约束对象
 * 从来是「码值」，不是「哪个类」。
 *
 * @param value 任意值。
 */
export function isErrorCode(value: unknown): value is ErrorCode {
  return typeof value === "string" && Object.hasOwn(ERROR_HTTP_STATUS, value);
}
