// @generated —— 由 scripts/gen_platform_contracts.mjs 从 contracts/sse/channels.json 生成。
// 请勿手改。
//
// contract_version: 1
// channels_digest_sha256: 9edda3baea0cee3a7bf0fb9aa4036fe90b0423797141ab5936abdd1d2e350fc5
// 通道数量（实测，以读取为准）: 19
// payload 键序 = payload_keys_in_order：TS 侧必须保序（契约键序 == 插入序）。

/** 全部 SSE 通道（19 条正式通道；浮点归一化 guard 帧不在内）。 */
export const SSE_CHANNELS = {
  AGENT_STARTED: "agent.started",
  AGENT_THINKING: "agent.thinking",
  MESSAGE_DELTA: "message.delta",
  TOOL_STARTED: "tool.started",
  TOOL_COMPLETED: "tool.completed",
  MCP_STARTED: "mcp.started",
  MCP_COMPLETED: "mcp.completed",
  AGENT_COMPLETED: "agent.completed",
  AGENT_ERROR: "agent.error",
  SKILL_RESOLVED: "skill.resolved",
  WORKFLOW_STARTED: "workflow.started",
  WORKFLOW_NODE_STARTED: "workflow.node.started",
  WORKFLOW_NODE_COMPLETED: "workflow.node.completed",
  WORKFLOW_COMPLETED: "workflow.completed",
  WORKFLOW_FAILED: "workflow.failed",
  KNOWLEDGE_INDEXED: "knowledge.indexed",
  MEMORY_WRITTEN: "memory.written",
  APPROVAL_REQUESTED: "approval.requested",
  APPROVAL_DECIDED: "approval.decided",
} as const;

export type SseChannel = (typeof SSE_CHANNELS)[keyof typeof SSE_CHANNELS];

/** 稳定顺序（契约 index 升序）的通道清单，供门禁逐项比对。 */
export const SSE_CHANNEL_LIST: readonly SseChannel[] = [
  "agent.started",
  "agent.thinking",
  "message.delta",
  "tool.started",
  "tool.completed",
  "mcp.started",
  "mcp.completed",
  "agent.completed",
  "agent.error",
  "skill.resolved",
  "workflow.started",
  "workflow.node.started",
  "workflow.node.completed",
  "workflow.completed",
  "workflow.failed",
  "knowledge.indexed",
  "memory.written",
  "approval.requested",
  "approval.decided",
];

/** 单通道规格：payload 键序是契约的一部分（sort_keys=False，字节可比的前提）。 */
export interface SseChannelSpec {
  readonly channel: string;
  readonly eventClass: string;
  readonly domainType: string;
  readonly phase: string;
  readonly payloadKeysInOrder: readonly string[];
}

