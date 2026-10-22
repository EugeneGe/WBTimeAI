/**
 * T3-14 · `RunDriver` —— **主链执行**（建 run → 装配 → 驱动九步内核 → 收敛终态）。
 *
 * 为什么需要这个文件（逐条对应四张卡的"遗留承接"）
 * ---------------------------------------------
 * | 遗留 | 施工前实测 | 本文件的落点 |
 * |---|---|---|
 * | T3-05/T3-08 | `runEntry()` 只做前置校验，返回 `execution:"deferred"` 回执，`agent_run` 计数不变 | {@link RunDriver.start} 真建 run 并**异步**驱动（HTTP 侧不等终态） |
 * | T3-10 #3 | `ToolExecutor` 全仓零实例化 | `#drive` 内每个 run 现建一个（沙箱会话按 runId 隔离） |
 * | T3-11 #1 | `createMcpToolAdapter()` 零调用点 | `tool-surface.buildToolSurface()`（本文件调用） |
 * | T3-13 #2 #3 | `SafetyGate` 零装配点、六个 stage 零调用者 | `safety/hooks.ts` 六挂点，本文件逐个接线 |
 *
 * 异步驱动（卡面「HTTP 侧不阻塞到终态」）
 * ---------------------------------
 *   `start()` 在**建完 run 行之后立即返回**，循环在后台推进：
 *   `void this.#drive(...)`（错误不外抛，全部折成 run 终态）。
 *   客户端随后经 `GET /runs/{id}` 看状态、`GET /runs/{id}/events` 收帧。
 *
 * 取消传播（"取消不复活"的落点）
 * -------------------------
 *   `RunCoordinator.cancel()` 先 `abortController.abort()` 再 CAS 落 `CANCELLED`。
 *   本文件在收尾前**重读 run 状态**：已是终态 ⇒ 直接返回，**不再 finalize**
 *   （否则一次晚到的 `SUCCEEDED` 会把 `CANCELLED` 覆盖成"复活"）。
 *
 * 终态与 `stop_reason` 的映射（R3-04 矩阵，**不自造码**）
 * ------------------------------------------------
 * | 内核终局 | run.status | stop_reason | 依据 |
 * |---|---|---|---|
 * | `SUCCEEDED` | `SUCCEEDED` | `model_finish` | 矩阵：`SUCCEEDED` 只允许这一个 |
 * | `FAILED` | `FAILED` | 内核给的（`budget_*` / `wall_time` / `tool_failed`） | 矩阵 |
 * | `CANCELLED` | `CANCELLED` | `cancelled` | 矩阵 |
 * | 审批驳回 | `CANCELLED` | `approval_rejected` | 矩阵：该码只在 `CANCELLED` 下合法 |
 * | 安全拦截（S2/S4/S7 DENY） | `FAILED` | `tool_failed` + `error_type=SAFETY_DENIED` | 11 值里**没有安全码**（R3-04 冻结），见 T3-14 施工记录偏差登记 |
 *
 * 安全六挂点的接线位置（逐点）
 * -----------------------
 *   S1 `input` —— {@link RunDriver.preflight}（**run 创建之前**；DENY ⇒ 422，run 不创建）
 *   S2 `context` —— `loadMessages` 包装（Prepare 之后、模型调用之前）
 *   S4 `model_request` —— 网关装饰器（真正 `stream()` 之前）
 *   S5 `tool_args` —— 执行器装饰器（intent 落盘后、`markRunning`/`execute` 之前）
 *   S6 `tool_result` —— 执行器装饰器（`execute` 返回后、observation 落库之前，先检查后截断）
 *   S7 `output` —— `appendAssistant` 包装（Commit turn 落库之前）
 *
 * 审批回路（卡面不变量「审批拒绝不进执行器」）
 * --------------------------------------
 *   `runtime_config.requires_approval` 命中工具名 ⇒ 建 `approval` 行 → 落
 *   `approval.requested` 帧 → run 迁 `WAITING_APPROVAL`（预算 `pause()`，R3-07：等待不吃
 *   墙钟）→ 轮询决议 → 落 `approval.decided` 帧 → 迁回 `RUNNING`（`resume()`）。
 *   **驳回 ⇒ 不调用 `ToolExecutor`**（`tool_call.DENIED` + 拒绝型 observation），
 *   并在收尾时把 run 收敛为 `CANCELLED` + `approval_rejected`。
 */

import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ERROR_CODES } from "@wbtime/core";
import {
  AgentRunRepo,
  ApprovalRepo,
  ConversationRepo,
  MessageRepo,
  Scope,
  SkillRepo,
  ToolCallRepo,
  instantLiteral,
  type AgentRunRow,
  type DrizzleDatabase,
  type MessageRow,
  type Scope as ScopeType,
  type SqlDialect,
} from "@wbtime/db";
import {
  BudgetLedger,
  isTerminalRunStatus,
  type ModelChunk,
  type ModelGatewayPort,
  type ModelMessage,
  type ModelRequest,
  type ModelToolCall,
  type RunCallContext,
  type StopReason,
  type ToolExecutionResult,
  type ToolExecutorPort,
  type ToolInvocation,
} from "@wbtime/domain";

import { authError } from "../auth/errors.js";
import { AgentLoop } from "../runtime/agent-loop.js";
import { GENERAL_HARNESS } from "../runtime/harness/general.js";
import {
  DEFAULT_STOP_LIMITS,
  toBudgetLimits,
  type StopLimits,
} from "../runtime/stop-conditions.js";
import { SAFETY_POLICY_VERSION, type SafetyGate, type SafetyVerdict } from "../safety/gate.js";
import { SafetyHooks, applyVerdict, isBlocked, type SampledContent } from "../safety/hooks.js";
import type { SandboxProvider } from "../sandbox/types.js";
import { ToolExecutor } from "../tool/executor.js";
import { RunCoordinator } from "./coordinator.js";
import { RunEventWriter, RunTerminalError } from "./event-writer.js";
import { buildToolSurface, toolTypeOf, type ToolSurface } from "./tool-surface.js";

