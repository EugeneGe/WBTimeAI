// ---------------------------------------------------------------------------
// WBTimeAI · 前端单测 msw handlers（T1-01 / P0-09 + W7 / T1-35）
//
// 提供**冒烟级**基础 handler（`/api/v1/health`）与 **Phase 1 契约 handler**
// （Agents / Models / Tools / Workspaces / Conversations），并导出 **SSE 流工具**：
//
//   - `shell(data, status)`：统一响应壳 JSON（成功 `code=0`）；
//   - `sseFrame({id,event,data})`：编码单个 SSE 帧（`id:` / `event:` / `data:` + 空行）；
//   - `sseResponse(frames)`：由帧数组构造 `text/event-stream` 流式响应。
//
// 🔴 SSE 为 `text/event-stream`，**不套响应壳**（对齐后端 `ResponseShellMiddleware`）。
// ---------------------------------------------------------------------------
import { HttpResponse, http } from "msw";

/** 统一响应壳 JSON 响应（成功 `code=0`，`data` 为业务 DTO）。 */
export function shell<T>(data: T, status = 200) {
  return HttpResponse.json(
    { code: 0, message: "ok", data, request_id: "test-request" },
    { status },
  );
}

/** 单条 SSE 帧载荷。 */
export interface SseFrameInput {
  id?: number;
  event?: string;
  data?: Record<string, unknown> | string;
  /** 注释帧内容（如心跳 `hb 123`）——给定则忽略 `id` / `event` / `data`。 */
  comment?: string;
}

/** 编码单个 SSE 帧（含结尾空行）。 */
export function sseFrame(input: SseFrameInput): string {
  if (input.comment !== undefined) {
    return `: ${input.comment}\n\n`;
  }
  const lines: string[] = [];
  if (input.id !== undefined) {
    lines.push(`id: ${input.id}`);
  }
  if (input.event !== undefined) {
    lines.push(`event: ${input.event}`);
  }
  if (input.data !== undefined) {
    const body = typeof input.data === "string" ? input.data : JSON.stringify(input.data);
    lines.push(`data: ${body}`);
  }
  return `${lines.join("\n")}\n\n`;
}

/**
 * 由帧数组构造 `text/event-stream` 流式响应。
 *
 * 每帧经独立 `enqueue` 推送（模拟网络分片），全部推完后 `close()`。
 */
