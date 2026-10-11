/**
 * Phase 1（v0.2）前端领域 DTO 与 SSE 契约类型（W7 / T1-32 ~ T1-34）。
 *
 * 与后端 `/api/v1` 契约严格对齐（设计 §2.9 / §2.13 / §2.15；`apps/api/src/astra_api/schemas/*.py`）。
 * 统一响应壳 `{code,message,data,request_id}` 由 `lib/api.ts` 拦截器解壳，服务层拿到业务 DTO。
 *
 * ⚠️ 凭证相关类型（`CredentialResponse` / `SaveCredentialRequest`）复用 `./api.ts`，
 *    本模块**不重复定义**（前端仅掩码，C-07）。
 */

// -- Agent -------------------------------------------------------------------

/** Agent 类型字面量。 */
export type AgentType =
  "PRIMARY" | "SUB_AGENT" | "WORKFLOW_AGENT" | "SCHEDULED_AGENT" | "EVENT_AGENT";

/** Agent 状态字面量。 */
export type AgentStatus = "DRAFT" | "ACTIVE" | "ARCHIVED";

/** Agent 响应。 */
export interface AgentResponse {
  id: string;
  tenant_id?: string | null;
  name: string;
  workspace_id?: string | null;
  description?: string | null;
  type: string;
  status: string;
  current_version_id?: string | null;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
}

/** 创建 Agent 请求。 */
export interface CreateAgentRequest {
  name: string;
  description?: string | null;
  type?: string;
  workspace_id?: string | null;
}

/** 更新 Agent 请求（缺省字段不变）。 */
export interface UpdateAgentRequest {
  name?: string;
  description?: string | null;
  status?: string;
}

/** AgentVersion ↔ Tool 绑定入参。 */
export interface AgentToolBind {
  tool_id: string;
  permission_scope?: Record<string, unknown>;
  enabled?: boolean;
}

/**
 * 发布 AgentVersion 请求。
 *
 * 注意：后端 Pydantic 字段名为 `model_configuration`，对外别名为 `model_config`；
 * 前端请求体使用别名 `model_config`（`populate_by_name` 两者皆可）。
 */
export interface PublishRequest {
  system_prompt?: string;
  model_config?: Record<string, unknown>;
  runtime_config?: Record<string, unknown>;
  version?: string | null;
  tools?: AgentToolBind[];
}

/** AgentVersion 响应（`model_config` 为对外字段）。 */
export interface AgentVersionResponse {
  id: string;
  agent_id: string;
  version: string;
  system_prompt: string;
  model_config: Record<string, unknown>;
  runtime_config: Record<string, unknown>;
  status: string;
  created_by: string;
  created_at?: string | null;
}

/** AgentVersion ↔ Tool 绑定响应。 */
export interface AgentToolResponse {
  id: string;
  tenant_id?: string | null;
  agent_version_id: string;
  tool_id: string;
  enabled: boolean;
  permission_scope: Record<string, unknown>;
}

// -- Run ---------------------------------------------------------------------

/** Run 响应。 */
export interface RunResponse {
  id: string;
  tenant_id?: string | null;
  agent_id: string;
  agent_version_id: string;
  conversation_id: string;
  user_id?: string | null;
  task_id?: string | null;
  trigger: string;
  run_mode: string;
  status: string;
  trace_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  success?: boolean | null;
  error_type?: string | null;
  token_usage: Record<string, unknown>;
  cost?: number | null;
  cost_status: string;
  error?: string | null;
}

/** 运行 Agent 请求（`Accept: text/event-stream` → SSE 流）。 */
export interface RunAgentRequest {
  message?: string;
  conversation_id?: string | null;
  workspace_id?: string | null;
  run_mode?: string;
}

/** 生命周期事件响应（`Last-Event-ID` / `?after_seq` 续传）。 */
export interface RunEventResponse {
  seq: number;
  type: string;
  payload: Record<string, unknown>;
  trace_id?: string | null;
  span_id?: string | null;
  created_at?: string | null;
}

// -- Conversation ------------------------------------------------------------

/** 会话响应。 */
export interface ConversationResponse {
  id: string;
  tenant_id?: string | null;
  workspace_id: string;
  agent_id: string;
  user_id: string;
  title: string;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
}

/** 创建会话请求。 */
export interface CreateConversationRequest {
  agent_id: string;
  workspace_id?: string;
  title?: string;
}

/** 会话消息响应。 */
export interface ConversationMessageResponse {
  id: string;
  conversation_id: string;
  run_id?: string | null;
  role: string;
  content: string;
  content_parts: unknown[];
  token_count?: number | null;
  created_at?: string | null;
}

