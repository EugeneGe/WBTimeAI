/**
 * v0019 · `Run*` 三个契约对象的 **TypeBox schema**（W0 收尾项）。
 *
 * 为什么单独一个文件，而不是塞进 `schemas.ts`
 * ------------------------------------------
 * `schemas.ts` 的抬头写明它只装「**19 个已实现 op** 的 TypeBox」，并由
 * `apps/api/tests/openapi-alignment.test.mjs` 逐 op 比对。本文件装的是 **runs 3 op
 * 尚未实现**（W5 · `T3-08`）的三个对象，提前落地的唯一理由是 v0019 改了它们
 * （`RunResponse.stop_reason` / `RunOut.stop_reason` / `status` 七值枚举），
 * 而 `apps/api/src/routes/schemas.ts` 里 `RunResponse` **0 命中**（施工前置实测 §0.1-#8）。
 * 混进 `schemas.ts` 会让「19 op」这句话立刻失真，故独立成件；W5 落 runs 路由时**直接引用本文件**，
 * 不再二次手抄。
 *
 * 对齐口径
 * --------
 * 逐字段对齐 `contracts/openapi.v1.frozen.v0019.json` 的 `RunRequest` / `RunResponse` /
 * `RunOut` / `ResultOut`：属性名、required 集合、可空性、`status` 七值枚举与默认 `QUEUED`、
 * 三个 `default` 字面量。**`stop_reason` 在契约里是 `string | null`（11 值写在 description）**，
 * 这里同样只约束到 `string | null`，11 值以 `STOP_REASONS` 常量导出，供 W2 的服务层断言
 * （终态必填、非终态 NULL）复用 —— 不在传输层提前收紧，避免与契约产生第二套枚举。
 */

import { Type, type Static } from "@sinclair/typebox";

/** 响应里的 `string | null`。 */
const NullableString = Type.Union([Type.String(), Type.Null()]);

/**
 * 请求体里的可空字符串：**`Null` 必须排在 `String` 前面**。
 * Fastify 的 Ajv 默认 `coerceTypes: true`，`null → ""` 是对 `type:"string"` 的合法强制转换；
 * 写成 `[String, Null]` 会让「显式清空」被悄悄改成空串（同 `schemas.ts` 的既有约定）。
 */
const RequestNullableString = Type.Union([Type.Null(), Type.String()]);

/** 契约 `RunResponse.status` / `RunOut.status` 的七值枚举（v0019 显式化，默认 `QUEUED`）。 */
export const RUN_STATUSES = [
  "QUEUED",
  "RUNNING",
  "WAITING_APPROVAL",
  "WAITING_INPUT",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
] as const;

const RunStatus = Type.Union(
  RUN_STATUSES.map((s) => Type.Literal(s)),
  { default: "QUEUED" }
);

/**
 * `stop_reason` 的 11 值（契约写在 description 里，**不在 schema 的 enum 上**）。
 * 服务层断言（W2）：终态必须命中其一、非终态必须为 `null`。
 */
export const STOP_REASONS = [
  "model_finish",
  "tool_failed",
  "approval_rejected",
  "cancelled",
  "budget_tokens",
  "budget_cost",
  "budget_turns",
  "budget_tools",
  "wall_time",
  "provider_error",
  "unknown_recovery",
] as const;

/** `token_usage`：契约是 `additionalProperties: true` 的开放对象（可选键先例见 V0.3.0 缓存观测）。 */
const OpenObject = Type.Object({}, { additionalProperties: true });

// ---------------------------------------------------------------------------
// RunRequest（`POST /agents/{agent_id}/runs`）
// ---------------------------------------------------------------------------

/** 契约 `RunRequest`：四个字段**全部可选**（`required` 缺失）。 */
export const RunRequestSchema = Type.Object({
  message: Type.Optional(Type.String({ default: "" })),
  conversation_id: Type.Optional(RequestNullableString),
  workspace_id: Type.Optional(RequestNullableString),
  run_mode: Type.Optional(Type.String({ maxLength: 20, default: "INLINE" })),
});
export type RunRequestBody = Static<typeof RunRequestSchema>;

// ---------------------------------------------------------------------------
// RunResponse（`GET /runs/{run_id}` / `POST /runs/{run_id}/cancel`）
// ---------------------------------------------------------------------------

