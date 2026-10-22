/**
 * T2-07 · 身份 19 op 的 TypeBox schema（T3-05 / T3-06 / T3-07 逐族扩充到 **38 op**）；
 * 唯一手写处，逐条对齐 `contracts/openapi.v1.frozen.json`。
 *
 * 为什么集中在一个文件
 * ------------------
 * `packages/contracts` 里**没有** OpenAPI 的 TS 生成物（只有 `domain-refs` +
 * `extension-points`），所以这些 schema 只能手写 —— 这天然是"第二真相源"。
 * 集中摆放让 `apps/api/tests/openapi-alignment.test.mjs` 可以**逐条**比对
 * （operationId / 请求体 required 集合 / 响应属性名集合），漂移立刻红。
 *
 * 🔴 可空键的 `Null` 次序**以真管线实测为准**
 * --------------------------------------------
 * 「`Null` 排在 `String` 前面」这条防护的**依据不是**裸 Ajv 的行为 —— T3-06 §9.4 #11
 * 的独立 probe 实测：裸 `new Ajv({ coerceTypes: true }).compile()` 下两种次序的行为
 * 与 Fastify 真管线**方向相反**（`anyOf` / `union` 的分支选择路径不同）。所以：
 * 任何"我把次序调一下试试"的结论都必须在**真 Fastify 管线**（`buildApp()` +
 * `app.inject()`，如 `routes-skills.test.mjs` B 组）里复验，裸 Ajv 不算证据。
 * 本文件的次序结论全部来自真管线实测，见 {@link NullableString255} 上方注释。
 *
 * 两处**刻意**与契约字面不同（都已登记在 T2-07 施工记录）
 * ---------------------------------------------------
 * 1. `ToolPermissionRequest.action` / `.effect` 的 `maxLength` 取 **20**，契约写 30。
 *    理由：落点列是 `resource_permission.action varchar(20)` / `effect varchar(10)`（DDL 冻结，
 *    不可改）。按 30 放进来，21~30 字符的取值会在 PG 上撞列宽 → **500**；按 20 挡下则是
 *    **422**（用户能看懂、可纠正）。宁可少放行，也不制造 500。`effect` 契约未给 maxLength，
 *    这里按列宽 10 收紧同理。
 * 2. 响应的 `agent_version_id` 恒 `null`：`resource_permission` **没有**这一列
 *    （契约 `ToolPermissionResponse` 有该字段），本版不为此改 DDL（J-1 红线）⇒ 恒 null，
 *    登记为遗留。
 *
 * 响应 schema 一律 `additionalProperties: false`：测试用 `Value.Check` 校验**真实响应**，
 * 多一个键当场红 —— 这比"人肉数键"可靠。
 */

import { Type, type Static, type TSchema } from "@sinclair/typebox";

// `POST /agents/{id}/run` 的请求体复用 v0019 落地的 `RunRequestSchema`（W0 收尾件，
// 单一真相源 —— 不二次手抄；字段对齐由 `schemas-run-v0019.test.mjs` 锁定）。
import { RunRequestSchema, RunResponseSchema } from "./schemas-run.js";

/** `string | null` 的简写（契约里大量 `anyOf: [string, null]`）。 */
const NullableString = Type.Union([Type.String(), Type.Null()]);

/**
 * 请求体里的「可空字符串」：**`Null` 必须排在 `String` 前面**。
 *
 * 这不是风格问题：Fastify 的 Ajv 默认 `coerceTypes: true`，而 `null → ""` 是它对
 * `type: "string"` 的合法强制转换。若写成 `[String, Null]`，客户端传
 * `{"display_name": null}`（想清空）会被**静默改成空串**——语义从"清空"变成"设为空字符串"，
 * 而且前端只能通过"读回来不是 null"才发现。实测踩到过（T2-07 PUT /users/me）。
 * 把 `Null` 放前面，Ajv 先用 `type: null` 分支匹配成功，就不会走到强制转换。
 *
 * ⚠️ 上句的"实测"指**真 Fastify 管线**（`buildApp` + `app.inject`）。T3-06 §9.4 #11
 * 用同样的两次对照 probe 证明：裸 `new Ajv({coerceTypes:true})` 下两序行为与管线
 * **相反** ⇒ 次序结论一律以真管线为准，不复跑裸 Ajv（复跑命令见文件头注）。
 */
const NullableString255 = Type.Union([Type.Null(), Type.String({ maxLength: 255 })]);
const NullableString36 = Type.Union([Type.Null(), Type.String({ maxLength: 36 })]);

// ---------------------------------------------------------------------------
// 公共响应
// ---------------------------------------------------------------------------

/** 契约 `TokenResponse`（**四键恒在**）。 */
export const TokenResponseSchema = Type.Object(
  {
    access_token: Type.String(),
    refresh_token: Type.String(),
    token_type: Type.String(),
    expires_in: Type.Integer(),
  },
  { additionalProperties: false }
);
export type TokenResponseBody = Static<typeof TokenResponseSchema>;

/** 契约 `MessageResponse`（`logout` / `logout-all`）。 */
export const MessageResponseSchema = Type.Object({ message: Type.String() }, { additionalProperties: false });
export type MessageResponseBody = Static<typeof MessageResponseSchema>;

// ---------------------------------------------------------------------------
// 认证族（4 op）
// ---------------------------------------------------------------------------

/** 契约 `RegisterRequest`。 */
export const RegisterRequestSchema = Type.Object({
  username: Type.String({ minLength: 1, maxLength: 150 }),
  email: Type.String({ minLength: 3, maxLength: 320 }),
  password: Type.String({ minLength: 6, maxLength: 256 }),
  display_name: Type.Optional(NullableString255),
});
export type RegisterRequestBody = Static<typeof RegisterRequestSchema>;