// -- Model -------------------------------------------------------------------

/** 模型提供方响应（`credential_id` 仅引用，无明文 / 密文）。 */
export interface ModelProviderResponse {
  id: string;
  tenant_id?: string | null;
  workspace_id?: string | null;
  name: string;
  type: string;
  endpoint?: string | null;
  credential_id?: string | null;
  status: string;
  config: Record<string, unknown>;
  created_at?: string | null;
}

/** 模型目录响应。 */
export interface ModelResponse {
  id: string;
  tenant_id?: string | null;
  provider_id: string;
  name: string;
  type: string;
  context_window?: number | null;
  capabilities: Record<string, unknown>;
  status: string;
  created_at?: string | null;
}

/** 注册模型提供方请求。 */
export interface RegisterProviderRequest {
  name: string;
  provider_type: string;
  endpoint?: string | null;
  credential_id?: string | null;
  config?: Record<string, unknown>;
  workspace_id?: string | null;
}

/** 注册模型请求。 */
export interface RegisterModelRequest {
  name: string;
  model_type?: string;
  context_window?: number | null;
  capabilities?: Record<string, unknown>;
}

/** 绑定凭证到 Provider 请求（仅存引用）。 */
export interface BindCredentialRequest {
  credential_id: string;
}

// -- Tool --------------------------------------------------------------------

/** 工具目录项响应（内置工具浏览器）。 */
export interface ToolResponse {
  id?: string | null;
  name: string;
  display_name: string;
  description: string;
  category: string;
  type: string;
  requires_sandbox: boolean;
  input_schema: Record<string, unknown>;
}

/** 授予 / 更新 Tool 权限请求（agent × tool × effect × scope）。 */
export interface ToolPermissionRequest {
  tool_id: string;
  action?: string;
  effect?: string;
  scope?: Record<string, unknown>;
  agent_id?: string | null;
  agent_version_id?: string | null;
}

/** Tool 权限响应。 */
export interface ToolPermissionResponse {
  id: string;
  tenant_id?: string | null;
  agent_id?: string | null;
  agent_version_id?: string | null;
  tool_id: string;
  action: string;
  effect: string;
  scope: Record<string, unknown>;
  created_at?: string | null;
}

/** Tool 权限动作字面量。 */
export type ToolAction = "EXECUTE" | "READ" | "WRITE";

/** Tool 权限效果字面量（ALLOW / DENY）。 */
export type ToolEffect = "ALLOW" | "DENY";

// -- SSE（9 通道，设计 §2.9） ------------------------------------------------

/** SSE 通道名（9 类）。 */
export type SseChannel =
  | "agent.started"
  | "agent.thinking"
  | "message.delta"
  | "tool.started"
  | "tool.completed"
  | "mcp.started"
  | "mcp.completed"
  | "agent.completed"
  | "agent.error";

/** 全部 SSE 通道（有序），用于穷举与测试。 */
export const SSE_CHANNELS: readonly SseChannel[] = [
  "agent.started",
  "agent.thinking",
  "message.delta",
  "tool.started",
  "tool.completed",
  "mcp.started",
  "mcp.completed",
  "agent.completed",
  "agent.error",
];

/** 判定字符串是否为合法 SSE 通道。 */
export function isSseChannel(value: string): value is SseChannel {
  return (SSE_CHANNELS as readonly string[]).includes(value);
}

/** 解析后的 SSE 事件（`seq` 来自帧 `id:`；心跳注释帧无 `event:` 被忽略）。 */
export interface ChatStreamEvent {
  seq: number | null;
  channel: SseChannel;
  payload: Record<string, unknown>;
}

/** 终态通道（`agent.completed` / `agent.error`）。 */
export function isTerminalChannel(channel: SseChannel): boolean {
  return channel === "agent.completed" || channel === "agent.error";
}

// -- UI 模型（客户端态，Zustand） -------------------------------------------

/** 会话消息角色（UI 视图）。 */
export type ChatRole = "system" | "user" | "assistant" | "tool";

/** 会话消息（UI 视图；`streaming` 标记流式未完成）。 */
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  streaming?: boolean;
  createdAt?: string | null;
}

/** 时间线条目种类。 */
export type TimelineKind = "tool" | "mcp" | "thinking";

/** 时间线条目状态。 */
export type TimelineStatus = "running" | "completed" | "error";

/** 事件时间线条目（`tool.*` / `mcp.*` / `agent.thinking`）。 */
export interface TimelineEntry {
  id: string;
  kind: TimelineKind;
  status: TimelineStatus;
  name: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  durationMs?: number;
  error?: string;
  seq: number | null;
}