export function sseResponse(frames: string[]) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame));
      }
      controller.close();
    },
  });
  return new HttpResponse(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

// -- 契约夹具（与后端 schema 对齐） -----------------------------------------

const PROVIDER = {
  id: "p1",
  tenant_id: "t1",
  workspace_id: null,
  name: "OpenAI",
  type: "openai",
  endpoint: null,
  credential_id: null,
  status: "ACTIVE",
  config: {},
  created_at: null,
};

const MODEL = {
  id: "m1",
  tenant_id: "t1",
  provider_id: "p1",
  name: "gpt-4o-mini",
  type: "CHAT",
  context_window: 128000,
  capabilities: {},
  status: "ACTIVE",
  created_at: null,
};

/** 5 个内置 Tool（与设计 §2.15.1 `tool.name` 对齐）。 */
export const BUILTIN_TOOLS = [
  {
    id: "tool-filesystem",
    name: "filesystem",
    display_name: "文件系统",
    description: "读写工作区文件",
    category: "fs",
    type: "builtin",
    requires_sandbox: true,
    input_schema: {},
  },
  {
    id: "tool-shell",
    name: "shell",
    display_name: "Shell",
    description: "执行 Shell 命令",
    category: "exec",
    type: "builtin",
    requires_sandbox: true,
    input_schema: {},
  },
  {
    id: "tool-git",
    name: "git",
    display_name: "Git",
    description: "版本控制操作",
    category: "vcs",
    type: "builtin",
    requires_sandbox: true,
    input_schema: {},
  },
  {
    id: "tool-http",
    name: "http",
    display_name: "HTTP",
    description: "发起 HTTP 请求",
    category: "net",
    type: "builtin",
    requires_sandbox: false,
    input_schema: {},
  },
  {
    id: "tool-python",
    name: "python",
    display_name: "Python",
    description: "运行 Python 代码",
    category: "exec",
    type: "builtin",
    requires_sandbox: true,
    input_schema: {},
  },
];

const WORKSPACE = {
  id: "w1",
  tenant_id: "t1",
  owner_id: "u1",
  name: "Demo Workspace",
  workspace_type: "local",
  settings: {},
  config: {},
  created_at: null,
  updated_at: null,
};

/** 默认创建的 Agent 夹具。 */
export const AGENT = {
  id: "a1",
  tenant_id: "t1",
  name: "Coder",
  workspace_id: "w1",
  description: null,
  type: "PRIMARY",
  status: "DRAFT",
  current_version_id: null,
  created_by: "u1",
  created_at: null,
  updated_at: null,
};

/** 默认 SSE 运行脚本（happy path：started → 两段 delta → completed）。 */
export const DEFAULT_RUN_SCRIPT = [
  sseFrame({
    id: 1,
    event: "agent.started",
    data: { run_id: "run-1", agent_id: "a1", version: "1" },
  }),
  sseFrame({
    id: 2,
    event: "message.delta",
    data: { run_id: "run-1", message_id: "m1", delta: "Hel" },
  }),
  sseFrame({
    id: 3,
    event: "message.delta",
    data: { run_id: "run-1", message_id: "m1", delta: "lo" },
  }),
  sseFrame({
    id: 4,
    event: "agent.completed",
    data: { run_id: "run-1", token_usage: {}, cost: 0 },
  }),
];

// -- Phase 2b / W6（T2-35）：Workflow / Knowledge / Memory 契约夹具 ----------

/** Workflow 夹具。 */
export const WORKFLOW = {
  id: "wf1",
  tenant_id: "t1",
  workspace_id: null,
  name: "Onboarding",
  description: null,
  status: "DRAFT",
  current_version_id: null,
  created_by: "u1",
  created_at: null,
  updated_at: null,
};

/** WorkflowVersion 夹具（含 8 类节点之一 + 一条边）。 */
export const WORKFLOW_VERSION = {
  id: "wfv1",
  workflow_id: "wf1",
  version: "v1",
  status: "PUBLISHED",
  definition: {
    nodes: [
      { key: "n1", type: "AGENT", config: {}, position: { x: 80, y: 60 } },
      { key: "n2", type: "END", config: {}, position: { x: 260, y: 60 } },
    ],
    edges: [{ from: "n1", to: "n2", condition: null }],
    entry: "n1",
  },
  created_by: "u1",
  created_at: null,
};

/**
 * `POST /workflows/{id}/run` 的**裸 JSON** 摘要夹具（↔ 后端 `_json_run_digest`）。
 *
 * 🔴 该响应**不套统一响应壳**（`Accept: application/json` 的 JSON 降级分支）。
 */
export const WORKFLOW_RUN_DIGEST = {
  run_id: "wfrun-a1b2",
  workflow_version_id: "wfv1",
  status: "SUCCEEDED",
  task_id: "task-wf1",
  error: null,
};

/** WorkflowRun 重放快照夹具（2 个节点：`SUCCEEDED` / `SKIPPED`，整体 `SUCCEEDED`）。 */
export const WORKFLOW_RUN = {
  run_id: "wfrun-a1b2",
  workflow_id: "wf1",
  workflow_version_id: "wfv1",
  status: "SUCCEEDED",
  trigger: "user",
  input: {},
  output: { ok: true },
  error: null,
  nodes: [
    {
      id: "wfnr1",
      workflow_run_id: "wfrun-a1b2",
      node_key: "n1",
      status: "SUCCEEDED",
      attempt: 1,
      agent_run_id: "ar1",
      tool_call_id: null,
      approval_id: null,
      input: {},
      output: { done: true },
      started_at: "2026-10-18T10:00:00",
      completed_at: "2026-10-18T10:00:02",
    },
    {
      id: "wfnr2",
      workflow_run_id: "wfrun-a1b2",
      node_key: "n2",
      status: "SKIPPED",
      attempt: 1,
      agent_run_id: null,
      tool_call_id: null,
      approval_id: null,
      input: {},
      output: {},
      started_at: "2026-10-18T10:00:02",
      completed_at: "2026-10-18T10:00:02",
    },
  ],
  task_id: "task-wf1",
  started_at: "2026-10-18T10:00:00",
  completed_at: "2026-10-18T10:00:02",
};

/** 取消运行响应夹具（↔ `WorkflowRunResponse`）。 */
export const WORKFLOW_RUN_DETAIL = {
  id: "wfrun-a1b2",
  tenant_id: "t1",
  workflow_version_id: "wfv1",
  trigger: "user",
  status: "CANCELLED",
  task_id: "task-wf1",
  input: {},
  output: null,
  started_at: "2026-10-18T10:00:00",
  completed_at: "2026-10-18T10:00:01",
  error: null,
};

/** KnowledgeBase 夹具。 */
export const KNOWLEDGE_BASE = {
  id: "kb1",
  tenant_id: "t1",
  workspace_id: null,
  name: "Handbook",
  description: null,
  embedding_model: {},
  chunk_config: {},
  status: "ACTIVE",
  created_by: "u1",
  created_at: null,
};

/** Document 夹具（`status` 供进度展示）。 */
export const DOCUMENT = {
  id: "doc1",
  knowledge_base_id: "kb1",
  title: "guide.md",
  source_type: "text",
  storage_key: null,
  mime: null,
  size: null,
  checksum: null,
  status: "READY",
  error: null,
  task_id: null,
  created_at: null,
};

/** 检索试跑响应夹具（关键字路 + 一条命中）。 */
export const SEARCH_RESULT = {
  query: "hello",
  mode: "keyword",
  kb_ids: ["kb1"],
  hits: [
    {
      chunk_id: "chk1",
      content: "Hello world",
      score: 0.42,
      source: "doc1",
      metadata: { mode: "fts", document_id: "doc1", ordinal: 0 },
    },
  ],
};

/** 本人信息夹具（B-17：工作台 / 设置·个人四格只读信息）。 */
export const USER = {
  id: "usr_01a13e2e",
  tenant_id: "t1",
  username: "admin",
  email: "admin@local.dev",
  display_name: null,
  is_active: true,
  is_superuser: true,
  created_at: null,
};

/** 设备会话夹具（B-17：2 活跃 + 1 已撤销；`device` 空项验证 `user_agent` 兜底）。 */
export const DEVICES = [
  {
    id: "dev1",
    device: "Chrome · Windows",
    ip_address: "127.0.0.1",
    user_agent: "Mozilla/5.0 (Windows NT 10.0) Chrome/126.0",
    created_at: "2026-10-18T10:00:00",
    expires_at: null,
    revoked_at: null,
  },
  {
    id: "dev2",
    device: null,
    ip_address: "127.0.0.1",
    user_agent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/126.0 Safari/537.36",
    created_at: "2026-10-17T15:32:00",
    expires_at: null,
    revoked_at: null,
  },
  {
    id: "dev3",
    device: "Firefox · Windows",
    ip_address: "127.0.0.1",
    user_agent: "Mozilla/5.0 (Windows NT 10.0) Firefox/128.0",
    created_at: "2026-10-17T15:32:00",
    expires_at: null,
    revoked_at: "2026-10-17T16:00:00",
  },
];

/** Memory 夹具（含来源 Run）。 */
export const MEMORY = {
  id: "mem1",
  tenant_id: "t1",
  workspace_id: null,
  kind: "LONG_TERM",
  scope_type: "user",
  scope_id: "u1",
  visibility: "private",
  content: "用户偏好深色主题",
  memory_type: "preference",
  importance: 0.8,
  confidence: 0.9,
  source_run_id: "run-1",
  expires_at: null,
  created_at: null,
};

export const handlers = [
  // 后端 /health 直接暴露；/api/v1/... 走统一响应壳 { code, message, data }。
  // 注意：保留**最小三字段**形态，供既有冒烟测试 `toEqual` 精确断言（勿追加 request_id）。
  http.get("/api/v1/health", () =>
    HttpResponse.json({ code: 0, message: "ok", data: { status: "ok" } }),
  ),

  // -- Models（T1-34） ------------------------------------------------------
  http.get("/api/v1/models/providers", () => shell([PROVIDER])),
  http.get("/api/v1/models/providers/:providerId/models", () => shell([MODEL])),
  http.get("/api/v1/models/credentials", () => shell([])),
  http.post("/api/v1/models/credentials", () =>
    shell(
      {
        id: "c1",
        provider: "openai",
        key_type: "api_key",
        masked_value: "sk-****1234",
        workspace_id: null,
        created_at: null,
      },
      201,
    ),
  ),

  // -- Tools（T1-34） -------------------------------------------------------
  http.get("/api/v1/tools", () => shell(BUILTIN_TOOLS)),
  http.get("/api/v1/tools/permissions", () => shell([])),

  // -- Workspaces（复用） ---------------------------------------------------
  http.get("/api/v1/workspaces", () => shell([WORKSPACE])),

  // -- Agents（T1-33） ------------------------------------------------------
  http.get("/api/v1/agents", () => shell([AGENT])),
  http.get("/api/v1/agents/:agentId/versions", () => shell([])),
  http.post("/api/v1/agents", () => shell(AGENT, 201)),
  http.post("/api/v1/agents/:agentId/publish", () =>
    shell(
      {
        id: "v1",
        agent_id: "a1",
        version: "1",
        system_prompt: "",
        model_config: {},
        runtime_config: {},
        status: "PUBLISHED",
        created_by: "u1",
        created_at: null,
      },
      201,
    ),
  ),

  // -- Conversations（T1-32） ----------------------------------------------
  http.get("/api/v1/conversations", () => shell([])),
  http.get("/api/v1/conversations/:conversationId/messages", () => shell([])),

  // -- Run（SSE，T1-32 / T1-35） -------------------------------------------
  // 默认 happy path：POST 运行 → SSE 帧；测试可 `server.use(...)` 覆盖为断连场景。
  http.post("/api/v1/agents/:agentId/run", () => sseResponse(DEFAULT_RUN_SCRIPT)),
  http.get("/api/v1/runs/:runId/events", () => sseResponse([])),

  // -- Workflow（W4 / T2-25 契约；W6 / T2-35 前端） -------------------------
  http.get("/api/v1/workflows", () => shell([WORKFLOW])),
  http.post("/api/v1/workflows", () => shell(WORKFLOW, 201)),
  http.get("/api/v1/workflows/:workflowId/versions", () => shell([WORKFLOW_VERSION])),
  http.post("/api/v1/workflows/:workflowId/publish", () => shell(WORKFLOW_VERSION, 201)),
  // 运行闭环（`/run` 为**裸 JSON**；重放 / 取消走统一响应壳）。
  http.post("/api/v1/workflows/:workflowId/run", () => HttpResponse.json(WORKFLOW_RUN_DIGEST)),
  http.get("/api/v1/workflows/:workflowId/runs/:runId", () => shell(WORKFLOW_RUN)),
  http.post("/api/v1/workflows/:workflowId/runs/:runId/cancel", () => shell(WORKFLOW_RUN_DETAIL)),

  // -- Knowledge（W6 / T2-35） ---------------------------------------------
  http.get("/api/v1/knowledge/bases", () => shell([KNOWLEDGE_BASE])),
  http.post("/api/v1/knowledge/bases", () => shell(KNOWLEDGE_BASE, 201)),
  http.get("/api/v1/knowledge/bases/:knowledgeBaseId/documents", () => shell([DOCUMENT])),
  http.post("/api/v1/knowledge/bases/:knowledgeBaseId/documents", () => shell(DOCUMENT, 201)),
  http.post("/api/v1/knowledge/search", () => shell(SEARCH_RESULT)),

  // -- Auth / 本人信息 / 设备会话（B-17） ------------------------------------
  http.get("/api/v1/users/me", () => shell(USER)),
  http.put("/api/v1/users/me", () => shell(USER)),
  http.get("/api/v1/users/me/devices", () => shell(DEVICES)),
  http.get("/api/v1/settings/personal", () =>
    shell({ user_id: USER.id, username: USER.username, email: USER.email, display_name: null }),
  ),

  // -- Memory（W6 / T2-35） ------------------------------------------------
  http.get("/api/v1/memory", () => shell([MEMORY])),
  http.delete("/api/v1/memory/:memoryId", () => new HttpResponse(null, { status: 204 })),
];
