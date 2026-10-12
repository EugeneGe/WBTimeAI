import { QueryClient } from "@tanstack/react-query";

/**
 * TanStack Query 客户端（**服务状态**的唯一真相源，D6）。
 *
 * - `retry: 1`：弱网下最多重试一次（刷新后的 401 重试由 `lib/api.ts` 承担）；
 * - `refetchOnWindowFocus: false`：避免频繁打扰；
 * - 统一 `staleTime`，减少抖动。
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
    mutations: {
      retry: 0,
    },
  },
});

/** 统一的 query key 工厂（集中管理，避免拼写漂移）。 */
export const queryKeys = {
  me: ["me"] as const,
  devices: ["devices"] as const,
  organizations: ["organizations"] as const,
  workspaces: ["workspaces"] as const,
  workspace: (id: string) => ["workspace", id] as const,
  system: ["system"] as const,
  personal: ["personal"] as const,
  credentials: ["credentials"] as const,
  features: ["features"] as const,
  // -- Phase 1 / W7（T1-32 ~ T1-34）-----------------------------------------
  agents: ["agents"] as const,
  agent: (id: string) => ["agent", id] as const,
  agentVersions: (id: string) => ["agent", id, "versions"] as const,
  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  conversationMessages: (id: string) => ["conversation", id, "messages"] as const,
  providers: ["model-providers"] as const,
  provider: (id: string) => ["model-providers", id] as const,
  providerModels: (id: string) => ["model-providers", id, "models"] as const,
  tools: ["tools"] as const,
  toolPermissions: (agentId: string) => ["tools", "permissions", agentId] as const,
  // -- Phase 2a / W3（T2-18）------------------------------------------------
  skills: ["skills"] as const,
  skill: (id: string) => ["skill", id] as const,
  skillVersions: (id: string) => ["skill", id, "versions"] as const,
  mcpServers: ["mcp", "servers"] as const,
  mcpServer: (id: string) => ["mcp", "servers", id] as const,
  mcpTools: (serverId?: string) =>
    serverId ? (["mcp", "tools", serverId] as const) : (["mcp", "tools"] as const),
  mcpPermissions: (toolId: string) => ["mcp", "permissions", toolId] as const,
  permissionCheck: (cap: string) => ["permissions", "check", cap] as const,
  // -- Phase 2b / W6（T2-35）：Workflow / Knowledge / Memory -----------------
  workflows: ["workflows"] as const,
  workflow: (id: string) => ["workflow", id] as const,
  workflowVersions: (id: string) => ["workflow", id, "versions"] as const,
  knowledgeBases: ["knowledge", "bases"] as const,
  knowledgeBase: (id: string) => ["knowledge", "bases", id] as const,
  documents: (knowledgeBaseId: string) =>
    ["knowledge", "bases", knowledgeBaseId, "documents"] as const,
  memories: (filter: string) => ["memory", filter] as const,
  // -- Phase 2c / W10（T2-50）：Projects / Files / Environment / Tasks / Schedules
  projects: (workspaceId: string) => ["projects", workspaceId] as const,
  project: (id: string) => ["project", id] as const,
  workspaceFiles: (workspaceId: string, prefix: string) =>
    ["workspace", workspaceId, "files", prefix] as const,
  workspaceEnvironments: (workspaceId: string) =>
    ["workspace", workspaceId, "environments"] as const,
  workspaceEnvironment: (workspaceId: string, environmentId: string) =>
    ["workspace", workspaceId, "environment", environmentId] as const,
  tasks: (filter: string) => ["tasks", filter] as const,
  task: (id: string) => ["task", id] as const,
  taskExecutions: (id: string) => ["task", id, "executions"] as const,
  schedules: ["schedules"] as const,
  // -- R4 / T2-62：远程工作台（Project Clone / 远程 Task / 审阅 / Apply / Push）--
  remoteTask: (id: string) => ["remote-task", id] as const,
  remoteAttempts: (id: string) => ["remote-task", id, "attempts"] as const,
  remoteEvents: (id: string, cursor: string) => ["remote-task", id, "events", cursor] as const,
  remoteLogs: (id: string) => ["remote-task", id, "logs"] as const,
  remoteDiff: (id: string, attempt: number) => ["remote-task", id, "diff", attempt] as const,
  remoteArtifacts: (id: string) => ["remote-task", id, "artifacts"] as const,
  projectStatus: (id: string) => ["project", id, "status"] as const,
  projectGitRefs: (id: string) => ["project", id, "git-refs"] as const,
};