export const SSE_CHANNEL_SPECS: Readonly<Record<string, SseChannelSpec>> = {
  "agent.started": {
    channel: "agent.started",
    eventClass: "AgentStarted",
    domainType: "agent.started",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "agent_id",
      "agent_version_id",
      "conversation_id",
      "run_mode",
    ],
  },
  "agent.thinking": {
    channel: "agent.thinking",
    eventClass: "AgentThinking",
    domainType: "agent.thinking",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "iteration",
    ],
  },
  "message.delta": {
    channel: "message.delta",
    eventClass: "AgentMessage",
    domainType: "agent.message",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "message_id",
      "role",
      "content",
    ],
  },
  "tool.started": {
    channel: "tool.started",
    eventClass: "ToolCallStarted",
    domainType: "tool_call.started",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "tool_call_id",
      "tool_name",
      "attempt",
      "arguments",
    ],
  },
  "tool.completed": {
    channel: "tool.completed",
    eventClass: "ToolCallCompleted",
    domainType: "tool_call.completed",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "tool_call_id",
      "tool_name",
      "status",
      "duration_ms",
      "error",
    ],
  },
  "mcp.started": {
    channel: "mcp.started",
    eventClass: "MCPCallStarted",
    domainType: "mcp_call.started",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "mcp_call_id",
      "server",
      "tool_name",
    ],
  },
  "mcp.completed": {
    channel: "mcp.completed",
    eventClass: "MCPCallCompleted",
    domainType: "mcp_call.completed",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "mcp_call_id",
      "server",
      "status",
      "duration_ms",
      "error",
    ],
  },
  "agent.completed": {
    channel: "agent.completed",
    eventClass: "AgentCompleted",
    domainType: "agent.completed",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "duration_ms",
      "iterations",
    ],
  },
  "agent.error": {
    channel: "agent.error",
    eventClass: "AgentFailed",
    domainType: "agent.failed",
    phase: "core",
    payloadKeysInOrder: [
      "run_id",
      "error_type",
      "error",
      "duration_ms",
    ],
  },
  "skill.resolved": {
    channel: "skill.resolved",
    eventClass: "SkillResolved",
    domainType: "skill.resolved",
    phase: "phase2",
    payloadKeysInOrder: [
      "skill_name",
      "skill_id",
      "version",
      "run_id",
    ],
  },
  "workflow.started": {
    channel: "workflow.started",
    eventClass: "WorkflowStarted",
    domainType: "workflow.started",
    phase: "phase2",
    payloadKeysInOrder: [
      "workflow_id",
      "run_id",
      "workflow_version_id",
    ],
  },
  "workflow.node.started": {
    channel: "workflow.node.started",
    eventClass: "WorkflowNodeStarted",
    domainType: "workflow.node.started",
    phase: "phase2",
    payloadKeysInOrder: [
      "workflow_id",
      "run_id",
      "node_id",
      "node_type",
    ],
  },
  "workflow.node.completed": {
    channel: "workflow.node.completed",
    eventClass: "WorkflowNodeCompleted",
    domainType: "workflow.node.completed",
    phase: "phase2",
    payloadKeysInOrder: [
      "workflow_id",
      "run_id",
      "node_id",
      "status",
      "duration_ms",
    ],
  },
  "workflow.completed": {
    channel: "workflow.completed",
    eventClass: "WorkflowCompleted",
    domainType: "workflow.completed",
    phase: "phase2",
    payloadKeysInOrder: [
      "workflow_id",
      "run_id",
      "duration_ms",
    ],
  },
  "workflow.failed": {
    channel: "workflow.failed",
    eventClass: "WorkflowFailed",
    domainType: "workflow.failed",
    phase: "phase2",
    payloadKeysInOrder: [
      "workflow_id",
      "run_id",
      "error_type",
      "error",
      "duration_ms",
    ],
  },
  "knowledge.indexed": {
    channel: "knowledge.indexed",
    eventClass: "KnowledgeIndexed",
    domainType: "knowledge.indexed",
    phase: "phase2",
    payloadKeysInOrder: [
      "kb_id",
      "document_id",
      "chunk_count",
      "status",
    ],
  },
  "memory.written": {
    channel: "memory.written",
    eventClass: "MemoryWritten",
    domainType: "memory.written",
    phase: "phase2",
    payloadKeysInOrder: [
      "memory_id",
      "scope",
      "key",
    ],
  },
  "approval.requested": {
    channel: "approval.requested",
    eventClass: "ApprovalRequested",
    domainType: "approval.requested",
    phase: "phase2",
    payloadKeysInOrder: [
      "approval_id",
      "subject_type",
      "subject_ref",
      "requested_by",
    ],
  },
  "approval.decided": {
    channel: "approval.decided",
    eventClass: "ApprovalDecided",
    domainType: "approval.decided",
    phase: "phase2",
    payloadKeysInOrder: [
      "approval_id",
      "status",
      "decided_by",
    ],
  },
};

/**
 * 数值上线策略（contracts/sse/channels.json → numeric_format）。
 * 目的：Python `json.dumps(1.0) == '1.0'` 而 JS `JSON.stringify(1.0) == '1'`，
 * 只要整数值浮点能上帧，「golden 帧逐字节相同」就原理上不可达，故定死为
 * 「线上只走整数」，非整数浮点转定点十进制字符串。
 */
export const NUMERIC_FORMAT_POLICY = "integers-only-on-the-wire";
export const NUMERIC_FORMAT_RULE_VERSION = 1;
/** 定点十进制字符串的小数位数（从契约 example 解析，非硬编码）。 */
export const NUMERIC_FIXED_DECIMALS = 6;
