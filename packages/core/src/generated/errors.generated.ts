// @generated —— 由 scripts/gen_platform_contracts.mjs 从 contracts/errors.json 生成。
// 请勿手改：改契约后重跑 `node scripts/gen_platform_contracts.mjs`。
//
// contract_version: 3
// codes_digest_sha256: 76b4524d30677a4fcf9287a7f3f087e5db34a378aeb581d99eef8e1268f306d4
// 错误码数量（实测，以读取为准）: 30
// HTTP 状态来源: 逐码取 codes[*].http_status（字段在契约内，非推导、非编造）。

/** 全部错误码字面量集合（键 == 值，便于 `ErrorCode.X` 与字面量双向对齐）。 */
export const ERROR_CODES = {
  AUTH_ACCOUNT_LOCKED: "AUTH_ACCOUNT_LOCKED",
  AUTH_INVALID_CREDENTIALS: "AUTH_INVALID_CREDENTIALS",
  AUTH_TOKEN_EXPIRED: "AUTH_TOKEN_EXPIRED",
  AUTH_TOKEN_INVALID: "AUTH_TOKEN_INVALID",
  AUTH_TOKEN_REVOKED: "AUTH_TOKEN_REVOKED",
  CONFIGURATION_ERROR: "CONFIGURATION_ERROR",
  CONFLICT: "CONFLICT",
  CONTEXT_LENGTH_EXCEEDED: "CONTEXT_LENGTH_EXCEEDED",
  CREDENTIAL_NOT_FOUND: "CREDENTIAL_NOT_FOUND",
  DEPENDENCY_MISSING: "DEPENDENCY_MISSING",
  EVENT_CURSOR_EXPIRED: "EVENT_CURSOR_EXPIRED",
  HEARTBEAT_TIMEOUT: "HEARTBEAT_TIMEOUT",
  IDEMPOTENCY_KEY_REUSE: "IDEMPOTENCY_KEY_REUSE",
  INTERNAL_ERROR: "INTERNAL_ERROR",
  MAX_ITERATIONS: "MAX_ITERATIONS",
  METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
  NOT_FOUND: "NOT_FOUND",
  NOT_IMPLEMENTED: "NOT_IMPLEMENTED",
  ORGANIZATION_NOT_FOUND: "ORGANIZATION_NOT_FOUND",
  PERMISSION_DENIED: "PERMISSION_DENIED",
  RESOURCE_LIMIT_EXCEEDED: "RESOURCE_LIMIT_EXCEEDED",
  TASK_NOT_FOUND: "TASK_NOT_FOUND",
  TENANT_NOT_FOUND: "TENANT_NOT_FOUND",
  TOOL_TIMEOUT: "TOOL_TIMEOUT",
  UNAUTHORIZED: "UNAUTHORIZED",
  UNKNOWN: "UNKNOWN",
  USER_ALREADY_EXISTS: "USER_ALREADY_EXISTS",
  USER_NOT_FOUND: "USER_NOT_FOUND",
  VALIDATION_ERROR: "VALIDATION_ERROR",
  WORKSPACE_NOT_FOUND: "WORKSPACE_NOT_FOUND",
} as const;

/** 错误码联合类型：与 `ERROR_CODES` 同源，新增/删码即刻类型级可见。 */
export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

/** 错误码 → HTTP 状态码映射（来源：contracts/errors.json → codes[*].http_status）。 */
export const ERROR_HTTP_STATUS: Readonly<Record<ErrorCode, number>> = {
  AUTH_ACCOUNT_LOCKED: 423, // 账号已锁定。
  AUTH_INVALID_CREDENTIALS: 401, // 登录凭证（用户名 / 密码等）错误。
  AUTH_TOKEN_EXPIRED: 401, // 访问令牌已过期。
  AUTH_TOKEN_INVALID: 401, // 访问令牌非法（签名 / 格式错误）。
  AUTH_TOKEN_REVOKED: 401, // 访问令牌已撤销。
  CONFIGURATION_ERROR: 422, // 配置非法或缺失。
  CONFLICT: 409, // 资源状态冲突（版本、唯一性等）。
  CONTEXT_LENGTH_EXCEEDED: 422, // 上下文长度超出模型窗口。
  CREDENTIAL_NOT_FOUND: 404, // 凭证记录不存在。
  DEPENDENCY_MISSING: 503, // 可选依赖 / 能力未装配；非静默降级，须显式上报。状态由 call-site 决定：8 处显式 503，2 处未传 status_code 的构造点回落 500（见 http_status_uniform=false）。
  EVENT_CURSOR_EXPIRED: 410, // 事件续读游标已过期（引用序号低于保留窗口低水位）。
  HEARTBEAT_TIMEOUT: 500, // 心跳超时（执行端失联）。
  IDEMPOTENCY_KEY_REUSE: 409, // 幂等键复用但请求内容不一致。
  INTERNAL_ERROR: 500, // 服务端未预期错误，由兜底异常处理器产出。
  MAX_ITERATIONS: 422, // Agent 迭代次数达到上限。
  METHOD_NOT_ALLOWED: 405, // HTTP 方法不被该路径允许。
  NOT_FOUND: 404, // 资源不存在。
  NOT_IMPLEMENTED: 501, // 功能尚未实现（骨架路由占位、Feature Flag 降级）。
  ORGANIZATION_NOT_FOUND: 404, // 组织不存在。
  PERMISSION_DENIED: 403, // 已认证但权限不足。
  RESOURCE_LIMIT_EXCEEDED: 429, // 执行期资源限额超限（并行度 / 产物 / 等待队列）。
  TASK_NOT_FOUND: 404, // 任务不存在。
  TENANT_NOT_FOUND: 404, // 租户不存在。
  TOOL_TIMEOUT: 504, // 工具调用超时。
  UNAUTHORIZED: 401, // 未认证或凭证缺失 / 无效。
  UNKNOWN: 500, // 未分类错误的兜底码（框架层 HTTPException 无对应码时回落）。
  USER_ALREADY_EXISTS: 409, // 用户已存在（唯一性冲突）。
  USER_NOT_FOUND: 404, // 用户不存在。
  VALIDATION_ERROR: 422, // 请求参数 / 数据校验失败；FastAPI RequestValidationError 亦映射到此码。
  WORKSPACE_NOT_FOUND: 404, // 工作空间不存在。
};

