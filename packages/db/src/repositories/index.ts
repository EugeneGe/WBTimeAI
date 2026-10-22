/**
 * T1-03 / T2-03 · 数据层仓储出口。
 *
 * 两族：
 * * **通用**（`ScopedRepo` 基类 + T1-03 的三个业务仓储）；
 * * **身份族**（T2-03 · 11 张身份表：8 个 scoped + 3 个白名单通道）。
 *
 * 三个白名单通道的存在理由写在 `./unscoped-repo.ts` 的 `UNSCOPED_WHITELIST` 里，
 * 那是代码内的台账 —— 想给第 4 张表开 unscoped 通道，构造时就会抛 `ScopeError`。
 */

export {
  ScopedRepo,
  Scope,
  ScopeError,
  resolveListLimit,
  type DrizzleDatabase,
  type ListOptions,
  type ScopedRef,
  type ScopedRepoOptions,
  type TenantScopedInsert,
  type TenantScopedPatch,
} from "./scoped-repo.js";
export { TaskRepo, type TaskRow } from "./task-repo.js";
export { AgentRepo, type AgentRow } from "./agent-repo.js";
export {
  ConversationRepo,
  CONVERSATION_STATUS_ACTIVE,
  type ConversationRow,
  type CreateConversationInput,
} from "./conversation-repo.js";

// ---------------------------------------------------------------------------
// 方言适配
// ---------------------------------------------------------------------------

export { resolveTable, toSqliteTimestamp, instantLiteral, type SqlDialect } from "./dialect.js";

// ---------------------------------------------------------------------------
// 身份族 · 8 个 scoped 仓储（`extends ScopedRepo<XxxRow>`）
// ---------------------------------------------------------------------------

export { TenantRepo, type TenantRow } from "./tenant-repo.js";
export { UserRepo, type UserRow } from "./user-repo.js";
export { OrganizationRepo, type OrganizationRow } from "./organization-repo.js";
export {
  MembershipRepo,
  MEMBERSHIP_STATUS_ACTIVE,
  type MembershipRow,
} from "./membership-repo.js";
export { RoleRepo, type RoleRow } from "./role-repo.js";
export {
  ResourcePermissionRepo,
  decideResourcePermission,
  type ResourcePermissionRow,
  type ResourcePermissionQuery,
  type ResourceDecision,
  type PermissionEffect,
  type PermissionSubjectType,
} from "./resource-permission-repo.js";
export { SessionRepo, type SessionRow } from "./session-repo.js";
export {
  RefreshTokenRepo,
  assertSha256Hex,
  type RefreshTokenRow,
} from "./refresh-token-repo.js";

// ---------------------------------------------------------------------------
// 身份族 · 3 个白名单通道（unscoped，理由见 UNSCOPED_WHITELIST）
// ---------------------------------------------------------------------------

export {
  UNSCOPED_WHITELIST,
  UnscopedTableRepo,
  type UnscopedTableName,
} from "./unscoped-repo.js";
export { PermissionCatalog, ADMIN_PERMISSION, type PermissionRow } from "./permission-catalog.js";
export { RolePermissionCatalog, type RolePermissionRow } from "./role-permission-catalog.js";
export {
  LoginAttemptSink,
  countConsecutiveFailures,
  LOGIN_ATTEMPT_WINDOW_SIZE,
  LOGIN_MAX_CONSECUTIVE_FAILURES,
  LOGIN_LOCK_SECONDS,
  type LoginAttemptRecord,
  type LoginAttemptRow,
} from "./login-attempt-sink.js";

// ---------------------------------------------------------------------------
// 模型/凭证族（T2-07 新增；**不在** T2-03 的 11 张身份表内）
// ---------------------------------------------------------------------------

export { ModelCredentialRepo, type CredentialRow } from "./model-credential-repo.js";
// QA 遗留第 3 条（T3-03 接线）：把 T3-02 新增的常量与类型透出，
// 免得调用方/测试再用字面量 `"ACTIVE"` 复述口径。
export {
  ModelProviderRepo,
  CREDENTIAL_STATUS_ACTIVE,
  PROVIDER_STATUS_ACTIVE,
  type CredentialState,
  type ModelProviderRow,
  type ProviderKeyCarrier,
} from "./model-provider-repo.js";

// ---------------------------------------------------------------------------
// 运行时族（T3-03 · W2；**不在** T2-03 的 11 张身份表内）
// ---------------------------------------------------------------------------

export {
  ChildScopedRepo,
  ChildConflictError,
  type ChildListOptions,
  type ChildRepoOptions,
  type ChildScopedInsert,
  type ChildScopedPatch,
} from "./child-scoped-repo.js";
export {
  AgentRunRepo,
  AGENT_RUN_STATUSES,
  TERMINAL_AGENT_RUN_STATUSES,
  isTerminalAgentRunStatus,
  type AcquireLeaseOptions,
  type AgentRunRow,
  type FinalizeRunPatch,
} from "./agent-run-repo.js";
export {
  ToolCallRepo,
  TOOL_CALL_STATUSES,
  TERMINAL_TOOL_CALL_STATUSES,
  isTerminalToolCallStatus,
  type MarkRunningOptions,
  type MarkTerminalOptions,
  type ToolCallRow,
} from "./tool-call-repo.js";
export {
  AgentEventRepo,
  type AgentEventRow,
  type AppendEventInput,
  type AppendedEvent,
} from "./agent-event-repo.js";
export { MessageRepo, type AppendMessageInput, type MessageRow } from "./message-repo.js";

// ---------------------------------------------------------------------------
// 工具目录族（T3-03 · B1；`tool` 有 tenant_id ⇒ ScopedRepo；含 R3-23 幂等物化）
// ---------------------------------------------------------------------------

export {
  ToolRepo,
  BUILTIN_TOOLS,
  BUILTIN_TOOL_VERSION,
  CODE_EXEC_DEFAULT_RUNTIME,
  CODE_EXEC_RUNTIMES,
  TOOL_SOURCE_BUILTIN,
  TOOL_STATUS_ACTIVE,
  readToolPermissionAction,
  serializeBuiltinInputSchema,
  serializeBuiltinToolSpec,
  toToolCatalogEntry,
  type BuiltinToolSpec,
  type BuiltinToolsSummary,
  type ToolCatalogEntry,
  type ToolPermissionAction,
  type ToolRow,
  type ToolVersionRow,
} from "./tool-repo.js";

// ---------------------------------------------------------------------------
// B2 · 审批族（`approval` 有 tenant_id、无父外键 ⇒ ScopedRepo；独立租户域）
// ---------------------------------------------------------------------------

export {
  ApprovalRepo,
  APPROVAL_STATUSES,
  APPROVAL_STATUS_APPROVED,
  APPROVAL_STATUS_EXPIRED,
  APPROVAL_STATUS_PENDING,
  APPROVAL_STATUS_REJECTED,
  APPROVAL_SUBJECT_TYPES,
  APPROVAL_TERMINAL_STATUSES,
  APPROVAL_LIST_DEFAULT_LIMIT,
  APPROVAL_LIST_MAX_LIMIT,
  isTerminalApprovalStatus,
  type ApprovalRow,
  type CreateApprovalInput,
  type DecideApprovalInput,
} from "./approval-repo.js";
