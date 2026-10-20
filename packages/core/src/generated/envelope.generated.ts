// @generated —— 由 scripts/gen_platform_contracts.mjs 从 contracts/envelope.schema.json 生成。
// 请勿手改。
//
// $id: https://wbtimeai.local/contracts/envelope.schema.json
// 响应壳顶层字段（实测，成功壳 required == 失败壳 required == properties 键集）: 4
// 字段清单: code, data, message, request_id

import { Type } from "@sinclair/typebox";

/** 响应壳的四顶层键：成功壳与失败壳同构（总纲 §11.1「四顶层键恒在」）。 */
export const ENVELOPE_FIELD_NAMES = [
  "code",
  "data",
  "message",
  "request_id",
] as const;

export type EnvelopeFieldName = (typeof ENVELOPE_FIELD_NAMES)[number];

/** 成功壳（code 恒为整数 0，message 恒为 "ok"）。 */
export const OkEnvelopeSchema = Type.Object({
  "code": Type.Literal(0),
  "data": Type.Union([Type.Object({}), Type.Array(Type.Unknown()), Type.String(), Type.Number(), Type.Boolean(), Type.Null()]),
  "message": Type.Literal("ok"),
  "request_id": Type.Union([Type.String(), Type.Null()]),
},
  {
    additionalProperties: false
  });

/** 失败壳（code 为 ErrorCode 字符串字面量，与成功壳的 0 **不同型**）。 */
export const ErrorEnvelopeSchema = Type.Object({
  "code": Type.Union([Type.Literal("UNKNOWN"), Type.Literal("INTERNAL_ERROR"), Type.Literal("VALIDATION_ERROR"), Type.Literal("NOT_FOUND"), Type.Literal("METHOD_NOT_ALLOWED"), Type.Literal("CONFLICT"), Type.Literal("PERMISSION_DENIED"), Type.Literal("UNAUTHORIZED"), Type.Literal("NOT_IMPLEMENTED"), Type.Literal("CONFIGURATION_ERROR"), Type.Literal("DEPENDENCY_MISSING"), Type.Literal("AUTH_INVALID_CREDENTIALS"), Type.Literal("AUTH_TOKEN_EXPIRED"), Type.Literal("AUTH_TOKEN_INVALID"), Type.Literal("AUTH_TOKEN_REVOKED"), Type.Literal("AUTH_ACCOUNT_LOCKED"), Type.Literal("TENANT_NOT_FOUND"), Type.Literal("USER_NOT_FOUND"), Type.Literal("USER_ALREADY_EXISTS"), Type.Literal("ORGANIZATION_NOT_FOUND"), Type.Literal("WORKSPACE_NOT_FOUND"), Type.Literal("TASK_NOT_FOUND"), Type.Literal("CREDENTIAL_NOT_FOUND"), Type.Literal("RESOURCE_LIMIT_EXCEEDED"), Type.Literal("MAX_ITERATIONS"), Type.Literal("CONTEXT_LENGTH_EXCEEDED"), Type.Literal("TOOL_TIMEOUT"), Type.Literal("IDEMPOTENCY_KEY_REUSE"), Type.Literal("HEARTBEAT_TIMEOUT"), Type.Literal("EVENT_CURSOR_EXPIRED")]),
  "data": Type.Record(Type.String(), Type.Unknown()),
  "message": Type.String(),
  "request_id": Type.Union([Type.String(), Type.Null()]),
},
  {
    additionalProperties: false
  });