/** 错误码 → 中文描述（来源：contracts/errors.json → codes[*].description）。 */
export const ERROR_DESCRIPTIONS: Readonly<Record<ErrorCode, string>> = {
  AUTH_ACCOUNT_LOCKED: "账号已锁定。",
  AUTH_INVALID_CREDENTIALS: "登录凭证（用户名 / 密码等）错误。",
  AUTH_TOKEN_EXPIRED: "访问令牌已过期。",
  AUTH_TOKEN_INVALID: "访问令牌非法（签名 / 格式错误）。",
  AUTH_TOKEN_REVOKED: "访问令牌已撤销。",
  CONFIGURATION_ERROR: "配置非法或缺失。",
  CONFLICT: "资源状态冲突（版本、唯一性等）。",
  CONTEXT_LENGTH_EXCEEDED: "上下文长度超出模型窗口。",
  CREDENTIAL_NOT_FOUND: "凭证记录不存在。",
  DEPENDENCY_MISSING: "可选依赖 / 能力未装配；非静默降级，须显式上报。状态由 call-site 决定：8 处显式 503，2 处未传 status_code 的构造点回落 500（见 http_status_uniform=false）。",
  EVENT_CURSOR_EXPIRED: "事件续读游标已过期（引用序号低于保留窗口低水位）。",
  HEARTBEAT_TIMEOUT: "心跳超时（执行端失联）。",
  IDEMPOTENCY_KEY_REUSE: "幂等键复用但请求内容不一致。",
  INTERNAL_ERROR: "服务端未预期错误，由兜底异常处理器产出。",
  MAX_ITERATIONS: "Agent 迭代次数达到上限。",
  METHOD_NOT_ALLOWED: "HTTP 方法不被该路径允许。",
  NOT_FOUND: "资源不存在。",
  NOT_IMPLEMENTED: "功能尚未实现（骨架路由占位、Feature Flag 降级）。",
  ORGANIZATION_NOT_FOUND: "组织不存在。",
  PERMISSION_DENIED: "已认证但权限不足。",
  RESOURCE_LIMIT_EXCEEDED: "执行期资源限额超限（并行度 / 产物 / 等待队列）。",
  TASK_NOT_FOUND: "任务不存在。",
  TENANT_NOT_FOUND: "租户不存在。",
  TOOL_TIMEOUT: "工具调用超时。",
  UNAUTHORIZED: "未认证或凭证缺失 / 无效。",
  UNKNOWN: "未分类错误的兜底码（框架层 HTTPException 无对应码时回落）。",
  USER_ALREADY_EXISTS: "用户已存在（唯一性冲突）。",
  USER_NOT_FOUND: "用户不存在。",
  VALIDATION_ERROR: "请求参数 / 数据校验失败；FastAPI RequestValidationError 亦映射到此码。",
  WORKSPACE_NOT_FOUND: "工作空间不存在。",
};

/** 稳定顺序（字典序）的错误码清单，供门禁逐项比对。 */
export const ERROR_CODE_LIST: readonly ErrorCode[] = [
  "AUTH_ACCOUNT_LOCKED",
  "AUTH_INVALID_CREDENTIALS",
  "AUTH_TOKEN_EXPIRED",
  "AUTH_TOKEN_INVALID",
  "AUTH_TOKEN_REVOKED",
  "CONFIGURATION_ERROR",
  "CONFLICT",
  "CONTEXT_LENGTH_EXCEEDED",
  "CREDENTIAL_NOT_FOUND",
  "DEPENDENCY_MISSING",
  "EVENT_CURSOR_EXPIRED",
  "HEARTBEAT_TIMEOUT",
  "IDEMPOTENCY_KEY_REUSE",
  "INTERNAL_ERROR",
  "MAX_ITERATIONS",
  "METHOD_NOT_ALLOWED",
  "NOT_FOUND",
  "NOT_IMPLEMENTED",
  "ORGANIZATION_NOT_FOUND",
  "PERMISSION_DENIED",
  "RESOURCE_LIMIT_EXCEEDED",
  "TASK_NOT_FOUND",
  "TENANT_NOT_FOUND",
  "TOOL_TIMEOUT",
  "UNAUTHORIZED",
  "UNKNOWN",
  "USER_ALREADY_EXISTS",
  "USER_NOT_FOUND",
  "VALIDATION_ERROR",
  "WORKSPACE_NOT_FOUND",
];

/** 未登记的错误码一律回落到 UNKNOWN，并取 500。 */
export const UNKNOWN_ERROR_CODE: ErrorCode = "UNKNOWN";

/** 取 HTTP 状态码：未知码回落 UNKNOWN 的状态码（不静默给 500 字面量）。 */
export function httpStatusFor(code: string): number {
  return ERROR_HTTP_STATUS[code as ErrorCode] ?? ERROR_HTTP_STATUS[UNKNOWN_ERROR_CODE];
}