/** 契约 `RunResponse`：required = `id` / `agent_id` / `agent_version_id` / `conversation_id`。
 *  其余字段契约**未列入 required** ⇒ 一律 `Type.Optional`，否则会把合法响应判成非法。 */
export const RunResponseSchema = Type.Object(
  {
    id: Type.String(),
    agent_id: Type.String(),
    agent_version_id: Type.String(),
    conversation_id: Type.String(),
    tenant_id: Type.Optional(NullableString),
    user_id: Type.Optional(NullableString),
    task_id: Type.Optional(NullableString),
    trigger: Type.Optional(Type.String({ default: "user" })),
    run_mode: Type.Optional(Type.String({ default: "INLINE" })),
    status: Type.Optional(RunStatus),
    trace_id: Type.Optional(NullableString),
    started_at: Type.Optional(NullableString),
    completed_at: Type.Optional(NullableString),
    duration_ms: Type.Optional(Type.Union([Type.Integer(), Type.Null()])),
    token_usage: Type.Optional(OpenObject),
    cost: Type.Optional(Type.Union([Type.Number(), Type.Null()])),
    cost_status: Type.Optional(Type.String({ default: "UNPRICED" })),
    success: Type.Optional(Type.Union([Type.Boolean(), Type.Null()])),
    error: Type.Optional(NullableString),
    error_type: Type.Optional(NullableString),
    /** v0019 新增：终态原因（11 值），非终态为 `null`。 */
    stop_reason: Type.Optional(NullableString),
  },
  { additionalProperties: false }
);
export type RunResponseBody = Static<typeof RunResponseSchema>;

// ---------------------------------------------------------------------------
// RunOut / ResultOut（评测视图；`required` 全缺 ⇒ 逐字段可选）
// ---------------------------------------------------------------------------

/** 契约 `ResultOut`：单 case 的评分结果（`required` 全缺 ⇒ 逐字段可选）。 */
export const ResultOutSchema = Type.Object(
  {
    id: Type.Optional(Type.String({ default: "" })),
    case_id: Type.Optional(Type.String({ default: "" })),
    evaluation_run_id: Type.Optional(Type.String({ default: "" })),
    agent_run_id: Type.Optional(NullableString),
    status: Type.Optional(Type.String({ default: "" })),
    score: Type.Optional(Type.Union([Type.Number(), Type.Null()])),
    cost: Type.Optional(Type.Union([Type.Number(), Type.Null()])),
    duration_ms: Type.Optional(Type.Union([Type.Integer(), Type.Null()])),
    error_type: Type.Optional(NullableString),
    token_usage: Type.Optional(Type.Union([OpenObject, Type.Null()])),
    assertion_results: Type.Optional(Type.Union([Type.Array(OpenObject), Type.Null()])),
  },
  { additionalProperties: false }
);
export type ResultOutBody = Static<typeof ResultOutSchema>;

/** 契约 `RunOut`：评测视图（`results` 为逐 case 分数；`required` 全缺 ⇒ 逐字段可选）。 */
export const RunOutSchema = Type.Object(
  {
    id: Type.Optional(Type.String({ default: "" })),
    agent_id: Type.Optional(Type.String({ default: "" })),
    agent_version_id: Type.Optional(Type.String({ default: "" })),
    dataset_id: Type.Optional(Type.String({ default: "" })),
    tenant_id: Type.Optional(NullableString),
    organization_id: Type.Optional(NullableString),
    workspace_id: Type.Optional(NullableString),
    idempotency_key: Type.Optional(NullableString),
    created_by: Type.Optional(NullableString),
    status: Type.Optional(RunStatus),
    started_at: Type.Optional(NullableString),
    completed_at: Type.Optional(NullableString),
    created_at: Type.Optional(NullableString),
    updated_at: Type.Optional(NullableString),
    summary: Type.Optional(Type.Union([OpenObject, Type.Null()])),
    results: Type.Optional(Type.Array(ResultOutSchema)),
    /** v0019 新增：同 `RunResponse.stop_reason`。 */
    stop_reason: Type.Optional(NullableString),
  },
  { additionalProperties: false }
);
export type RunOutBody = Static<typeof RunOutSchema>;