/** 默认审批轮询间隔（ms）。 */
export const DEFAULT_APPROVAL_POLL_MS = 40;

/** 默认审批等待上限（ms）。超时 ⇒ 该工具按 `DENIED` 处理（**不执行**）。 */
export const DEFAULT_APPROVAL_TIMEOUT_MS = 15_000;

/** 默认上下文字符预算（超过 ⇒ `ContextBuilder` 压缩）。 */
export const DEFAULT_MAX_CONTEXT_CHARS = 12_000;

/** 默认保留的尾部消息数。 */
export const DEFAULT_KEEP_RECENT = 8;

/** `runtime_config.skills` 的元素形态（`string` 或 `{name, version?}`）。 */
type SkillRefConfig = string | { readonly name?: unknown; readonly version?: unknown };

/** 驱动依赖（装配一次，见 `app.ts::buildIdentityStack`）。 */
export interface RunDriverDeps {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
  readonly tenantId: string;
  /** 协调器（与 `RunService` **同一实例** —— 取消信号只有一份）。 */
  readonly coordinator: RunCoordinator;
  /**
   * 模型网关。**缺省 ⇒ run 入口 fail loud**（`CONFIGURATION_ERROR`）。
   * 未配置 ≠ 降级：没有网关就假装能跑，等于对外声称有模型能力。
   */
  readonly gateway?: ModelGatewayPort;
  /** 安全闸（缺省 ⇒ 六个挂点不生效，只在测试替身场景使用）。 */
  readonly safety?: SafetyGate;
  /** 沙箱（需沙箱的 3 个工具靠它；缺省 ⇒ 它们返回 `FAILED`，不回落宿主直执行）。 */
  readonly sandbox?: SandboxProvider;
  /** run 工作目录的根（缺省 `WBTIME_RUN_WORKSPACE_ROOT` 或 `os.tmpdir()/wbtime-runs`）。 */
  readonly workspaceRoot?: string;
  /** 出网白名单（`http` / `git clone` / MCP http）。 */
  readonly egressAllowlist?: readonly string[];
  /** 六项停止上限（缺省 {@link DEFAULT_STOP_LIMITS}）。 */
  readonly limits?: StopLimits;
  /** 工具单次超时（ms）。 */
  readonly toolTimeoutMs?: number;
  /** 时钟（测试注入）。 */
  readonly now?: () => Date;
  /** 审批轮询间隔（ms）。 */
  readonly approvalPollMs?: number;
  /** 审批等待上限（ms）。 */
  readonly approvalTimeoutMs?: number;
  /** S6 采样窗口（字符）。 */
  readonly resultSampleWindow?: number;
}

/** 一次 run 的启动入参（由 `AgentService.runEntry` 装配）。 */
export interface RunStartInput {
  readonly tenantId: string;
  readonly userId: string;
  readonly agentId: string;
  readonly agentVersionId: string;
  /** 版本的 `system_prompt`（进上下文第一条消息）。 */
  readonly systemPrompt: string;
  /** 版本的 `model_config`（取 `model` 键；缺省 `"default"`）。 */
  readonly modelConfig: Record<string, unknown>;
  /** 版本的 `runtime_config`（`harness` / `skills` / `requires_approval` / `limits`）。 */
  readonly runtimeConfig: Record<string, unknown>;
  /** 已有会话（续聊）；`null` ⇒ 新建。 */
  readonly conversationId: string | null;
  /** 工作区（新建会话必填；续聊可缺省）。 */
  readonly workspaceId: string | null;
  /** Agent 自身的工作区（`workspace_id` 入参缺省时的回落）。 */
  readonly agentWorkspaceId: string | null;
  readonly message: string;
  readonly requestId: string;
}

/** 启动结果（回执给 HTTP 侧）。 */
export interface RunStartResult {
  readonly run: AgentRunRow;
  readonly conversationId: string;
}

/** 安全拦截（S2/S4/S7 DENY）：抛出后被 `#drive` 折成 `FAILED` 终态。 */
export class SafetyBlockedError extends Error {
  readonly name = "SafetyBlockedError";
  readonly stage: string;
  readonly detail: string;

  constructor(stage: string, detail: string) {
    super(`安全拦截（${stage}）：${detail}`);
    this.stage = stage;
    this.detail = detail;
  }
}

/**
 * 一次 run 的可变标志（并发安全地由装饰器写、由收尾读）。
 *
 * 为什么不塞进 `RunCallContext`：那是 `@wbtime/domain` 的**冻结端口**（T3-04），
 * 往里加字段等于改冻结签名。本对象只活在一个 run 的内存里。
 */
interface RunFlags {
  approvalRejected: boolean;
  safetyBlockedStage: string | null;
  servedUnits: number;
}

