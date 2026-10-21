// @wbtime/domain · W1 **首日冻结**的五个端口签名（`T3-04` 产出）。
//
// 为什么放在域层：这些是「运行时能做什么」的抽象，**不是实现**。域层只声明形状，
// 由 `apps/api` / `packages/*` 提供 adapter。这样 T3-02（ModelGateway）、T3-09
// （AgentLoop）、T3-10（ToolExecutor）可以并行落地而**不需要互相 import**。
//
// 冻结纪律（任务卡 T3-04 验收口径 ④）：本文件被 T3-02/T3-09/T3-10 引用后**零改动**；
// 需要新增能力时**新增端口**，不改既有签名（否则 W1 并行失效）。
//
// 零 ORM / 零 Web import；`AbortSignal` 来自 Node 全局类型。

import type { BudgetLedger } from "./budget-ledger.js";

/**
 * 一次调用必须携带的上下文（Harness §1-4：run 身份 / 执行权限 / 取消令牌 / 截止时间 / 预算账本，缺一不可）。
 */
export interface RunCallContext {
  readonly runId: string;
  readonly tenantId: string;
  /** 取消令牌：取消传播与超时都经它，adapter 不得自建定时器绕过。 */
  readonly signal: AbortSignal;
  /** **绝对**截止时刻（epoch ms），由活动时钟换算，不是剩余时长。 */
  readonly deadlineMs: number;
  readonly budget: BudgetLedger;
  /** 该 run 已授予的权限码（工具/模型 adapter 只做粗筛，最终裁决在 SafetyGate）。 */
  readonly permissions: readonly string[];
  /** `policy_version` 快照（子 run 继承父快照 —— S3 语义）。 */
  readonly policyVersion: string;
}

// ---------------------------------------------------------------------------
// 1. ModelGatewayPort —— 唯一执行方法是 `stream()`
// ---------------------------------------------------------------------------

export type ModelRole = "system" | "user" | "assistant" | "tool";

/**
 * 一次工具调用请求（assistant 消息携带）。
 *
 * 加它是因为 **D-T302-1**：原端口只能表达"文本消息"，无法表达"模型请求了哪些工具"，
 * 工具回路的往返因此在类型上不可表达。字段全是可选 ⇒ 对既有调用方零影响。
 */
export interface ModelToolCall {
  readonly id: string;
  readonly name: string;
  /** 模型给出的入参（JSON 值；由 ToolExecutor 校验，域层不解释）。 */
  readonly input: unknown;
}

export interface ModelMessage {
  readonly role: ModelRole;
  readonly content: string;
  /** `role="tool"` 时必填：对应的 tool call id。 */
  readonly toolCallId?: string;
  /**
   * `role="tool"` 时**应填**：产生该结果的工具名。
   *
   * AI SDK v4 的 `tool-result` 分片要求 `toolName`；缺它上游认不出结果属于哪个工具
   * （见 D-T302-1）。可选是为了保持向后兼容 —— 缺省时适配器会退回占位值，但那只是
   * 兼容路径，**真实工具回路必须填**。
   */
  readonly toolName?: string;
  /**
   * `role="assistant"` 时填：本轮模型请求的工具调用。
   *
   * 与 `toolName` 配对使用，才能把"请求 → 执行 → 回传"整条链表达完整。
   */
  readonly toolCalls?: readonly ModelToolCall[];
}

export interface ModelToolSpec {
  readonly name: string;
  readonly description?: string;
  /** JSON Schema（工具入参）；由 ToolExecutor 注册表提供，域层不解释其内容。 */
  readonly inputSchema: Readonly<Record<string, unknown>>;
}

export interface ModelRequest {
  readonly model: string;
  readonly messages: readonly ModelMessage[];
  readonly tools?: readonly ModelToolSpec[];
  readonly maxOutputTokens?: number;
  readonly temperature?: number;
}

