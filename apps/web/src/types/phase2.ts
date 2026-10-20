/**
 * Phase 2a 前端领域 DTO（W3 / T2-18；设计 §2.3 / §2.4 / §2.10.2 / §2.12）。
 *
 * 与后端 `apps/api/src/wbtime_ai_api/schemas/{skill,mcp,permission}.py` 严格对齐；
 * 统一响应壳由 `lib/api.ts` 拦截器解壳，服务层直接拿到业务 DTO。
 *
 * 🔴 凭据纪律（C-07）：MCP Server 的 `credential_id` / `env_ref` 均为**引用**，
 *    **不含明文 / 密文**；前端只展示引用（掩码），**不回显明文**。
 */
import type { AgentResponse, AgentVersionResponse, PublishRequest } from "./phase1";

// -- Skill -------------------------------------------------------------------

/** Skill 响应。 */
export interface SkillResponse {
  id: string;
  tenant_id?: string | null;
  name: string;
  display_name: string;
  description?: string | null;
  category: string;
  status: string;
  current_version_id?: string | null;
  current_version?: string | null;
  created_by: string;
  created_at?: string | null;
}

/** 创建 Skill 请求。 */
export interface CreateSkillRequest {
  name: string;
  display_name?: string;
  description?: string | null;
  category?: string;
}

/** 更新 Skill 请求（仅提供需变更字段）。 */
export interface UpdateSkillRequest {
  display_name?: string | null;
  description?: string | null;
  category?: string | null;
  status?: string | null;
}

/** 创建 Skill 版本请求。 */
export interface CreateSkillVersionRequest {
  version: string;
  instructions?: string;
  manifest?: Record<string, unknown>;
}

/** SkillVersion 响应（不含资源二进制）。 */
export interface SkillVersionResponse {
  id: string;
  skill_id: string;
  version: string;
  instructions: string;
  manifest: Record<string, unknown>;
  status: string;
  created_by: string;
  created_at?: string | null;
}

// -- MCP ---------------------------------------------------------------------

/** 注册 MCP Server 请求（凭据仅引用）。 */
export interface RegisterMCPServerRequest {
  name: string;
  transport?: string;
  endpoint?: string | null;
  command?: string | null;
  args?: string[];
  env_ref?: Record<string, unknown>;
  credential_id?: string | null;
  workspace_id?: string | null;
}

/** MCP Server 响应（无明文）。 */
export interface MCPServerResponse {
  id: string;
  tenant_id?: string | null;
  name: string;
  transport: string;
  endpoint?: string | null;
  command?: string | null;
  args: string[];
  env_ref: Record<string, unknown>;
  credential_id?: string | null;
  status: string;
  workspace_id?: string | null;
  created_at?: string | null;
}

/** MCP Tool（发现目录）响应。 */
export interface MCPToolResponse {
  id: string;
  mcp_server_id: string;
  name: string;
  description?: string | null;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  status: string;
  discovered_at?: string | null;
}

/** MCP Tool 授权请求（agent × mcp_tool × effect × scope）。 */
export interface CreateMCPPermissionRequest {
  agent_id?: string | null;
  agent_version_id?: string | null;
  mcp_tool_id: string;
  action?: string;
  effect?: string;
  scope?: Record<string, unknown>;
}

/** MCP Tool 授权响应。 */
export interface MCPPermissionResponse {
  id: string;
  tenant_id?: string | null;
  agent_id?: string | null;
  agent_version_id?: string | null;
  mcp_tool_id: string;
  action: string;
  effect: string;
  scope: Record<string, unknown>;
  created_at?: string | null;
}

// -- Permission（capability 检查，`can()` 数据源） ----------------------------

/** 能力检查响应（后端唯一判定输入源）。 */
export interface PermissionCheckResponse {
  capability: string;
  allowed: boolean;
  effect: string;
  reason: string;
  source?: string | null;
}