/** 契约 `LoginRequest`。 */
export const LoginRequestSchema = Type.Object({
  username: Type.String({ minLength: 1, maxLength: 150 }),
  password: Type.String({ minLength: 1, maxLength: 256 }),
});
export type LoginRequestBody = Static<typeof LoginRequestSchema>;

/** 契约 `RefreshRequest`。 */
export const RefreshRequestSchema = Type.Object({
  refresh_token: Type.String({ minLength: 1 }),
});
export type RefreshRequestBody = Static<typeof RefreshRequestSchema>;

// ---------------------------------------------------------------------------
// 用户族（4 op）
// ---------------------------------------------------------------------------

/** 契约 `UserResponse`。 */
export const UserResponseSchema = Type.Object(
  {
    id: Type.String(),
    username: Type.String(),
    email: Type.String(),
    display_name: NullableString,
    tenant_id: NullableString,
    is_active: Type.Boolean(),
    is_superuser: Type.Boolean(),
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type UserResponseBody = Static<typeof UserResponseSchema>;

/** 契约 `UpdateUserRequest`（唯一字段可空 ⇒ 允许显式清空显示名）。 */
export const UpdateUserRequestSchema = Type.Object({
  display_name: Type.Optional(NullableString255),
});
export type UpdateUserRequestBody = Static<typeof UpdateUserRequestSchema>;

/** 契约 `DeviceResponse`。 */
export const DeviceResponseSchema = Type.Object(
  {
    id: Type.String(),
    device: NullableString,
    ip_address: NullableString,
    user_agent: NullableString,
    created_at: NullableString,
    expires_at: NullableString,
    revoked_at: NullableString,
  },
  { additionalProperties: false }
);
export type DeviceResponseBody = Static<typeof DeviceResponseSchema>;

// ---------------------------------------------------------------------------
// 组织族（2 op）
// ---------------------------------------------------------------------------

/** 契约 `OrganizationResponse`。 */
export const OrganizationResponseSchema = Type.Object(
  {
    id: Type.String(),
    name: Type.String(),
    slug: Type.String(),
    tenant_id: NullableString,
  },
  { additionalProperties: false }
);
export type OrganizationResponseBody = Static<typeof OrganizationResponseSchema>;

// ---------------------------------------------------------------------------
// 权限族（4 op）
// ---------------------------------------------------------------------------

/**
 * `GET /permissions/check` 的 querystring。
 *
 * 为什么用 schema 而不是 handler 里手判：py 侧（FastAPI）缺必填 query 参数时返回的是
 * **框架校验错误**（422 + `data.errors`）。手判只能造出 `{field: "cap"}`，键集合与 py 不同
 * —— J-11 比 `data` 的**键集合**，当场红。交给 Fastify 校验后，错误走统一出口的
 * ② 分支（`{errors: [...]}`），与 py 同形。
 */
export const CheckQuerySchema = Type.Object({ cap: Type.String({ minLength: 1 }) });

/** `GET /tools/permissions` 的 querystring（`agent_id` 必填，同上）。 */
export const ListToolPermissionsQuerySchema = Type.Object({
  agent_id: Type.String({ minLength: 1 }),
});

/** 契约 `PermissionCheckResponse`（J-6a：`capability`/`allowed`/`effect`/`reason` 恒在）。 */
export const PermissionCheckResponseSchema = Type.Object(
  {
    capability: Type.String(),
    allowed: Type.Boolean(),
    effect: Type.String(),
    reason: Type.String(),
    source: NullableString,
  },
  { additionalProperties: false }
);
export type PermissionCheckResponseBody = Static<typeof PermissionCheckResponseSchema>;

/** 契约 `ToolPermissionRequest`（见文件头注 1：maxLength 按列宽收紧）。 */
export const ToolPermissionRequestSchema = Type.Object({
  tool_id: Type.String({ minLength: 1 }),
  action: Type.Optional(Type.String({ maxLength: 20, default: "EXECUTE" })),
  effect: Type.Optional(Type.String({ maxLength: 10, default: "ALLOW" })),
  agent_id: Type.Optional(NullableString36),
  agent_version_id: Type.Optional(NullableString36),
  scope: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
});
export type ToolPermissionRequestBody = Static<typeof ToolPermissionRequestSchema>;

/** 契约 `ToolPermissionResponse`。 */
export const ToolPermissionResponseSchema = Type.Object(
  {
    id: Type.String(),
    tool_id: Type.String(),
    action: Type.String(),
    effect: Type.String(),
    agent_id: NullableString,
    agent_version_id: NullableString,
    scope: Type.Record(Type.String(), Type.Unknown()),
    tenant_id: NullableString,
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type ToolPermissionResponseBody = Static<typeof ToolPermissionResponseSchema>;

// ---------------------------------------------------------------------------
// 模型/凭证族（5 op）
// ---------------------------------------------------------------------------

/** 契约 `SaveCredentialRequest`。 */
export const SaveCredentialRequestSchema = Type.Object({
  provider: Type.String({ minLength: 1, maxLength: 100 }),
  value: Type.String({ minLength: 1 }),
  key_type: Type.Optional(Type.String({ maxLength: 50, default: "api_key" })),
  workspace_id: Type.Optional(NullableString36),
});
export type SaveCredentialRequestBody = Static<typeof SaveCredentialRequestSchema>;

/** 契约 `CredentialResponse`。 */
export const CredentialResponseSchema = Type.Object(
  {
    id: Type.String(),
    provider: Type.String(),
    key_type: Type.String(),
    masked_value: Type.String(),
    created_at: NullableString,
    workspace_id: NullableString,
  },
  { additionalProperties: false }
);
export type CredentialResponseBody = Static<typeof CredentialResponseSchema>;

/** 契约 `ModelProviderResponse`。 */
export const ModelProviderResponseSchema = Type.Object(
  {
    id: Type.String(),
    name: Type.String(),
    type: Type.String(),
    endpoint: NullableString,
    credential_id: NullableString,
    status: Type.String(),
    config: Type.Record(Type.String(), Type.Unknown()),
    created_at: NullableString,
    tenant_id: NullableString,
    workspace_id: NullableString,
  },
  { additionalProperties: false }
);
export type ModelProviderResponseBody = Static<typeof ModelProviderResponseSchema>;

/** 契约 `BindCredentialRequest`。 */
export const BindCredentialRequestSchema = Type.Object({
  credential_id: Type.String({ minLength: 1 }),
});
export type BindCredentialRequestBody = Static<typeof BindCredentialRequestSchema>;

/** 契约 `RegisterProviderRequest`（required = `name` / `provider_type`）。 */
export const RegisterProviderRequestSchema = Type.Object({
  name: Type.String({ minLength: 1, maxLength: 255 }),
  provider_type: Type.String({ minLength: 1, maxLength: 50 }),
  endpoint: Type.Optional(NullableString),
  credential_id: Type.Optional(NullableString36),
  config: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  workspace_id: Type.Optional(NullableString36),
});
export type RegisterProviderRequestBody = Static<typeof RegisterProviderRequestSchema>;

/**
 * 契约 `ModelResponse`（9 键）。
 *
 * `tenant_id` / `created_at` **恒 `null`**：`model` 表只有 `id / provider_id / name /
 * type / context_window / capabilities / status` 七列（实测 `schema/pg/model.ts:77`），
 * 没有这两列。契约里两者都可空 ⇒ 不为此改 DDL（J-1 红线），登记为已知差异。
 */
export const ModelResponseSchema = Type.Object(
  {
    id: Type.String(),
    tenant_id: NullableString,
    provider_id: Type.String(),
    name: Type.String(),
    type: Type.String(),
    context_window: Type.Union([Type.Integer(), Type.Null()]),
    capabilities: Type.Record(Type.String(), Type.Unknown()),
    status: Type.String(),
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type ModelResponseBody = Static<typeof ModelResponseSchema>;

/** 契约 `RegisterModelRequest`（required = `name`；`model_type` default `CHAT`）。 */
export const RegisterModelRequestSchema = Type.Object({
  name: Type.String({ minLength: 1, maxLength: 255 }),
  model_type: Type.Optional(Type.String({ maxLength: 30, default: "CHAT" })),
  context_window: Type.Optional(Type.Union([Type.Integer(), Type.Null()])),
  capabilities: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
});
export type RegisterModelRequestBody = Static<typeof RegisterModelRequestSchema>;

// ---------------------------------------------------------------------------
// 审批族（T3-12 · 4 op）
// ---------------------------------------------------------------------------

/**
 * 契约 `ApprovalResponse`（12 键，required 仅 `id`）。
 *
 * `subject_type` / `subject_ref` / `status` 契约都给了 `default` 且非必填 ⇒
 * 列 NOT NULL 时按原值出；列若为 `null` 则回落空串（py `str(... or "")` 同口径）。
 */
export const ApprovalResponseSchema = Type.Object(
  {
    id: Type.String(),
    tenant_id: NullableString,
    subject_type: Type.String(),
    subject_ref: Type.String(),
    requested_by: NullableString,
    status: Type.String(),
    decided_by: NullableString,
    decided_at: NullableString,
    payload: Type.Record(Type.String(), Type.Unknown()),
    expires_at: NullableString,
    created_at: NullableString,
    updated_at: NullableString,
  },
  { additionalProperties: false }
);
export type ApprovalResponseBody = Static<typeof ApprovalResponseSchema>;

// ---------------------------------------------------------------------------
// 工具目录族（T3-12 · 1 op）
// ---------------------------------------------------------------------------

/** 契约 `ToolResponse`（8 键，required 仅 `name`；`type` default `builtin`）。 */
export const ToolResponseSchema = Type.Object(
  {
    id: NullableString,
    name: Type.String(),
    display_name: Type.String(),
    description: Type.String(),
    category: Type.String(),
    type: Type.String(),
    requires_sandbox: Type.Boolean(),
    input_schema: Type.Record(Type.String(), Type.Unknown()),
  },
  { additionalProperties: false }
);
export type ToolResponseBody = Static<typeof ToolResponseSchema>;

// ---------------------------------------------------------------------------
// MCP 族（T3-11 · 8 op）
// ---------------------------------------------------------------------------

/** 契约 `RegisterMCPServerRequest`（required 仅 `name`；`transport` default `stdio`）。 */
export const RegisterMcpServerRequestSchema = Type.Object({
  name: Type.String({ minLength: 1, maxLength: 255 }),
  transport: Type.Optional(Type.String({ default: "stdio" })),
  command: Type.Optional(NullableString),
  args: Type.Optional(Type.Array(Type.String())),
  endpoint: Type.Optional(NullableString),
  credential_id: Type.Optional(NullableString36),
  env_ref: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  workspace_id: Type.Optional(NullableString36),
});
export type RegisterMcpServerRequestBody = Static<typeof RegisterMcpServerRequestSchema>;

/** 契约 `MCPServerResponse`（12 键；`args` 非可空 ⇒ 列值 null 回落 `[]`）。 */
export const McpServerResponseSchema = Type.Object(
  {
    id: Type.String(),
    name: Type.String(),
    transport: Type.String(),
    command: NullableString,
    args: Type.Array(Type.String()),
    endpoint: NullableString,
    credential_id: NullableString,
    env_ref: Type.Union([Type.Record(Type.String(), Type.Unknown()), Type.Null()]),
    status: Type.String(),
    workspace_id: NullableString,
    tenant_id: NullableString,
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type McpServerResponseBody = Static<typeof McpServerResponseSchema>;

/** 契约 `MCPToolResponse`（8 键）。 */
export const McpToolResponseSchema = Type.Object(
  {
    id: Type.String(),
    mcp_server_id: Type.String(),
    name: Type.String(),
    description: NullableString,
    input_schema: Type.Record(Type.String(), Type.Unknown()),
    output_schema: Type.Union([Type.Record(Type.String(), Type.Unknown()), Type.Null()]),
    status: Type.String(),
    discovered_at: NullableString,
  },
  { additionalProperties: false }
);
export type McpToolResponseBody = Static<typeof McpToolResponseSchema>;

/** 契约 `CreateMCPPermissionRequest`（required 仅 `mcp_tool_id`）。 */
export const CreateMcpPermissionRequestSchema = Type.Object({
  mcp_tool_id: Type.String({ minLength: 1 }),
  agent_id: Type.Optional(NullableString36),
  agent_version_id: Type.Optional(NullableString36),
  action: Type.Optional(Type.String({ default: "EXECUTE" })),
  effect: Type.Optional(Type.String({ default: "DENY" })),
  scope: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
});
export type CreateMcpPermissionRequestBody = Static<typeof CreateMcpPermissionRequestSchema>;

/** 契约 `MCPPermissionResponse`（9 键）。 */
export const McpPermissionResponseSchema = Type.Object(
  {
    id: Type.String(),
    mcp_tool_id: Type.String(),
    agent_id: NullableString,
    agent_version_id: NullableString,
    action: Type.String(),
    effect: Type.String(),
    scope: Type.Union([Type.Record(Type.String(), Type.Unknown()), Type.Null()]),
    tenant_id: NullableString,
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type McpPermissionResponseBody = Static<typeof McpPermissionResponseSchema>;

// ---------------------------------------------------------------------------
// Agent 族（T3-05 · 7 op）
// ---------------------------------------------------------------------------

/** 契约 `AgentResponse`（10 键；`status` default DRAFT / `type` default PRIMARY）。 */
export const AgentResponseSchema = Type.Object(
  {
    id: Type.String(),
    tenant_id: NullableString,
    name: Type.String(),
    workspace_id: NullableString,
    description: NullableString,
    type: Type.String(),
    status: Type.String(),
    current_version_id: NullableString,
    created_by: Type.String(),
    created_at: NullableString,
    updated_at: NullableString,
  },
  { additionalProperties: false }
);
export type AgentResponseBody = Static<typeof AgentResponseSchema>;

/** 契约 `CreateAgentRequest`（required = `name`；`type` default PRIMARY）。 */
export const CreateAgentRequestSchema = Type.Object({
  name: Type.String({ minLength: 1, maxLength: 255 }),
  description: Type.Optional(NullableString),
  type: Type.Optional(Type.String({ maxLength: 50, default: "PRIMARY" })),
  workspace_id: Type.Optional(NullableString36),
});
export type CreateAgentRequestBody = Static<typeof CreateAgentRequestSchema>;

/** 契约 `UpdateAgentRequest`（缺省字段不变；`status` 走服务层状态机，见 routes/agents.ts）。 */
export const UpdateAgentRequestSchema = Type.Object({
  name: Type.Optional(Type.Union([Type.Null(), Type.String({ maxLength: 255 })])),
  description: Type.Optional(NullableString),
  status: Type.Optional(Type.Union([Type.Null(), Type.String({ maxLength: 50 })])),
});
export type UpdateAgentRequestBody = Static<typeof UpdateAgentRequestSchema>;

/**
 * 契约 `AgentVersionResponse`（9 键；`model_config` / `runtime_config` 开放对象，
 * `status` default PUBLISHED —— 一次发布 = 一个新行）。
 */
export const AgentVersionResponseSchema = Type.Object(
  {
    id: Type.String(),
    agent_id: Type.String(),
    version: Type.String(),
    system_prompt: Type.String(),
    model_config: Type.Object({}, { additionalProperties: true }),
    runtime_config: Type.Object({}, { additionalProperties: true }),
    status: Type.String(),
    created_by: Type.String(),
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type AgentVersionResponseBody = Static<typeof AgentVersionResponseSchema>;

/**
 * 契约 `PublishRequest`（无 required 字段 —— 实测契约；`version` 可空）。
 *
 * ⚠️ `tools`（`AgentToolBind[]`）收下不落库：`agent_tool` 承接归后续接线
 * （§13.8.7 挂账 #7），schema 仍须逐键对齐契约（对齐测试按属性名集合比对）。
 */
export const PublishRequestSchema = Type.Object({
  system_prompt: Type.Optional(Type.String({ default: "" })),
  model_config: Type.Optional(Type.Object({}, { additionalProperties: true })),
  runtime_config: Type.Optional(Type.Object({}, { additionalProperties: true })),
  version: Type.Optional(Type.Union([Type.Null(), Type.String()])),
  tools: Type.Optional(Type.Array(Type.Object({ tool_id: Type.String() }, { additionalProperties: true }))),
});
export type PublishRequestBody = Static<typeof PublishRequestSchema>;

/**
 * `POST /agents/{id}/run` 的成功响应（T3-05：**入口回执**，非 `RunResponse`）。
 *
 * 契约该 200 的 schema 是**空对象** `{}`（ unconstrained）—— 对齐测试按"属性名
 * 集合"比对，这里也必须是**无属性**的对象 schema，否则 `openapi-alignment` 红。
 * 回执的真实形状（`agent_id` / `harness` / `execution` 等）见
 * `modules/agent/service.ts` 的 `RunEntryReceipt`；T3-08 落执行后整体替换。
 */
export const AgentRunEntryResponseSchema = Type.Object({}, { additionalProperties: true });

// ---------------------------------------------------------------------------
// Skill 族（T3-06 · 7 op）
// ---------------------------------------------------------------------------

/** 契约 `SkillResponse`（**11 键**，无 `updated_at`；`current_version` 恒 null —— py 同形）。 */
export const SkillResponseSchema = Type.Object(
  {
    id: Type.String(),
    tenant_id: NullableString,
    name: Type.String(),
    display_name: Type.String(),
    description: NullableString,
    category: Type.String(),
    status: Type.String(),
    current_version_id: NullableString,
    current_version: NullableString,
    created_by: Type.String(),
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type SkillResponseBody = Static<typeof SkillResponseSchema>;

/** 契约 `CreateSkillRequest`（required = `name`，maxLength 64；`display_name` 缺省回落 name —— 服务层 py 口径）。 */
export const CreateSkillRequestSchema = Type.Object({
  name: Type.String({ minLength: 1, maxLength: 64 }),
  display_name: Type.Optional(Type.String({ maxLength: 255, default: "" })),
  description: Type.Optional(NullableString),
  category: Type.Optional(Type.String({ maxLength: 100, default: "" })),
});
export type CreateSkillRequestBody = Static<typeof CreateSkillRequestSchema>;

/**
 * 契约 `UpdateSkillRequest`（缺省字段不变；**显式 null = 不变** —— py `is not None` 同口径）。
 *
 * 可空键全部用 **Null 在前** 的联合（见文件头注的 Ajv 强转说明）：若写成
 * `[String, Null]`，显式 `null` 会被静默改成 `""`，"不变"就变成了"清空"。
 */
export const UpdateSkillRequestSchema = Type.Object({
  display_name: Type.Optional(Type.Union([Type.Null(), Type.String({ maxLength: 255 })])),
  description: Type.Optional(Type.Union([Type.Null(), Type.String()])),
  category: Type.Optional(Type.Union([Type.Null(), Type.String({ maxLength: 100 })])),
  status: Type.Optional(Type.Union([Type.Null(), Type.String()])),
});
export type UpdateSkillRequestBody = Static<typeof UpdateSkillRequestSchema>;

/** 契约 `SkillVersionResponse`（**8 键**；`manifest` 开放对象 —— 版本清单是自由 JSON）。 */
export const SkillVersionResponseSchema = Type.Object(
  {
    id: Type.String(),
    skill_id: Type.String(),
    version: Type.String(),
    instructions: Type.String(),
    manifest: Type.Object({}, { additionalProperties: true }),
    status: Type.String(),
    created_by: Type.String(),
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type SkillVersionResponseBody = Static<typeof SkillVersionResponseSchema>;

/** 契约 `CreateSkillVersionRequest`（required = `version`；`manifest` 自由对象，py `default_factory=dict`）。 */
export const CreateSkillVersionRequestSchema = Type.Object({
  version: Type.String({ minLength: 1, maxLength: 50 }),
  instructions: Type.Optional(Type.String({ default: "" })),
  manifest: Type.Optional(Type.Object({}, { additionalProperties: true })),
});
export type CreateSkillVersionRequestBody = Static<typeof CreateSkillVersionRequestSchema>;

// ---------------------------------------------------------------------------
// Conversation 族（T3-07 · 5 op）
// ---------------------------------------------------------------------------

/**
 * 契约 `ConversationResponse`（**9 键**）。
 *
 * ⚠️ `workspace_id` / `agent_id` / `user_id` / `title` / `status` 在契约里是
 * `type: string` + `default`（**不是** `anyOf: [string, null]`）—— 只有 `tenant_id`
 * 与两个时间戳可空。视图层因此对列值为 null 的字符串键回落 `""`（`py` 的
 * `_to_conversation_response` 用 `str(getattr(..., ""))` 同形），不许发 null。
 */
export const ConversationResponseSchema = Type.Object(
  {
    id: Type.String(),
    tenant_id: NullableString,
    workspace_id: Type.String(),
    agent_id: Type.String(),
    user_id: Type.String(),
    title: Type.String(),
    status: Type.String(),
    created_at: NullableString,
    updated_at: NullableString,
  },
  { additionalProperties: false }
);
export type ConversationResponseBody = Static<typeof ConversationResponseSchema>;

/**
 * 契约 `ConversationMessageResponse`（**8 键**）。
 *
 * `content_parts` 契约是 `type: array` / `items: {}`（**非可空**）⇒ 列值为 null 时
 * 视图回落 `[]`（py `list(... or [])` 同口径）；`token_count` 是 `integer | null`
 * （"未统计"与"统计为 0"必须可分）。
 */
export const ConversationMessageResponseSchema = Type.Object(
  {
    id: Type.String(),
    conversation_id: Type.String(),
    run_id: NullableString,
    role: Type.String(),
    content: Type.String(),
    content_parts: Type.Array(Type.Unknown()),
    token_count: Type.Union([Type.Integer(), Type.Null()]),
    created_at: NullableString,
  },
  { additionalProperties: false }
);
export type ConversationMessageResponseBody = Static<typeof ConversationMessageResponseSchema>;

/**
 * 契约 `CreateConversationRequest`（required = `agent_id`）。
 *
 * `workspace_id` 契约给了 `default: ""` 且**不在** `required` 里 ⇒ schema 必须放行缺失，
 * 由服务层挡成 422（py `create_conversation` 的唯一守卫点）；在 schema 层加 minLength
 * 会把错误 `data` 形状改成 `{errors:[...]}`，与 py 的 `{field:workspace_id}` 不一致。
 */
export const CreateConversationRequestSchema = Type.Object({
  agent_id: Type.String({ minLength: 1 }),
  title: Type.Optional(Type.String({ maxLength: 255, default: "" })),
  workspace_id: Type.Optional(Type.String({ default: "" })),
});
export type CreateConversationRequestBody = Static<typeof CreateConversationRequestSchema>;

/** 契约 `UpdateConversationRequest`（required = `title`，`minLength: 1` / `maxLength: 255`）。 */
export const UpdateConversationRequestSchema = Type.Object({
  title: Type.String({ minLength: 1, maxLength: 255 }),
});
export type UpdateConversationRequestBody = Static<typeof UpdateConversationRequestSchema>;

// ---------------------------------------------------------------------------
// op → schema 映射（键 = 契约的 operationId，**逐字**）
// ---------------------------------------------------------------------------

/** 一个 op 的 schema 组：请求体（无则 `undefined`）+ 响应体。 */
export interface OperationSchemas {
  readonly method: "GET" | "POST" | "PUT" | "DELETE";
  readonly path: string;
  /** 成功状态码（201 / 200 / 204）。 */
  readonly successStatus: 200 | 201 | 204;
  readonly body?: TSchema;
  /** 成功响应体 schema；204 用 {@link EmptyBodySchema}（零字节体）。 */
  readonly response: TSchema;
}

/** 204 的"响应体"：零字节。用 `Type.Null()` 占位，测试据 `successStatus === 204` 走空体断言。 */
export const EmptyBodySchema = Type.Null();

/**
 * 全部 op 的字典。键是契约 `operationId`，值与各任务卡 §1/§2 的表逐条对应。
 *
 * **身份 19 op（T2-07）+ Agent 7 op（T3-05）+ Skill 7 op（T3-06）+ Conversation 5 op（T3-07）
 * = 38 条** —— 条数由 `openapi-alignment.test.mjs` 断言（多一条 = 加了契约外端点；
 * 少一条 = 漏实现）。`/api/v1/settings/credentials` 的 2 个镜像 op 按 U-3/R-5 **不纳入**；
 * Workspace 任何路由按 R-26 **不纳入**。
 */
export const OPERATION_SCHEMAS: Readonly<Record<string, OperationSchemas>> = Object.freeze({
  // ---- 认证族 -------------------------------------------------------------
  register_api_v1_auth_register_post: {
    method: "POST",
    path: "/api/v1/auth/register",
    successStatus: 201,
    body: RegisterRequestSchema,
    response: TokenResponseSchema,
  },
  login_api_v1_auth_login_post: {
    method: "POST",
    path: "/api/v1/auth/login",
    successStatus: 200,
    body: LoginRequestSchema,
    response: TokenResponseSchema,
  },
  refresh_api_v1_auth_refresh_post: {
    method: "POST",
    path: "/api/v1/auth/refresh",
    successStatus: 200,
    body: RefreshRequestSchema,
    response: TokenResponseSchema,
  },
  logout_api_v1_auth_logout_post: {
    method: "POST",
    path: "/api/v1/auth/logout",
    successStatus: 200,
    response: MessageResponseSchema,
  },

  // ---- 用户族 -------------------------------------------------------------
  read_me_api_v1_users_me_get: {
    method: "GET",
    path: "/api/v1/users/me",
    successStatus: 200,
    response: UserResponseSchema,
  },
  update_me_api_v1_users_me_put: {
    method: "PUT",
    path: "/api/v1/users/me",
    successStatus: 200,
    body: UpdateUserRequestSchema,
    response: UserResponseSchema,
  },
  list_devices_api_v1_users_me_devices_get: {
    method: "GET",
    path: "/api/v1/users/me/devices",
    successStatus: 200,
    response: Type.Array(DeviceResponseSchema),
  },
  logout_all_api_v1_users_me_logout_all_post: {
    method: "POST",
    path: "/api/v1/users/me/logout-all",
    successStatus: 200,
    response: MessageResponseSchema,
  },

  // ---- 组织族 -------------------------------------------------------------
  list_organizations_api_v1_organizations_get: {
    method: "GET",
    path: "/api/v1/organizations",
    successStatus: 200,
    response: Type.Array(OrganizationResponseSchema),
  },
  // operationId 里带双下划线是 FastAPI 对 `{organization_id}` 的既定拼法（逐字照抄，不要"美化"）
  get_organization_api_v1_organizations__organization_id__get: {
    method: "GET",
    path: "/api/v1/organizations/{organization_id}",
    successStatus: 200,
    response: OrganizationResponseSchema,
  },

  // ---- 权限族 -------------------------------------------------------------
  check_capability_api_v1_permissions_check_get: {
    method: "GET",
    path: "/api/v1/permissions/check",
    successStatus: 200,
    response: PermissionCheckResponseSchema,
  },
  list_permissions_api_v1_tools_permissions_get: {
    method: "GET",
    path: "/api/v1/tools/permissions",
    successStatus: 200,
    response: Type.Array(ToolPermissionResponseSchema),
  },
  grant_permission_api_v1_tools_permissions_post: {
    method: "POST",
    path: "/api/v1/tools/permissions",
    successStatus: 201,
    body: ToolPermissionRequestSchema,
    response: ToolPermissionResponseSchema,
  },
  revoke_permission_api_v1_tools_permissions__permission_id__delete: {
    method: "DELETE",
    path: "/api/v1/tools/permissions/{permission_id}",
    successStatus: 204,
    response: EmptyBodySchema,
  },

  // ---- 模型/凭证族 --------------------------------------------------------
  list_credentials_api_v1_models_credentials_get: {
    method: "GET",
    path: "/api/v1/models/credentials",
    successStatus: 200,
    response: Type.Array(CredentialResponseSchema),
  },
  save_credential_api_v1_models_credentials_post: {
    method: "POST",
    path: "/api/v1/models/credentials",
    successStatus: 201,
    body: SaveCredentialRequestSchema,
    response: CredentialResponseSchema,
  },
  delete_credential_api_v1_models_credentials__credential_id__delete: {
    method: "DELETE",
    path: "/api/v1/models/credentials/{credential_id}",
    successStatus: 204,
    response: EmptyBodySchema,
  },
  bind_credential_api_v1_models_providers__provider_id__credential_post: {
    method: "POST",
    path: "/api/v1/models/providers/{provider_id}/credential",
    successStatus: 200,
    body: BindCredentialRequestSchema,
    response: ModelProviderResponseSchema,
  },
  unbind_credential_api_v1_models_providers__provider_id__credential_delete: {
    method: "DELETE",
    path: "/api/v1/models/providers/{provider_id}/credential",
    successStatus: 200,
    response: ModelProviderResponseSchema,
  },

  // ---- Agent 族（T3-05 · 7 op）--------------------------------------------
  list_agents_api_v1_agents_get: {
    method: "GET",
    path: "/api/v1/agents",
    successStatus: 200,
    response: Type.Array(AgentResponseSchema),
  },
  create_agent_api_v1_agents_post: {
    method: "POST",
    path: "/api/v1/agents",
    successStatus: 201,
    body: CreateAgentRequestSchema,
    response: AgentResponseSchema,
  },
  get_agent_api_v1_agents__agent_id__get: {
    method: "GET",
    path: "/api/v1/agents/{agent_id}",
    successStatus: 200,
    response: AgentResponseSchema,
  },
  update_agent_api_v1_agents__agent_id__put: {
    method: "PUT",
    path: "/api/v1/agents/{agent_id}",
    successStatus: 200,
    body: UpdateAgentRequestSchema,
    response: AgentResponseSchema,
  },
  publish_agent_api_v1_agents__agent_id__publish_post: {
    method: "POST",
    path: "/api/v1/agents/{agent_id}/publish",
    successStatus: 201,
    body: PublishRequestSchema,
    response: AgentVersionResponseSchema,
  },
  run_agent_api_v1_agents__agent_id__run_post: {
    method: "POST",
    path: "/api/v1/agents/{agent_id}/run",
    successStatus: 200,
    body: RunRequestSchema,
    response: AgentRunEntryResponseSchema,
  },
  list_versions_api_v1_agents__agent_id__versions_get: {
    method: "GET",
    path: "/api/v1/agents/{agent_id}/versions",
    successStatus: 200,
    response: Type.Array(AgentVersionResponseSchema),
  },

  // ---- Skill 族（T3-06 · 7 op）--------------------------------------------
  list_skills_api_v1_skills_get: {
    method: "GET",
    path: "/api/v1/skills",
    successStatus: 200,
    response: Type.Array(SkillResponseSchema),
  },
  create_skill_api_v1_skills_post: {
    method: "POST",
    path: "/api/v1/skills",
    successStatus: 201,
    body: CreateSkillRequestSchema,
    response: SkillResponseSchema,
  },
  get_skill_api_v1_skills__skill_id__get: {
    method: "GET",
    path: "/api/v1/skills/{skill_id}",
    successStatus: 200,
    response: SkillResponseSchema,
  },
  update_skill_api_v1_skills__skill_id__put: {
    method: "PUT",
    path: "/api/v1/skills/{skill_id}",
    successStatus: 200,
    body: UpdateSkillRequestSchema,
    response: SkillResponseSchema,
  },
  publish_skill_version_api_v1_skills__skill_id__publish_post: {
    method: "POST",
    path: "/api/v1/skills/{skill_id}/publish",
    successStatus: 200,
    response: SkillVersionResponseSchema,
  },
  list_skill_versions_api_v1_skills__skill_id__versions_get: {
    method: "GET",
    path: "/api/v1/skills/{skill_id}/versions",
    successStatus: 200,
    response: Type.Array(SkillVersionResponseSchema),
  },
  create_skill_version_api_v1_skills__skill_id__versions_post: {
    method: "POST",
    path: "/api/v1/skills/{skill_id}/versions",
    successStatus: 201,
    body: CreateSkillVersionRequestSchema,
    response: SkillVersionResponseSchema,
  },

  // ---- Conversation 族（T3-07 · 5 op）--------------------------------------
  // ⚠️ 两条列表 op 的契约 `parameters` 都是空数组（实测）⇒ 这里也**不许**出现
  //    page / page_size / limit / offset（`routes-invariants` 的守恒断言比 (method,path)，
  //    分页参数属契约外扩展，`routes-conversations.test.mjs` 的 E 组另有正面断言）。
  list_conversations_api_v1_conversations_get: {
    method: "GET",
    path: "/api/v1/conversations",
    successStatus: 200,
    response: Type.Array(ConversationResponseSchema),
  },
  create_conversation_api_v1_conversations_post: {
    method: "POST",
    path: "/api/v1/conversations",
    successStatus: 201,
    body: CreateConversationRequestSchema,
    response: ConversationResponseSchema,
  },
  get_conversation_api_v1_conversations__conversation_id__get: {
    method: "GET",
    path: "/api/v1/conversations/{conversation_id}",
    successStatus: 200,
    response: ConversationResponseSchema,
  },
  update_conversation_api_v1_conversations__conversation_id__put: {
    method: "PUT",
    path: "/api/v1/conversations/{conversation_id}",
    successStatus: 200,
    body: UpdateConversationRequestSchema,
    response: ConversationResponseSchema,
  },
  list_messages_api_v1_conversations__conversation_id__messages_get: {
    method: "GET",
    path: "/api/v1/conversations/{conversation_id}/messages",
    successStatus: 200,
    response: Type.Array(ConversationMessageResponseSchema),
  },

  // ---- 审批族（T3-12 · 4 op）------------------------------------------------
  // ⚠️ `GET /approvals` 是**唯一**带 query 分页参数的列表 op（`limit` 1..200 缺省 50、
  //    `offset` ≥0 缺省 0，契约实测）。本映射只记 method/path/成功码/响应形状；
  //    查询参数由路由层的 TypeBox `querystring` schema 校验（见 `routes/approvals.ts`）。
  list_approvals_api_v1_approvals_get: {
    method: "GET",
    path: "/api/v1/approvals",
    successStatus: 200,
    response: Type.Array(ApprovalResponseSchema),
  },
  get_approval_api_v1_approvals__approval_id__get: {
    method: "GET",
    path: "/api/v1/approvals/{approval_id}",
    successStatus: 200,
    response: ApprovalResponseSchema,
  },
  approve_approval_api_v1_approvals__approval_id__approve_post: {
    method: "POST",
    path: "/api/v1/approvals/{approval_id}/approve",
    successStatus: 200,
    response: ApprovalResponseSchema,
  },
  reject_approval_api_v1_approvals__approval_id__reject_post: {
    method: "POST",
    path: "/api/v1/approvals/{approval_id}/reject",
    successStatus: 200,
    response: ApprovalResponseSchema,
  },

  // ---- 模型目录族（T3-12 · 6 op，补 T2-07 的 5 op）---------------------------
  list_providers_api_v1_models_providers_get: {
    method: "GET",
    path: "/api/v1/models/providers",
    successStatus: 200,
    response: Type.Array(ModelProviderResponseSchema),
  },
  register_provider_api_v1_models_providers_post: {
    method: "POST",
    path: "/api/v1/models/providers",
    successStatus: 201,
    body: RegisterProviderRequestSchema,
    response: ModelProviderResponseSchema,
  },
  get_provider_api_v1_models_providers__provider_id__get: {
    method: "GET",
    path: "/api/v1/models/providers/{provider_id}",
    successStatus: 200,
    response: ModelProviderResponseSchema,
  },
  disable_provider_api_v1_models_providers__provider_id__delete: {
    method: "DELETE",
    path: "/api/v1/models/providers/{provider_id}",
    // **200 而不是 204**：软删（`status = DISABLED`）且回整行 —— 这条成功码就是
    // "删除其实是禁用"的证据，见 `model-provider-repo.ts::disable` 的注释。
    successStatus: 200,
    response: ModelProviderResponseSchema,
  },
  list_models_api_v1_models_providers__provider_id__models_get: {
    method: "GET",
    path: "/api/v1/models/providers/{provider_id}/models",
    successStatus: 200,
    response: Type.Array(ModelResponseSchema),
  },
  register_model_api_v1_models_providers__provider_id__models_post: {
    method: "POST",
    path: "/api/v1/models/providers/{provider_id}/models",
    successStatus: 201,
    body: RegisterModelRequestSchema,
    response: ModelResponseSchema,
  },

  // ---- 工具目录族（T3-12 · 1 op）-------------------------------------------
  list_tools_api_v1_tools_get: {
    method: "GET",
    path: "/api/v1/tools",
    successStatus: 200,
    response: Type.Array(ToolResponseSchema),
  },

  // ---- runs 族（T3-08 · 3 op）----------------------------------------------
  // ⚠️ 响应 schema **直接引用** `schemas-run.ts` 的 `RunResponseSchema`（v0019 口径，
  //    比 v0018 多 `stop_reason`）—— 那个文件的头注就是为"W5 落 runs 路由时直接引用"写的。
  get_run_api_v1_runs__run_id__get: {
    method: "GET",
    path: "/api/v1/runs/{run_id}",
    successStatus: 200,
    response: RunResponseSchema,
  },
  cancel_run_api_v1_runs__run_id__cancel_post: {
    method: "POST",
    path: "/api/v1/runs/{run_id}/cancel",
    // 契约回 200 + 整行（**不是 204**）：取消不删行，只改状态。
    successStatus: 200,
    response: RunResponseSchema,
  },
  list_run_events_api_v1_runs__run_id__events_get: {
    method: "GET",
    path: "/api/v1/runs/{run_id}/events",
    successStatus: 200,
    // 契约该 op 的 200 响应体是**空 schema `{}`**（SSE 不是 JSON）⇒ 这里给一个零属性的
    // 开放对象，只为让"属性名集合相等"这条判据有东西可比；真正的响应体是字节流，
    // 由 `routes/runs.ts` 的 `reply.raw` 写出，**不经过** Fastify 序列化。
    response: Type.Object({}, { additionalProperties: true }),
  },

  // ---- MCP 族（T3-11 · 8 op）-----------------------------------------------
  list_servers_api_v1_mcp_servers_get: {
    method: "GET",
    path: "/api/v1/mcp/servers",
    successStatus: 200,
    response: Type.Array(McpServerResponseSchema),
  },
  register_server_api_v1_mcp_servers_post: {
    method: "POST",
    path: "/api/v1/mcp/servers",
    successStatus: 201,
    body: RegisterMcpServerRequestSchema,
    response: McpServerResponseSchema,
  },
  get_server_api_v1_mcp_servers__server_id__get: {
    method: "GET",
    path: "/api/v1/mcp/servers/{server_id}",
    successStatus: 200,
    response: McpServerResponseSchema,
  },
  delete_server_api_v1_mcp_servers__server_id__delete: {
    method: "DELETE",
    path: "/api/v1/mcp/servers/{server_id}",
    // **204 零字节**（真删行）—— 与 `DELETE /models/providers/{id}`（软删 200）不同形。
    successStatus: 204,
    response: EmptyBodySchema,
  },
  discover_tools_api_v1_mcp_servers__server_id__discover_post: {
    method: "POST",
    path: "/api/v1/mcp/servers/{server_id}/discover",
    successStatus: 200,
    response: Type.Array(McpToolResponseSchema),
  },
  list_tools_api_v1_mcp_tools_get: {
    method: "GET",
    path: "/api/v1/mcp/tools",
    successStatus: 200,
    response: Type.Array(McpToolResponseSchema),
  },
  list_permissions_api_v1_mcp_permissions_get: {
    method: "GET",
    path: "/api/v1/mcp/permissions",
    successStatus: 200,
    response: Type.Array(McpPermissionResponseSchema),
  },
  create_permission_api_v1_mcp_permissions_post: {
    method: "POST",
    path: "/api/v1/mcp/permissions",
    successStatus: 201,
    body: CreateMcpPermissionRequestSchema,
    response: McpPermissionResponseSchema,
  },
});

/** 全部 operationId（顺序：身份 19 op，Agent 7 / Skill 7（§2 W3 卡），Conversation 5（W4 卡））。 */
export const OPERATION_IDS: readonly string[] = Object.freeze(Object.keys(OPERATION_SCHEMAS));