/** 流式分片。`usage` 与 `finish` 是**终态帧**，一个流各至多一次。 */
export type ModelChunk =
  | { readonly type: "text_delta"; readonly text: string }
  | {
      readonly type: "usage";
      readonly tokensIn: number;
      readonly tokensOut: number;
      /** 提示词缓存命中量（可选键；不提供 ≠ 0，见 V0.3.0 缓存观测口径）。 */
      readonly cacheReadTokens?: number;
    }
  | { readonly type: "finish"; readonly reason?: string };

/**
 * 模型网关：**只有 `stream()` 一个方法**（R3-10）。
 *
 * 不提供 `complete()` / `resume()` —— 非流式由调用方聚合；resume 归 run 层（重放）。
 */
export interface ModelGatewayPort {
  stream(request: ModelRequest, context: RunCallContext): AsyncIterable<ModelChunk>;
}

// ---------------------------------------------------------------------------
// 2. ToolExecutorPort —— 执行一次工具调用
// ---------------------------------------------------------------------------

export interface ToolInvocation {
  readonly callId: string;
  readonly toolName: string;
  readonly input: unknown;
}

/** 执行结果的状态集**与 `tool_call.status` 的终态子集一致**（不含 PENDING/RUNNING）。 */
export interface ToolExecutionResult {
  readonly status: "SUCCESS" | "FAILED" | "DENIED" | "CANCELLED" | "UNKNOWN";
  readonly output?: unknown;
  readonly error?: string;
  readonly exitCode?: number;
  readonly durationMs: number;
}

export interface ToolExecutorPort {
  execute(invocation: ToolInvocation, context: RunCallContext): Promise<ToolExecutionResult>;
}

// ---------------------------------------------------------------------------
// 3. RunEventWriterPort —— 事件落盘（seq 由实现分配）
// ---------------------------------------------------------------------------

export interface RunEventDraft {
  /** 事件类型（19 通道之一，或内部 `agent_event` 行）。 */
  readonly type: string;
  readonly payload: Readonly<Record<string, unknown>>;
}

export interface RunEventWriterPort {
  /**
   * 追加一条事件，返回分配到的 `seq`（严格单调，Harness §1-3）。
   *
   * 实现负责：同一 run 的单写者约束（lease）、seq 冲突检测、终态后拒写。
   */
  append(runId: string, event: RunEventDraft): Promise<number>;
}

// ---------------------------------------------------------------------------
// 4. SafetyPort —— 内容安全裁决（七挂点共用）
// ---------------------------------------------------------------------------

export type SafetyStage = "input" | "tool_result" | "output";

export interface SafetyRequest {
  readonly stage: SafetyStage;
  readonly content: string;
}

export type SafetyAction = "ALLOW" | "DENY" | "REDACT" | "REQUIRE_APPROVAL";

export interface SafetyDecision {
  readonly action: SafetyAction;
  /** 拒绝/脱敏的原因码（写 `audit_log`，不改错误码枚举）。 */
  readonly reasonCode?: string;
  /** `action="REDACT"` 时的同源脱敏结果（R16：检测集合 == 脱敏集合）。 */
  readonly redactedContent?: string;
}

export interface SafetyPort {
  evaluate(request: SafetyRequest, context: RunCallContext): Promise<SafetyDecision>;
}

// ---------------------------------------------------------------------------
// 5. SandboxPort —— 代码执行沙箱
// ---------------------------------------------------------------------------

export type ExecRuntime = "python" | "node" | "bash";

export interface ExecRequest {
  readonly runtime: ExecRuntime;
  readonly code: string;
  /** 单次执行超时；缺省由 `sandbox.exec.default_timeout_ms` 决定。 */
  readonly timeoutMs?: number;
}

export interface ExecResult {
  /** 进程退出码；超时固定 **124**（与 py 线 `TIMEOUT_EXIT_CODE` 等价，R3-18 E3）。 */
  readonly exitCode: number;
  /** 已按 `sandbox.exec.max_output_chars` 截断（**字符**，非字节）；R3-18 E6。 */
  readonly stdout: string;
  readonly stderr: string;
  readonly truncated: boolean;
  readonly durationMs: number;
}

export interface SandboxPort {
  exec(request: ExecRequest, context: RunCallContext): Promise<ExecResult>;
}