// ---------------------------------------------------------------------------
// Phase 2b / W6（T2-35）：Workflow / Knowledge / Memory
//
// 与后端 `apps/api/src/wbtime_ai_api/schemas/{workflow,knowledge,memory}.py` 严格对齐；
// 统一响应壳由 `lib/api.ts` 拦截器解壳，服务层直接拿到业务 DTO。
// ---------------------------------------------------------------------------

// -- Workflow ----------------------------------------------------------------

/** 画布 8 类节点字面值（↔ `workflow_node`；裁定 §3.4 冻结）。 */
export type WorkflowNodeType =
  "AGENT" | "TOOL" | "MCP" | "CONDITION" | "PARALLEL" | "LOOP" | "HUMAN_APPROVAL" | "END";

/** 画布 8 类节点（有序，供工具栏渲染）。 */
export const WORKFLOW_NODE_TYPES: readonly WorkflowNodeType[] = [
  "AGENT",
  "TOOL",
  "MCP",
  "CONDITION",
  "PARALLEL",
  "LOOP",
  "HUMAN_APPROVAL",
  "END",
] as const;

/** 发布快照中的节点定义（↔ `workflow_node`）。 */
export interface WorkflowNodeDef {
  key: string;
  type: string;
  config: Record<string, unknown>;
  position: Record<string, unknown>;
}

/** 发布快照中的连边定义（↔ `workflow_edge`）。 */
export interface WorkflowEdgeDef {
  from: string;
  to: string;
  condition?: string | null;
}

/** 完整图快照（`workflow_version.definition`）。 */
export interface WorkflowDefinition {
  nodes: WorkflowNodeDef[];
  edges: WorkflowEdgeDef[];
  entry?: string | null;
}

/** Workflow 响应。 */
export interface WorkflowResponse {
  id: string;
  tenant_id?: string | null;
  workspace_id?: string | null;
  name: string;
  description?: string | null;
  status: string;
  current_version_id?: string | null;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
}

/** WorkflowVersion 响应（不可变快照）。 */
export interface WorkflowVersionResponse {
  id: string;
  workflow_id: string;
  version: string;
  status: string;
  definition: WorkflowDefinition;
  created_by: string;
  created_at?: string | null;
}

/** 创建 Workflow 请求。 */
export interface CreateWorkflowRequest {
  name: string;
  description?: string | null;
  workspace_id?: string | null;
}

/** 发布 WorkflowVersion 请求（一次发布 = 一个新版本）。 */
export interface PublishWorkflowRequest {
  nodes: WorkflowNodeDef[];
  edges: WorkflowEdgeDef[];
  entry?: string | null;
  version?: string | null;
}

// -- Workflow 运行（INLINE 同步 / 重放快照 / 取消） ---------------------------

/**
 * WorkflowRun 状态（↔ `wbtime_ai_workflow.domain.state.WorkflowRunStatus`，六态**冻结**）。
 *
 * `WAITING_APPROVAL` 为**非终态**（审批挂起，恢复后回到 `RUNNING`）。
 */
export type WorkflowRunStatus =
  "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "WAITING_APPROVAL";

/**
 * WorkflowNodeRun 状态（↔ `wbtime_ai_workflow.domain.state.WorkflowNodeRunStatus`）。
 *
 * 与 Run 级差异：节点级终态含 `SKIPPED`（分支未命中 / 未执行）。
 */
export type WorkflowNodeRunStatus =
  "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED" | "WAITING_APPROVAL";

/** Run 级**终态**集合（不可再转移 → 无需轮询、不可取消）。 */
export const WORKFLOW_RUN_TERMINAL_STATUSES: readonly WorkflowRunStatus[] = [
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
] as const;

/** 判定 Run 是否已到终态（`true` 时停止轮询 / 禁用取消）。 */
export function isTerminalWorkflowRunStatus(status: string | null | undefined): boolean {
  return (WORKFLOW_RUN_TERMINAL_STATUSES as readonly string[]).includes(status ?? "");
}

