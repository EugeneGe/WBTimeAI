/**
 * T2-07 · 19 个 op 的 **TypeBox schema**（唯一手写处，逐条对齐 `contracts/openapi.v1.frozen.json`）。
 *
 * 为什么集中在一个文件
 * ------------------
 * `packages/contracts` 里**没有** OpenAPI 的 TS 生成物（只有 `domain-refs` +
 * `extension-points`），所以这 19 个 schema 只能手写 —— 这天然是"第二真相源"。
 * 集中摆放让 `apps/api/tests/openapi-alignment.test.mjs` 可以**逐条**比对
 * （operationId / 请求体 required 集合 / 响应属性名集合），漂移立刻红。
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
 * 19 个 op 的字典。键是契约 `operationId`，值与 `01-身份与授权.md §1` 的表逐条对应。
 *
 * **不多不少 19 条** —— 这条由 `openapi-alignment.test.mjs` 断言（多一条 = 加了契约外
 * 端点；少一条 = 漏实现）。`/api/v1/settings/credentials` 的 2 个镜像 op 按 U-3/R-5
 * **不纳入**；Workspace 任何路由按 R-26 **不纳入**。
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
});

/** 19 个 operationId（顺序与 `01-身份与授权.md §1` 的表一致）。 */
export const OPERATION_IDS: readonly string[] = Object.freeze(Object.keys(OPERATION_SCHEMAS));