/** 消息行 → 域模型消息（`content_parts` 反解工具调用/结果）。 */
export function toModelMessages(rows: readonly MessageRow[]): ModelMessage[] {
  const messages: ModelMessage[] = [];
  for (const row of rows) {
    const parts = Array.isArray(row.content_parts) ? (row.content_parts as unknown[]) : [];
    if (row.role === "tool") {
      const part = parts.find(
        (item): item is Record<string, unknown> =>
          typeof item === "object" &&
          item !== null &&
          (item as Record<string, unknown>).type === "tool_result"
      );
      messages.push({
        role: "tool",
        content: row.content,
        ...(typeof part?.callId === "string" ? { toolCallId: part.callId } : {}),
        ...(typeof part?.toolName === "string" ? { toolName: part.toolName } : {}),
      });
      continue;
    }
    if (row.role === "assistant") {
      const calls: ModelToolCall[] = [];
      for (const item of parts) {
        if (typeof item !== "object" || item === null) continue;
        const record = item as Record<string, unknown>;
        if (record.type !== "tool_call") continue;
        if (typeof record.id !== "string" || typeof record.name !== "string") continue;
        calls.push({ id: record.id, name: record.name, input: record.input });
      }
      messages.push({
        role: "assistant",
        content: row.content,
        ...(calls.length === 0 ? {} : { toolCalls: calls }),
      });
      continue;
    }
    if (row.role === "system") {
      messages.push({ role: "system", content: row.content });
      continue;
    }
    messages.push({ role: "user", content: row.content });
  }
  return messages;
}

/** 消息集合 → 单串（S2/S4 的判定载体；角色标签让注入模式可见）。 */
function flattenMessages(messages: readonly ModelMessage[]): string {
  return messages.map((message) => `[${message.role}] ${message.content}`).join("\n");
}

/**
 * 合成一条 `system` 消息行（把版本的 `system_prompt` 前置进上下文）。
 *
 * 为什么要有它：`system_prompt` 是**版本快照**，不在 `message` 表里；不前置就等于
 * "模型的系统提示词从未生效"（T3-14 施工前正是如此）。`id` 固定为
 * `system-prompt:<conversationId>`：回放时一眼能认出它不是用户消息。
 *
 * @param conversationId 会话 id（拼进合成 id）。
 * @param content 版本的系统提示词。
 * @returns 形状与 `MessageRow` 一致的合成行（其余列给 `null`）。
 */
function systemPromptRow(conversationId: string, content: string): MessageRow {
  return {
    id: `system-prompt:${conversationId}`,
    conversation_id: conversationId,
    run_id: null,
    role: "system",
    content,
    content_parts: null,
    token_count: null,
    created_at: "",
  } as unknown as MessageRow;
}

/** `runtime_config.skills` → 归一后的名字清单。 */
export function skillRefsOf(
  runtimeConfig: Record<string, unknown>
): { name: string; version?: string }[] {
  const raw = runtimeConfig.skills;
  if (!Array.isArray(raw)) return [];
  const refs: { name: string; version?: string }[] = [];
  for (const item of raw as SkillRefConfig[]) {
    if (typeof item === "string" && item.trim() !== "") {
      refs.push({ name: item.trim() });
      continue;
    }
    if (
      typeof item === "object" &&
      item !== null &&
      typeof item.name === "string" &&
      item.name.trim() !== ""
    ) {
      refs.push({
        name: item.name.trim(),
        ...(typeof item.version === "string" && item.version !== "" ? { version: item.version } : {}),
      });
    }
  }
  return refs;
}

/** `runtime_config.requires_approval` 命中判定（字符串数组；`"*"` = 全部工具）。 */
export function approvalRequiredFor(
  runtimeConfig: Record<string, unknown>,
  toolName: string
): boolean {
  const raw = runtimeConfig.requires_approval;
  if (!Array.isArray(raw)) return false;
  return (raw as unknown[]).some(
    (item) => typeof item === "string" && (item === "*" || item === toolName)
  );
}

/** 预算上限的版本级覆盖（`runtime_config.limits`，缺省用服务端缺省值）。 */
export function limitsOf(
  runtimeConfig: Record<string, unknown>,
  defaults: StopLimits = DEFAULT_STOP_LIMITS
): StopLimits {
  const raw = runtimeConfig.limits;
  const bag = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
  const pick = (key: keyof StopLimits): number => {
    const value = bag[key as string];
    return typeof value === "number" && Number.isFinite(value) && value > 0
      ? value
      : defaults[key];
  };
  return {
    maxModelTurns: pick("maxModelTurns"),
    maxToolCalls: pick("maxToolCalls"),
    maxToolCallsPerTurn: pick("maxToolCallsPerTurn"),
    maxWallTimeMs: pick("maxWallTimeMs"),
    maxTokens: pick("maxTokens"),
    maxCost: pick("maxCost"),
  };
}

/** 宽松 JSON 解析（失败回落原值 —— 脱敏文本理论上仍是 JSON，但不为此抛错）。 */
function safeJsonParse(text: string, fallback: unknown): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return fallback;
  }
}

/** 最小 sleep（不引入依赖）。 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/**
 * 主链执行器。
 *
 * 一个实例可服务多个并发 run：run 级状态全部是 `#drive` 的局部变量，
 * 共享的只有 `#inflight`（runId → 收尾 promise）这张表。
 */
export class RunDriver {
  readonly #deps: RunDriverDeps;
  readonly #inflight = new Map<string, Promise<void>>();

  constructor(deps: RunDriverDeps) {
    this.#deps = deps;
  }

  /** 本实例的租户（与 `RunService` 同源；用于构造仓储 scope）。 */
  get tenantId(): string {
    return this.#deps.tenantId;
  }

  /** 是否装配了模型网关（缺省 ⇒ run 入口 fail loud）。 */
  get hasGateway(): boolean {
    return this.#deps.gateway !== undefined;
  }