/**
 * `POST /workflows/{id}/run` 的**裸 JSON** 摘要（↔ 后端 `_json_run_digest`）。
 *
 * 🔴 该端点**不套统一响应壳**（`Accept: application/json` 时的 JSON 降级分支），
 *    `lib/api.ts` 拦截器 `isResponseShell()` 判定非壳 → 原样放行。
 */
export interface WorkflowRunDigest {
  /** 本次运行 id（后续拉重放 / 取消的入参）。 */
  run_id: string;
  /** 运行使用的版本快照 id。 */
  workflow_version_id: string;
  /** 运行状态（`INLINE` 同步执行 → 请求返回时通常已是终态）。 */
  status: string;
  /** 关联任务 id（无则 `null`）。 */
  task_id?: string | null;
  /** 运行失败时的错误摘要（成功为 `null`）。 */
  error?: string | null;
}

/** 单个节点的运行态（↔ `WorkflowNodeRunResponse`）。 */
export interface WorkflowReplayNode {
  id: string;
  workflow_run_id?: string;
  /** 节点 key（↔ 画布节点 `id`）。 */
  node_key: string;
  /** 节点状态（{@link WorkflowNodeRunStatus}）。 */
  status: string;
  /** 第几次尝试（从 1 起）。 */
  attempt: number;
  agent_run_id?: string | null;
  tool_call_id?: string | null;
  approval_id?: string | null;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  started_at?: string | null;
  completed_at?: string | null;
}

/**
 * 运行重放快照（↔ `WorkflowReplayResponse`；`I-P2-06` 可重建视图）。
 *
 * `GET /workflows/{id}/runs/{run_id}` 走统一响应壳 → 服务层直接拿到本 DTO。
 */
