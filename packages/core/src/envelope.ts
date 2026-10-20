// @wbtime/core · 统一响应壳 {code, data, message, request_id}（总纲 §11.1）。
//
// 字段集合与类型都来自 contracts/envelope.schema.json，由生成器翻译成 typebox
// schema（见 ./generated/envelope.generated.ts）；这里的 TS 类型一律用
// `Static<typeof ...>` 从 schema 反推，**不手写字段列表**，因此壳字段一改，
// 类型定义会跟着改，而不是静默漂移。

import { Type } from "@sinclair/typebox";
// typebox 0.34 起 `Value` 不再是根导出的成员，改由子路径导出（实测：@sinclair/typebox@0.34.52）。
import { Value } from "@sinclair/typebox/value";
import type { Static } from "@sinclair/typebox";

import {
  ENVELOPE_FIELD_NAMES,
  ErrorEnvelopeSchema,
  OkEnvelopeSchema,
} from "./generated/envelope.generated.js";
import type { ErrorCode } from "./generated/errors.generated.js";

export { ENVELOPE_FIELD_NAMES, ErrorEnvelopeSchema, OkEnvelopeSchema };
export type { EnvelopeFieldName } from "./generated/envelope.generated.js";

/** 成功壳的静态类型（`code` 恒 0、`message` 恒 "ok"）。 */
export type OkEnvelope = Static<typeof OkEnvelopeSchema>;

/** 成功响应：`data` 为裸业务对象（成功壳不套二级 {data}）。 */
export type OkResponse<T = unknown> = Omit<OkEnvelope, "data"> & { data: T };

/** 失败响应：`code` 是 ErrorCode **字符串**，与成功壳的整数 0 不同型。 */
export type ErrorResponse = Static<typeof ErrorEnvelopeSchema>;

/** 响应壳联合。判别必须走 `code` 的类型分支，不得用同一类型表达两种结果。 */
export type Envelope<T = unknown> = OkResponse<T> | ErrorResponse;

export function isOkResponse<T>(value: Envelope<T>): value is OkResponse<T> {
  return value.code === 0;
}

export function isErrorResponse<T>(value: Envelope<T>): value is ErrorResponse {
  return value.code !== 0;
}

/** 构造成功壳。`request_id` 键恒在（值可为 null）。 */
export function okResponse<T>(data: T, requestId: string | null = null): OkResponse<T> {
  return { code: 0, message: "ok", data, request_id: requestId };
}

/** 构造失败壳。`data` 缺省为 `{}`（键恒在）。 */
export function errorResponse(
  code: ErrorCode,
  message: string,
  data: Record<string, unknown> = {},
  requestId: string | null = null,
): ErrorResponse {
  return { code, message, data, request_id: requestId };
}

/** 运行时校验：值是否满足成功壳形状（typebox，非手写 instanceof）。 */
export function isOkEnvelopeShape(value: unknown): value is OkEnvelope {
  return Value.Check(OkEnvelopeSchema, value);
}

/** 运行时校验：值是否满足失败壳形状。 */
export function isErrorEnvelopeShape(value: unknown): value is ErrorResponse {
  return Value.Check(ErrorEnvelopeSchema, value);
}

/**
 * 顶层键集合（运行时可读）。与 `ENVELOPE_FIELD_NAMES` 同源，
 * 供 `scripts/check_platform_parity.py` 与契约逐项比对。
 */
export const ENVELOPE_FIELDS: readonly string[] = ENVELOPE_FIELD_NAMES;

/** typebox 命名空间再导出，便于调用方做自定义校验而不重复依赖。 */
export { Type, Value };