  /**
   * **S1 · `input`** —— run 创建之前的内容闸。
   *
   * @returns 判定（`null` = 未装配安全闸）；`REDACT` 时调用方应用 `redactedContent`。
   * @throws {HttpException} 422 `VALIDATION_ERROR` + `reason_code='safety_denied'`（DENY）。
   */
  async preflight(input: {
    readonly message: string;
    readonly requestId: string;
    readonly conversationId: string | null;
  }): Promise<SafetyVerdict | null> {
    if (this.#deps.safety === undefined) return null;
    const hooks = new SafetyHooks(this.#deps.safety, {
      // S1 时 run 还没创建 ⇒ `run_id` 必须为 null（`audit_log.run_id` 有 FK）。
      runId: null,
      requestId: input.requestId,
      conversationId: input.conversationId,
    });
    const verdict = await hooks.stageInput(input.message);
    if (isBlocked(verdict)) {
      throw authError(ERROR_CODES.VALIDATION_ERROR, `输入被安全策略拦截：${verdict.detail}`, {
        reason_code: "safety_denied",
        stage: "input",
      });
    }
    return verdict;
  }

  /**
   * 建 run 并在后台驱动（**不等待终态**）。
   *
   * @throws {HttpException} `CONFIGURATION_ERROR`（未装配模型网关）/ 422（缺 workspace）。
   */
  async start(input: RunStartInput): Promise<RunStartResult> {
    if (this.#deps.gateway === undefined) {
      throw authError(
        ERROR_CODES.CONFIGURATION_ERROR,
        "未装配模型网关：POST /agents/{id}/run 需要 provider（未配置 ≠ 降级）",
        { reason_code: "model_not_configured" }
      );
    }

    const scope = new Scope(input.tenantId);
    const workspaceId = input.workspaceId ?? input.agentWorkspaceId;
    if (input.conversationId === null && (workspaceId === null || workspaceId === "")) {
      throw authError(
        ERROR_CODES.VALIDATION_ERROR,
        "新建会话需要 workspace_id（`conversation.workspace_id` NOT NULL）",
        { field: "workspace_id", reason_code: "workspace_required" }
      );
    }

    const conversationId =
      input.conversationId ??
      (
        await new ConversationRepo(this.#deps.db, scope, this.#deps.dialect).create({
          id: randomUUID(),
          workspaceId: workspaceId as string,
          agentId: input.agentId,
          userId: input.userId,
          title: input.message.slice(0, 60),
        })
      ).id;

    // 用户消息先落（`run_id` 留 null：这条是"用户说的话"，不是"run 产出的东西"）。
    const messages = new MessageRepo(
      this.#deps.db,
      scope,
      scope.ref(conversationId),
      this.#deps.dialect
    );
    await messages.append({ role: "user", content: input.message, runId: null });

    const now = this.#deps.now ?? (() => new Date());
    const startedAt = now();
    const runId = randomUUID();
    // `TenantScopedInsert<AgentRunRow>` 要求列全（NOT NULL 列无默认值者必须显式给）；
    // 这里的 `as never` 与仓内既有 `insertRow(... as never)` 同款（列类型由 drizzle 推导，
    // `agent/policy.ts` 亦如此断言），刻意保留逐列书写以便人工核对 NOT NULL 面。
    const run = await new AgentRunRepo(this.#deps.db, scope, this.#deps.dialect).create({
      id: runId,
      agent_id: input.agentId,
      agent_version_id: input.agentVersionId,
      conversation_id: conversationId,
      user_id: input.userId,
      task_id: null,
      trigger: "user",
      run_mode: "INLINE",
      status: "QUEUED",
      trace_id: null,
      span_id: null,
      last_heartbeat_at: instantLiteral(this.#deps.dialect, startedAt),
      idempotency_key: null,
      started_at: instantLiteral(this.#deps.dialect, startedAt),
      completed_at: null,
      duration_ms: null,
      token_usage: {},
      success: null,
      error_type: null,
      tool_error_count: 0,
      cost: null,
      cost_currency: null,
      cost_price_version: null,
      cost_estimated: false,
      cost_breakdown: null,
      cost_status: "UNPRICED",
      error: null,
      stop_reason: null,
    } as never);

    // ⚠️ 刻意的 `void`：HTTP 侧不等终态（卡面「异步驱动」）。错误全部折成 run 终态，
    //    不外抛 —— 一个已经返回 200 的请求不该有"后台抛异常"这种不可观测形态。
    const driving = this.#drive(input, run, conversationId).catch(() => undefined);
    this.#inflight.set(runId, driving);
    void driving.finally(() => {
      this.#inflight.delete(runId);
    });

    return { run, conversationId };
  }

  /**
   * 等某 run 的后台驱动收尾（**测试与优雅关闭用**；生产 HTTP 路径不调它）。
   *
   * @param runId run 标识。
   * @param timeoutMs 上限（缺省 30s）；超时不抛错 —— 断言留给调用方（用 `GET /runs`）。
   */
  async awaitSettled(runId: string, timeoutMs = 30_000): Promise<void> {
    const pending = this.#inflight.get(runId);
    if (pending === undefined) return;
    await Promise.race([pending, sleep(timeoutMs)]);
  }

  /** 是否还有后台 run 在跑（优雅关闭用）。 */
  get inflightCount(): number {
    return this.#inflight.size;
  }

  // -------------------------------------------------------------------------
  // 后台驱动
  // -------------------------------------------------------------------------

  /** 抢 lease → 装配 → 跑内核 → 收敛终态。**任何异常都折成终态**（不外抛）。 */
  async #drive(input: RunStartInput, queued: AgentRunRow, conversationId: string): Promise<void> {
    const driver = this;
    const { db, dialect, tenantId } = this.#deps;
    const coordinator = this.#deps.coordinator;
    const scope = new Scope(tenantId);
    const runId = queued.id;
    const writer = new RunEventWriter({ db, dialect, tenantId, runId });
    const flags: RunFlags = { approvalRejected: false, safetyBlockedStage: null, servedUnits: 0 };