export interface WorkflowReplay {
  run_id: string;
  workflow_id: string;
  workflow_version_id: string;
  /** 运行状态（{@link WorkflowRunStatus}）。 */
  status: string;
  /** 触发来源（`user` / `schedule` / `webhook` …）。 */
  trigger: string;
  input: Record<string, unknown>;
  output?: Record<string, unknown> | null;
  error?: string | null;
  /** 节点运行态（按执行顺序返回）。 */
  nodes: WorkflowReplayNode[];
  task_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

/** 取消运行响应（↔ `WorkflowRunResponse`；走统一响应壳）。 */
export interface WorkflowRunDetail {
  id: string;
  tenant_id?: string | null;
  workflow_version_id: string;
  trigger: string;
  /** 取消后状态（通常为 `CANCELLED`）。 */
  status: string;
  task_id?: string | null;
  input?: Record<string, unknown>;
  output?: Record<string, unknown> | null;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
}

// -- Knowledge ---------------------------------------------------------------

/** KnowledgeBase 响应。 */
export interface KnowledgeBaseResponse {
  id: string;
  tenant_id?: string | null;
  workspace_id?: string | null;
  name: string;
  description?: string | null;
  embedding_model: Record<string, unknown>;
  chunk_config: Record<string, unknown>;
  status: string;
  created_by: string;
  created_at?: string | null;
}

/** Document 响应（`status` 供展示索引进度）。 */
export interface DocumentResponse {
  id: string;
  knowledge_base_id: string;
  title: string;
  source_type: string;
  storage_key?: string | null;
  mime?: string | null;
  size?: number | null;
  checksum?: string | null;
  status: string;
  error?: string | null;
  task_id?: string | null;
  created_at?: string | null;
}

/** 创建 KnowledgeBase 请求。 */
export interface CreateKnowledgeBaseRequest {
  name: string;
  description?: string | null;
  workspace_id?: string | null;
  embedding_model?: Record<string, unknown>;
  chunk_config?: Record<string, unknown>;
}

/** 更新 KnowledgeBase 请求（PATCH；至少一项；`description: null` = 清空描述）。 */
export interface UpdateKnowledgeBaseRequest {
  name?: string;
  description?: string | null;
}

/** 登记文档请求（2b 仅登记元数据）。 */
export interface CreateDocumentRequest {
  title: string;
  source_type?: string;
  storage_key?: string | null;
  mime?: string | null;
  size?: number | null;
  checksum?: string | null;
}

/** 检索试跑请求。 */
export interface SearchRequest {
  query: string;
  knowledge_base_id?: string | null;
  workspace_id?: string | null;
  top_k?: number;
}

/** 检索命中（引用可回溯）。 */
export interface SearchHitResponse {
  chunk_id: string;
  content: string;
  score: number;
  source: string;
  metadata: Record<string, unknown>;
}

/** 检索试跑响应（命中 + 检索路 `mode`）。 */
export interface SearchResponse {
  query: string;
  mode: string;
  kb_ids: string[];
  hits: SearchHitResponse[];
}

// -- Memory ------------------------------------------------------------------

/** Memory 视图响应（F-d 形状；含来源 Run `source_run_id`）。 */
export interface MemoryResponse {
  id: string;
  tenant_id?: string | null;
  workspace_id?: string | null;
  kind: string;
  scope_type: string;
  scope_id?: string | null;
  visibility: string;
  content: string;
  memory_type?: string | null;
  importance: number;
  confidence?: number | null;
  source_run_id?: string | null;
  expires_at?: string | null;
  created_at?: string | null;
}

/** Memory 浏览参数（F-d query）。 */
export interface MemoryListParams {
  scope_type?: string | null;
  scope_id?: string | null;
  kind?: string | null;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Phase 2c / W8（T2-41）：Agent Studio（主框架 + 九分区 + 版本发布）
//
// 与设计 §2.13「Agent Studio：左侧分区 Basic / Model / Prompt / Skills / Tools /
// MCP / Knowledge / Memory / Permission，右侧配置与预览；含版本管理与发布」对齐。
//
// 🔴 R6 / R14：本模块**复用**既有能力与 SDK（不重复实现后端能力）；**不引入** `js-yaml`。
// ---------------------------------------------------------------------------

/** Studio 九分区标识（左侧导航；顺序与设计 §2.13 一致）。 */
export type AgentStudioPanelId =
  "basic" | "model" | "prompt" | "skills" | "tools" | "mcp" | "knowledge" | "memory" | "permission";

/** 一个 Studio 分区描述（供左侧导航渲染）。 */
export interface AgentStudioPanelDef {
  /** 分区标识（↔ 面板组件）。 */
  id: AgentStudioPanelId;
  /** 展示名（技术英文名，两种语言一致 → 不参与翻译）。 */
  label: string;
  /** 一句话说明的 **i18n key**（渲染方经 `t(descriptionKey)` 取词；模块顶层不取 `t`）。 */
  descriptionKey: string;
}

/** 有序的九分区定义（Basic / Model / Prompt / Skills / Tools / MCP / Knowledge / Memory / Permission）。 */
export const AGENT_STUDIO_PANELS: readonly AgentStudioPanelDef[] = [
  { id: "basic", label: "Basic", descriptionKey: "studio.panel.basic.description" },
  { id: "model", label: "Model", descriptionKey: "studio.panel.model.description" },
  { id: "prompt", label: "Prompt", descriptionKey: "studio.panel.prompt.description" },
  { id: "skills", label: "Skills", descriptionKey: "studio.panel.skills.description" },
  { id: "tools", label: "Tools", descriptionKey: "studio.panel.tools.description" },
  { id: "mcp", label: "MCP", descriptionKey: "studio.panel.mcp.description" },
  { id: "knowledge", label: "Knowledge", descriptionKey: "studio.panel.knowledge.description" },
  { id: "memory", label: "Memory", descriptionKey: "studio.panel.memory.description" },
  { id: "permission", label: "Permission", descriptionKey: "studio.panel.permission.description" },
] as const;

/**
 * Studio 草稿（跨面板合成的 Agent 配置）。
 *
 * 面板各自编辑本草稿的一个片段；发布时经 {@link draftToPublishRequest} 合成
 * `PublishRequest`（一次发布 = 一个新 `agent_version`，不可变快照）。
 */
export interface AgentStudioDraft {
  /** System Prompt（↔ `agent_version.system_prompt`）。 */
  systemPrompt: string;
  /** 模型配置（↔ `agent_version.model_config`）。 */
  modelConfig: Record<string, unknown>;
  /** 运行时配置（↔ `agent_version.runtime_config`）。 */
  runtimeConfig: Record<string, unknown>;
  /** 绑定的 Skill id 集合。 */
  skillIds: string[];
  /** 绑定的 Tool id 集合。 */
  toolIds: string[];
  /** 绑定的 MCP Server id 集合。 */
  mcpServerIds: string[];
  /** 绑定的 KnowledgeBase id 集合。 */
  knowledgeBaseIds: string[];
  /** 记忆作用域（↔ `memory.scope_type`）。 */
  memoryScope: string;
  /** 权限声明（capability 列表）。 */
  declaredCapabilities: string[];
}

/** 构造**空**草稿（Studio 初始态 / 新建 Agent 时使用）。 */
export function createEmptyAgentStudioDraft(): AgentStudioDraft {
  return {
    systemPrompt: "",
    modelConfig: {},
    runtimeConfig: {},
    skillIds: [],
    toolIds: [],
    mcpServerIds: [],
    knowledgeBaseIds: [],
    memoryScope: "user",
    declaredCapabilities: [],
  };
}

/** 防御式取字符串数组（跳过非字符串项）。 */
function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

/** 由既有版本快照还原一份草稿（选中 Agent 时载入其当前版本）。 */
export function agentVersionToDraft(version: AgentVersionResponse): AgentStudioDraft {
  const runtime = version.runtime_config ?? {};
  return {
    systemPrompt: version.system_prompt ?? "",
    modelConfig: { ...(version.model_config ?? {}) },
    runtimeConfig: { ...runtime },
    skillIds: asStringArray(runtime.skill_ids),
    toolIds: asStringArray(runtime.tool_ids),
    mcpServerIds: asStringArray(runtime.mcp_server_ids),
    knowledgeBaseIds: asStringArray(runtime.knowledge_base_ids),
    memoryScope: typeof runtime.memory_scope === "string" ? runtime.memory_scope : "user",
    declaredCapabilities: asStringArray(runtime.capabilities),
  };
}

/**
 * 由草稿合成发布请求（跨面板配置的**单点**合成）。
 *
 * Skill / MCP / Knowledge 绑定与权限声明落在 `runtime_config`（既有载荷），
 * Tool 绑定落在 `tools`（↔ `agent_version` ↔ Tool 绑定）；不新增后端契约。
 */
export function draftToPublishRequest(draft: AgentStudioDraft): PublishRequest {
  return {
    system_prompt: draft.systemPrompt,
    model_config: { ...draft.modelConfig },
    runtime_config: {
      ...draft.runtimeConfig,
      skill_ids: [...draft.skillIds],
      tool_ids: [...draft.toolIds],
      mcp_server_ids: [...draft.mcpServerIds],
      knowledge_base_ids: [...draft.knowledgeBaseIds],
      memory_scope: draft.memoryScope,
      capabilities: [...draft.declaredCapabilities],
    },
    tools: draft.toolIds.map((toolId) => ({
      tool_id: toolId,
      enabled: true,
      permission_scope: {},
    })),
  };
}

/** Studio 面板组件的统一入参（各面板编辑草稿的各自片段）。 */
export interface AgentStudioPanelProps {
  /** 当前选中的 Agent（未选中为 `null`）。 */
  agent: AgentResponse | null;
  /** 当前 Studio 草稿。 */
  draft: AgentStudioDraft;
  /** 局部更新草稿（浅合并）。 */
  onDraftChange: (patch: Partial<AgentStudioDraft>) => void;
  /** 统一反馈通道（面板经此上报成功 / 失败信息）。 */
  onFeedback: (message: string) => void;
}