    // ---- lease（抢不到 ⇒ 别的 worker 在推这次 run，本进程安静退出）---------
    try {
      await coordinator.acquire(runId, { from: ["QUEUED"], to: "RUNNING" });
    } catch {
      return;
    }

    const startedAtMs = Date.now();
    const limits = limitsOf(input.runtimeConfig, this.#deps.limits ?? DEFAULT_STOP_LIMITS);
    const ledger = new BudgetLedger(toBudgetLimits(limits), () => Date.now());
    const surface: ToolSurface = await buildToolSurface({
      db,
      dialect,
      tenantId,
      ...(this.#deps.egressAllowlist === undefined
        ? {}
        : { egressAllowlist: this.#deps.egressAllowlist }),
    });
    const workspaceRoot = this.#workspaceRootOf(runId);
    const executor = new ToolExecutor({
      workspaceRoot,
      tools: surface.tools,
      ...(this.#deps.sandbox === undefined ? {} : { sandbox: this.#deps.sandbox }),
      ...(this.#deps.egressAllowlist === undefined
        ? {}
        : { egressAllowlist: this.#deps.egressAllowlist }),
      ...(this.#deps.toolTimeoutMs === undefined ? {} : { timeoutMs: this.#deps.toolTimeoutMs }),
    });
    const hooks =
      this.#deps.safety === undefined
        ? null
        : new SafetyHooks(this.#deps.safety, {
            runId,
            requestId: input.requestId,
            conversationId,
          });
    const messagesRepo = new MessageRepo(db, scope, scope.ref(conversationId), dialect);
    const toolCalls = new ToolCallRepo(db, scope, scope.ref(runId), dialect);

    const context: RunCallContext = {
      runId,
      tenantId,
      signal: coordinator.signalOf(runId),
      // 绝对截止时刻：账本的墙钟上限换算成"到点即视为超时"。
      deadlineMs: startedAtMs + limits.maxWallTimeMs,
      budget: ledger,
      // V0.3.0 没有权限授予链 ⇒ 空集 = 维持现状（真正的拦截在 SafetyGate）；
      // 与 `ToolExecutor.#authorized` 的注释同源，不是"忘了传"。
      permissions: [],
      policyVersion: SAFETY_POLICY_VERSION,
    };

    let outcome: Awaited<ReturnType<AgentLoop["run"]>> | null = null;
    let failureDetail: string | null = null;
    let failureType: string | null = null;

    try {
      // ---- `agent.started`（12 帧之一；终态后零事件由 writer 保证）----------
      await this.#frame(writer, "agent.started", {
        agent_id: queued.agent_id,
        agent_version_id: queued.agent_version_id,
        conversation_id: conversationId,
        run_mode: queued.run_mode,
      });

      // ---- `skill.resolved`（按版本配置逐个**真解析**；解析不到就不发）------
      await this.#emitSkills(writer, tenantId, scope, input.runtimeConfig);

      // ---- 网关装饰器（S4 + `agent.thinking`）------------------------------
      let modelCalls = 0;
      const gateway: ModelGatewayPort = {
        stream: (request: ModelRequest, callContext: RunCallContext): AsyncIterable<ModelChunk> =>
          (async function* (): AsyncIterable<ModelChunk> {
            modelCalls += 1;
            await driver.#frame(writer, "agent.thinking", { iteration: modelCalls });
            if (hooks !== null) {
              const verdict = await hooks.stageModelRequest(flattenMessages(request.messages));
              if (isBlocked(verdict)) {
                flags.safetyBlockedStage = "model_request";
                throw new SafetyBlockedError("model_request", verdict.detail);
              }
            }
            if (callContext.signal.aborted) return;
            yield* (driver.#deps.gateway as ModelGatewayPort).stream(request, callContext);
          })(),
      };

      // ---- 执行器装饰器（S5 + 审批 + S6 + tool.* 帧 + 四段落库）-------------
      const guardedExecutor: ToolExecutorPort = {
        execute: async (
          invocation: ToolInvocation,
          callContext: RunCallContext
        ): Promise<ToolExecutionResult> => {
          const startedAtCall = Date.now();
          const callId = invocation.callId;
          const toolName = invocation.toolName;
          const mcpOwner = surface.mcp.get(toolName);
          const argsJson = JSON.stringify(invocation.input ?? {});

          // ① intent（`PENDING`；**恰好一行** —— 先查后插，重复 id 复用已有行）
          const existing = await toolCalls.findById(callId);
          const intent =
            existing ??
            (await toolCalls.createPending({
              id: callId,
              tool_name: toolName,
              tool_type: toolTypeOf(toolName, surface),
              input: invocation.input ?? {},
              attempt: 1,
              trace_id: null,
              span_id: null,
              tool_id: null,
              tool_ref: null,
              sandbox_session_id: null,
            } as never));

          await driver.#frame(writer, "tool.started", {
            tool_call_id: callId,
            tool_name: toolName,
            attempt: intent.attempt,
            arguments: invocation.input ?? {},
          });
          if (mcpOwner !== undefined) {
            await driver.#frame(writer, "mcp.started", {
              mcp_call_id: callId,
              server: mcpOwner.server,
              tool_name: mcpOwner.tool,
            });
          }

          /** 收尾：写 tool_call 终态 + `tool.completed`（+ `mcp.completed`）。 */
          const finish = async (
            result: ToolExecutionResult,
            output?: unknown
          ): Promise<ToolExecutionResult> => {
            await toolCalls.markTerminal(callId, {
              status: result.status,
              ...(output === undefined ? {} : { output }),
              ...(result.error === undefined ? {} : { error: result.error }),
              durationMs: result.durationMs,
            });
            await driver.#frame(writer, "tool.completed", {
              tool_call_id: callId,
              tool_name: toolName,
              status: result.status,
              duration_ms: result.durationMs,
              error: result.error ?? null,
            });
            if (mcpOwner !== undefined) {
              await driver.#frame(writer, "mcp.completed", {
                mcp_call_id: callId,
                server: mcpOwner.server,
                status: result.status,
                duration_ms: result.durationMs,
                error: result.error ?? null,
              });
            }
            return result;
          };

          // ② S5（`tool_args`；Authorize 之前 ⇒ DENY 不进执行器）
          //    REDACT 的语义（T3-13 口径"REDACT 仅限落盘脱敏"）在这里落成
          //    **脱敏后的 args 才进执行器**：凭据不进工具，比"存脱敏、跑原文"安全。
          let effectiveInput: unknown = invocation.input;
          if (hooks !== null) {
            const verdict = await hooks.stageToolArgs(callId, argsJson);
            const applied = applyVerdict(verdict, argsJson);
            if (applied.blocked) {
              flags.safetyBlockedStage = "tool_args";
              return finish({
                status: "DENIED",
                error: `工具入参被安全策略拦截：${verdict.detail}`,
                durationMs: Date.now() - startedAtCall,
              });
            }
            if (applied.text !== argsJson) {
              effectiveInput = safeJsonParse(applied.text, invocation.input);
            }
          }

          // ③ 审批（命中 `requires_approval` ⇒ **先问人，再执行**）
          if (approvalRequiredFor(input.runtimeConfig, toolName)) {
            const decision = await driver.#askApproval({
              input,
              writer,
              runId,
              ledger,
              toolCallId: callId,
              toolName,
              argsJson,
            });
            if (decision.rejected) {
              flags.approvalRejected = true;
              return finish({
                status: "DENIED",
                error: `工具调用未获审批（approval=${decision.approvalId}）`,
                durationMs: Date.now() - startedAtCall,
              });
            }
          }

          if (callContext.signal.aborted) {
            return finish({
              status: "CANCELLED",
              error: "取消信号",
              durationMs: Date.now() - startedAtCall,
            });
          }

          // ④ execute（`PENDING → RUNNING` 之后才碰沙箱）
          await toolCalls.markRunning(callId);
          const raw = await executor.execute(
            effectiveInput === invocation.input
              ? invocation
              : { callId, toolName, input: effectiveInput },
            callContext
          );

          // ⑤ S6（`tool_result`；先检查后截断）
          let sampled: SampledContent | null = null;
          let redacted = false;
          if (hooks !== null) {
            const checked = await hooks.stageToolResult(
              callId,
              typeof raw.output === "string"
                ? raw.output
                : JSON.stringify(raw.output ?? raw.error ?? ""),
              driver.#deps.resultSampleWindow
            );
            sampled = checked.sampled;
            if (isBlocked(checked.verdict)) {
              flags.safetyBlockedStage = "tool_result";
              return finish({
                status: "DENIED",
                error: `工具结果被安全策略拦截：${checked.verdict.detail}`,
                durationMs: raw.durationMs,
              });
            }
            // REDACT ⇒ 落库/回传用脱敏后的**截断形态**（凭据不进模型，P-1 不落原文）。
            if (checked.verdict.decision === "REDACT") {
              redacted = true;
              return finish(
                { ...raw, output: checked.verdict.redactedContent ?? checked.sampled.stored },
                checked.verdict.redactedContent ?? checked.sampled.stored
              );
            }
          }

          // 采样过的结果落"截断形态"（`stored`），**不外传 `checked`**。
          const output =
            sampled !== null && sampled.sampled && !redacted
              ? sampled.stored
              : (raw.output ?? raw.error ?? null);
          return finish(raw, output === null ? undefined : output);
        },
      };

      const loop = new AgentLoop({
        gateway,
        executor: guardedExecutor,
        events: {
          // 内部行（turn/step 级）**不进 SSE**；终态后写不进去 ⇒ 静默丢弃
          // （取消后的正常形态，不该让循环因为"写不进事件"而崩）。
          appendInternal: async (type, payload) => {
            try {
              const appended = await writer.appendInternal(type, payload);
              return appended.seq;
            } catch (error) {
              if (error instanceof RunTerminalError) return -1;
              throw error;
            }
          },
        },
        strategy: GENERAL_HARNESS,
        limits,
        model: typeof input.modelConfig.model === "string" ? input.modelConfig.model : "default",
        tools: surface.specs,
        loadMessages: async () => {
          const rows = await messagesRepo.list({ limit: 200 });
          // 系统提示词是**版本快照**的一部分（`agent_version.system_prompt`），不在
          // `message` 表里 —— 这里以一条合成行前置进上下文（id 固定，便于回放时识别）。
          // 空串 ⇒ 不加：一条空的 system 消息只会让模型看到噪声。
          const context = input.systemPrompt.trim() === ""
            ? rows
            : [systemPromptRow(conversationId, input.systemPrompt), ...rows];
          if (hooks !== null) {
            // **S2**：上下文拼装后、模型调用前逐轮判定。
            const verdict = await hooks.stageContext(flattenMessages(toModelMessages(context)));
            if (isBlocked(verdict)) {
              flags.safetyBlockedStage = "context";
              throw new SafetyBlockedError("context", verdict.detail);
            }
          }
          return context;
        },
        appendAssistant: async ({ content, toolCalls: calls }) => {
          let effectiveContent = content;
          if (hooks !== null) {
            // **S7**：Commit turn 之前（消息还没落库）。
            const verdict = await hooks.stageOutput(content, {
              incident: false,
              deliveredUnits: flags.servedUnits,
            });
            const applied = applyVerdict(verdict, content);
            if (applied.blocked) {
              flags.safetyBlockedStage = "output";
              throw new SafetyBlockedError("output", verdict.detail);
            }
            effectiveContent = applied.text;
          }
          const row = await messagesRepo.append({
            role: "assistant",
            content: effectiveContent,
            contentParts: calls.map((call) => ({
              type: "tool_call",
              id: call.id,
              name: call.name,
              input: call.input,
            })),
            runId,
          });
          // `message.delta`：一条 assistant 消息一帧（内容 = 该消息全文）。
          // 细粒度分片需要 loop 暴露 chunk 回调（`ModelChunk` 目前只在网关内部可见），
          // 登记为遗留；对"帧产生 / 不产生"的判据不构成影响。
          await driver.#frame(writer, "message.delta", {
            message_id: row.id,
            role: "assistant",
            content: effectiveContent,
          });
          flags.servedUnits += 1;
        },
        appendToolResult: async ({ callId, toolName, content }) => {
          await messagesRepo.append({
            role: "tool",
            content,
            contentParts: [{ type: "tool_result", callId, toolName }],
            runId,
          });
        },
        maxContextChars: DEFAULT_MAX_CONTEXT_CHARS,
        keepRecent: DEFAULT_KEEP_RECENT,
      });

      outcome = await loop.run(context);
    } catch (error) {
      if (error instanceof SafetyBlockedError) {
        // 用 `message`（含 `安全拦截（<stage>）` 前缀）而不是裸 detail：
        // 排障时"哪个挂点拦的"与"为什么拦"同等重要。
        failureDetail = error.message;
        failureType = "SAFETY_DENIED";
      } else {
        failureDetail = error instanceof Error ? error.message : String(error);
        failureType = "RUN_EXECUTION_ERROR";
      }
    } finally {
      // 沙箱会话按 run 建、按 run 销 —— 漏掉这一步会让每次 run 泄漏一个会话登记。
      await executor.destroySession(runId).catch(() => undefined);
    }

    await this.#settle({
      runId,
      writer,
      outcome,
      flags,
      failureDetail,
      failureType,
      startedAtMs,
    });
  }

  /**
   * 收敛终态（**先发终态帧、再落库**；已终态 ⇒ 什么都不做）。
   *
   * 顺序不可换：`RunEventWriter` 在 run 终态后拒写，若先 `finalize` 再发帧，
   * 终态帧永远发不出去（前端就会"看到 run 结束了却没收尾"）。
   */
  async #settle(args: {
    runId: string;
    writer: RunEventWriter;
    outcome: Awaited<ReturnType<AgentLoop["run"]>> | null;
    flags: RunFlags;
    failureDetail: string | null;
    failureType: string | null;
    startedAtMs: number;
  }): Promise<void> {
    const { runId, writer, outcome, flags } = args;
    const coordinator = this.#deps.coordinator;

    // 取消可能已经把 run 推到终态：**不再 finalize**（否则就是"取消后复活"）。
    const current = await coordinator.get(runId);
    if (current !== null && isTerminalRunStatus(current.status as never)) {
      coordinator.forget(runId);
      return;
    }

    const durationMs = Date.now() - args.startedAtMs;
    const terminal = terminalOf(outcome, args.failureDetail, args.failureType, flags);

    if (terminal.status === "SUCCEEDED") {
      await this.#frame(writer, "agent.completed", {
        duration_ms: durationMs,
        iterations: outcome?.turns ?? 0,
      });
    } else {
      await this.#frame(writer, "agent.error", {
        error_type: terminal.errorType ?? "INTERNAL_ERROR",
        error: terminal.error ?? "执行失败",
        duration_ms: durationMs,
      });
    }

    try {
      await coordinator.finish(runId, {
        status: terminal.status,
        stopReason: terminal.stopReason,
        success: terminal.status === "SUCCEEDED",
        error: terminal.error ?? null,
        errorType: terminal.errorType ?? null,
        durationMs,
        completedAt: new Date(),
      });
    } catch {
      // run 行在此期间被删 / 不可见 ⇒ 无可收敛对象；事件已发，不伪装成功。
    }
    coordinator.forget(runId);
  }

  // -------------------------------------------------------------------------
  // 帧 / 内部行
  // -------------------------------------------------------------------------

  /** 发一帧（终态后静默丢弃；其他错误照抛）。 */
  async #frame(
    writer: RunEventWriter,
    channel: string,
    values: Record<string, unknown>
  ): Promise<void> {
    try {
      await writer.append(channel, values);
    } catch (error) {
      if (error instanceof RunTerminalError) return;
      throw error;
    }
  }

  /**
   * `skill.resolved`（12 帧之一）。
   *
   * **真解析**：按名字查 `skill` 表，查不到就**不发帧**（只落一条内部行
   * `skill.unresolved`）。为什么不发一个"半真"的帧：`skill.resolved` 的语义是
   * "这个技能已经被解析出来了"，凭空发帧等于对外声称解析成功 —— 那是伪造能力。
   */
  async #emitSkills(
    writer: RunEventWriter,
    tenantId: string,
    scope: ScopeType,
    runtimeConfig: Record<string, unknown>
  ): Promise<void> {
    const refs = skillRefsOf(runtimeConfig);
    if (refs.length === 0) return;
    const repo = new SkillRepo(this.#deps.db, scope, this.#deps.dialect);
    for (const ref of refs) {
      const row = await repo.findByName(ref.name);
      if (row === null) {
        try {
          await writer.appendInternal("skill.unresolved", {
            skill_name: ref.name,
            tenant_id: tenantId,
          });
        } catch (error) {
          if (!(error instanceof RunTerminalError)) throw error;
        }
        continue;
      }
      await this.#frame(writer, "skill.resolved", {
        skill_name: row.name,
        skill_id: row.id,
        version: ref.version ?? row.current_version_id ?? "unversioned",
      });
    }
  }

  // -------------------------------------------------------------------------
  // 审批回路
  // -------------------------------------------------------------------------

  /**
   * 三段状态迁移都用 CAS（`RUNNING → WAITING_APPROVAL → RUNNING`）；任一段失败
   * （run 已被取消）⇒ 把决议按"未批准"处理，**绝不执行**。
   */
  async #askApproval(args: {
    input: RunStartInput;
    writer: RunEventWriter;
    runId: string;
    ledger: BudgetLedger;
    toolCallId: string;
    toolName: string;
    argsJson: string;
  }): Promise<{ rejected: boolean; approvalId: string }> {
    const { db, dialect, tenantId } = this.#deps;
    const coordinator = this.#deps.coordinator;
    const scope = new Scope(tenantId);
    const approvals = new ApprovalRepo(db, scope, dialect);
    const approvalId = randomUUID();
    const approval = await approvals.create({
      id: approvalId,
      subjectType: "tool",
      subjectRef: args.toolCallId,
      requestedBy: args.input.userId,
      payload: { tool_name: args.toolName, arguments: args.argsJson.slice(0, 2000) },
    });

    let paused = false;
    try {
      await coordinator.acquire(args.runId, { from: ["RUNNING"], to: "WAITING_APPROVAL" });
      // 等待期间墙钟预算**暂停**（R3-07：用户挂起审批不该烧掉 run 的预算）。
      args.ledger.pause();
      paused = true;
    } catch {
      paused = false;
    }

    await this.#frame(args.writer, "approval.requested", {
      approval_id: approval.id,
      subject_type: "tool",
      subject_ref: args.toolCallId,
      requested_by: args.input.userId,
    });

    const pollMs = this.#deps.approvalPollMs ?? DEFAULT_APPROVAL_POLL_MS;
    const timeoutMs = this.#deps.approvalTimeoutMs ?? DEFAULT_APPROVAL_TIMEOUT_MS;
    const deadline = Date.now() + timeoutMs;
    const signal = coordinator.signalOf(args.runId);
    let decided = approval;
    for (;;) {
      if (signal.aborted) break;
      if (Date.now() > deadline) break;
      const row = await approvals.findById(scope.ref(approvalId));
      if (row === null) break;
      if (row.status !== "PENDING") {
        decided = row;
        break;
      }
      await sleep(pollMs);
    }

    if (paused) {
      try {
        await coordinator.acquire(args.runId, { from: ["WAITING_APPROVAL"], to: "RUNNING" });
        args.ledger.resume();
      } catch {
        // run 在此期间被取消 ⇒ 下面按"非 APPROVED ⇒ 驳回"处理。
      }
    }

    await this.#frame(args.writer, "approval.decided", {
      approval_id: decided.id,
      status: decided.status,
      decided_by: decided.decided_by ?? args.input.userId,
    });

    return { rejected: decided.status !== "APPROVED", approvalId: decided.id };
  }

  // -------------------------------------------------------------------------
  // 工作目录
  // -------------------------------------------------------------------------

  /** 该 run 的工作目录（**按需创建**；沙箱与 `filesystem` 共用它）。 */
  #workspaceRootOf(runId: string): string {
    const base =
      this.#deps.workspaceRoot ??
      process.env.WBTIME_RUN_WORKSPACE_ROOT ??
      join(tmpdir(), "wbtime-runs");
    const dir = join(base, runId);
    mkdirSync(dir, { recursive: true });
    return dir;
  }
}

/**
 * 内核终局 + 标志 → 终态三元组（见文件头注的映射表）。
 *
 * @param outcome 内核终局（`null` = 内核没跑起来，属执行异常）。
 * @param failureDetail 失败详情（异常路径给）。
 * @param failureType `error_type`（异常路径给）。
 * @param flags run 级标志（审批驳回优先）。
 */
export function terminalOf(
  outcome: Awaited<ReturnType<AgentLoop["run"]>> | null,
  failureDetail: string | null,
  failureType: string | null,
  flags: Pick<RunFlags, "approvalRejected">
): {
  status: "SUCCEEDED" | "FAILED" | "CANCELLED";
  stopReason: StopReason;
  errorType?: string | null;
  error?: string | null;
} {
  // 审批驳回优先于内核终局：R3-04 矩阵里 `approval_rejected` 只允许配 `CANCELLED`。
  if (flags.approvalRejected) {
    return {
      status: "CANCELLED",
      stopReason: "approval_rejected",
      errorType: failureType ?? "APPROVAL_REJECTED",
      error: failureDetail ?? "工具调用未获审批",
    };
  }
  if (outcome === null) {
    return {
      status: "FAILED",
      stopReason: "tool_failed",
      errorType: failureType ?? "RUN_EXECUTION_ERROR",
      error: failureDetail ?? "run 执行异常",
    };
  }
  if (outcome.status === "SUCCEEDED") {
    return { status: "SUCCEEDED", stopReason: "model_finish", error: null };
  }
  if (outcome.status === "CANCELLED") {
    return {
      status: "CANCELLED",
      stopReason: "cancelled",
      errorType: "CANCELLED",
      error: outcome.detail,
    };
  }
  return {
    status: "FAILED",
    stopReason: outcome.stopReason ?? "tool_failed",
    errorType: failureType ?? "RUN_EXECUTION_ERROR",
    error: failureDetail ?? outcome.detail,
  };
}
