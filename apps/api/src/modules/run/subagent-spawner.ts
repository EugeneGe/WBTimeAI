/**
 * V0.3.1 · G031-SPK · `SubAgentSpawner` —— 派生闸的**最小骨架**（spike 产物）。
 *
 * 本文件只回答 spike 的第三个问题：「深度守卫在子 run 内是否真的可拦，且三层
 * 观察面（D1）零 DDL 可写」。它**不是** T031-02 的完整实现：预算下拨 / 取消传播 /
 * 权限收窄 / S3 挂点都不在这里（那些是 T031-02 的文件域），这里只有
 * "派生请求 → 放行或拒绝"一段。
 *
 * 拒绝侧（depth 超限）的三层观察面**同时落库**（D1，全部零 DDL）：
 *   ① 父 run 内本次 `spawn_agent` 的 `tool_call.status = "failed"`（内置工具拒绝
 *      不产生 HTTP 4xx —— 观察面在表里，不在状态码里）；
 *   ② `agent_event` 落一条 `subagent.rejected`，`payload.reason = "DEPTH_EXCEEDED"`；
 *   ③ `agent_run` 中 `trigger = "subagent"` 的行数 == 0 —— **先判后写**的结构性
 *      保证（深度判不过 ⇒ 根本不会走到建子 run 的那行代码），不靠事后清理。
 *
 * 放行侧的最小闭环（只证明"零 DDL 建得出可还原的子 run"，D8① 的机制骨架）：
 *   过 {@link guardRunCreation}（`origin = SUBAGENT` 豁免并发计数）→ 落一条
 *   `trigger = "subagent"` / `status = "QUEUED"` 的子 run → 父侧 `tool_call = SUCCESS`
 *   （`output.child_run_id`，父侧还原源）+ 子侧 `subagent.started` 内部事件
 *   （`payload.parent_run_id`，子侧还原源）。**双源还原**（裁定书 R8 ②）的两个
 *   写入点都在这里，T031-02 在此基础上收紧预算 / 取消 / 权限。
 */

import { randomUUID } from "node:crypto";

import {
  AgentEventRepo,
  AgentRunRepo,
  Scope,
  ToolCallRepo,
  type AgentRunRow,
  type DrizzleDatabase,
  type SqlDialect,
  type TenantScopedInsert,
} from "@wbtime/db";
import {
  DEPTH_EXCEEDED_REASON,
  MAX_SUBAGENT_DEPTH,
  RUN_ORIGIN_SUBAGENT,
  RUN_TRIGGER_SUBAGENT,
  SPAWN_AGENT_TOOL_NAME,
  SUBAGENT_REJECTED_EVENT,
  SUBAGENT_STARTED_EVENT,
} from "@wbtime/domain";

import { guardRunCreation } from "./coordinator.js";
import { isDepthAllowed } from "./subagent-guard.js";

/** 构造依赖（《调用契约》：单对象入参 `{ db, dialect, tenantId, maxDepth }`）。 */
export interface SubAgentSpawnerDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  readonly tenantId: string;
  /** 缺省最大深度（单次 spawn 未显式给 `maxDepth` 时的兜底；缺省域常量 1）。 */
  readonly maxDepth?: number;
}

/** 一次派生请求（《调用契约》的单对象入参形态）。 */
export interface SpawnChildArgs {
  readonly parentRunId: string;
  readonly targetAgentId: string;
  readonly targetVersionId: string;
  readonly conversationId: string;
  readonly task: string;
  /** 当前 run 的深度（父 run = 0；缺省按 0 处理）。 */
  readonly depth?: number;
  /** 本次请求允许的最大深度（缺省回落构造依赖，再回落域常量）。 */
  readonly maxDepth?: number;
  /** 原始工具入参（原样进 `tool_call.input`，仅作审计）。 */
  readonly toolInput?: Record<string, unknown>;
}

/** 派生结果。 */
export interface SpawnChildOutcome {
  readonly accepted: boolean;
  readonly reason: "OK" | "DEPTH_EXCEEDED" | "CONCURRENCY_LIMIT" | "PARENT_NOT_VISIBLE";
  readonly depth: number;
  readonly maxDepth: number;
  /** 放行 ⇒ 子 run id；拒绝 ⇒ `null`。 */
  readonly childRunId: string | null;
  /** 父 run 内本次 `spawn_agent` 的 `tool_call` id（拒绝时为 FAILED 行，放行时为 SUCCESS 行）。 */
  readonly toolCallId: string | null;
  /** 拒绝侧：`subagent.rejected` 事件分到的 seq（放行 ⇒ `null`）。 */
  readonly rejectedEventSeq: number | null;
}

/** 子 Agent 派生器（spike 最小骨架）。 */
export class SubAgentSpawner {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #scope: Scope;
  readonly #maxDepth: number;

  constructor(deps: SubAgentSpawnerDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
    this.#scope = new Scope(deps.tenantId);
    this.#maxDepth = deps.maxDepth ?? MAX_SUBAGENT_DEPTH;
  }

  /**
   * 处理一次派生请求。**不抛错**：拒绝与失败都以结果对象表达（调用方是工具执行
   * 链，4xx 不是它的表达方式 —— D1 ①）。
   */
  async spawn(args: SpawnChildArgs): Promise<SpawnChildOutcome> {
    const maxDepth = args.maxDepth ?? this.#maxDepth;
    const depth = args.depth ?? 0;

    // 闸 1：深度（纯判定，先于一切 IO —— 观察面 ③ 的结构性保证就在这个次序里）。
    const check = isDepthAllowed({ depth, maxDepth });
    if (!check.allowed) {
      return this.#reject(args, { depth, maxDepth, reason: DEPTH_EXCEEDED_REASON });
    }

    // 父可见性：父不在本 scope 下 ⇒ 连 tool_call 的父都写不进（父谓词是 run_id），
    // 没有可落的观察面，只能把"不可见"原样交给调用方（HTTP 侧折 404，不是 409）。
    const parent = await this.#runs().findById(this.#scope.ref(args.parentRunId));
    if (parent === null) {
      return {
        accepted: false,
        reason: "PARENT_NOT_VISIBLE",
        depth,
        maxDepth,
        childRunId: null,
        toolCallId: null,
        rejectedEventSeq: null,
      };
    }

    // 闸 2：并发（D8/D10）。子 run 只经应用层入口建；origin=SUBAGENT 才豁免计数，
    // trigger 仅随行落库作标记 —— 判定对它零引用。
    const guard = await guardRunCreation({
      db: this.#db,
      dialect: this.#dialect,
      tenantId: this.#scope.tenantId,
      conversationId: args.conversationId,
      origin: RUN_ORIGIN_SUBAGENT,
      trigger: RUN_TRIGGER_SUBAGENT,
    });
    if (!guard.allowed) {
      return this.#reject(args, { depth, maxDepth, reason: "CONCURRENCY_LIMIT" });
    }

    // 放行：落子 run（零 DDL：trigger 用自由串列）→ 双源还原的两个写入点。
    const childRunId = randomUUID();
    await this.#runs().create(this.#childRunValues(args, parent, childRunId));

    const toolCallId = randomUUID();
    const toolCalls = this.#toolCalls(args.parentRunId);
    // 形状同 `driver.ts` 既有调用点（可空列显式置 null + `as never`：insert 的静态
    // 类型按 PG select 全键展开，仓储在运行时只要求非空列齐备）。
    await toolCalls.createPending({
      id: toolCallId,
      tool_name: SPAWN_AGENT_TOOL_NAME,
      tool_type: "builtin",
      input: args.toolInput ?? this.#defaultToolInput(args),
      attempt: 1,
      trace_id: null,
      span_id: null,
      tool_id: null,
      tool_ref: null,
      sandbox_session_id: null,
    } as never);
    await toolCalls.markRunning(toolCallId);
    await toolCalls.markTerminal(toolCallId, {
      status: "SUCCESS",
      output: { child_run_id: childRunId },
      durationMs: 0,
    });

    // 子侧还原源：`payload.parent_run_id`（子 run 自己的事件流里第一条）。
    await this.#events(childRunId).append({
      type: SUBAGENT_STARTED_EVENT,
      payload: {
        parent_run_id: args.parentRunId,
        child_run_id: childRunId,
        target_agent_id: args.targetAgentId,
        task: args.task,
      },
    });

    return {
      accepted: true,
      reason: "OK",
      depth,
      maxDepth,
      childRunId,
      toolCallId,
      rejectedEventSeq: null,
    };
  }

  // -------------------------------------------------------------------------
  // 拒绝侧：三层观察面（D1）
  // -------------------------------------------------------------------------

  /** 拒绝并落观察面（② 事件 + ① 失败的 tool_call；③ 由"未写子 run 行"结构性保证）。 */
  async #reject(
    args: SpawnChildArgs,
    options: { depth: number; maxDepth: number; reason: string }
  ): Promise<SpawnChildOutcome> {
    const toolCallId = randomUUID();
    const toolCalls = this.#toolCalls(args.parentRunId);
    // 形状同 `driver.ts` 既有调用点（可空列显式置 null + `as never`）。
    await toolCalls.createPending({
      id: toolCallId,
      tool_name: SPAWN_AGENT_TOOL_NAME,
      tool_type: "builtin",
      input: args.toolInput ?? this.#defaultToolInput(args),
      attempt: 1,
      trace_id: null,
      span_id: null,
      tool_id: null,
      tool_ref: null,
      sandbox_session_id: null,
    } as never);
    await toolCalls.markRunning(toolCallId);
    await toolCalls.markTerminal(toolCallId, {
      status: "FAILED",
      error: `spawn_agent 被拒：${options.reason}`,
      durationMs: 0,
    });

    const appended = await this.#events(args.parentRunId).append({
      type: SUBAGENT_REJECTED_EVENT,
      payload: {
        reason: options.reason,
        parent_run_id: args.parentRunId,
        target_agent_id: args.targetAgentId,
        task: args.task,
        depth: options.depth,
        max_depth: options.maxDepth,
      },
    });

    return {
      accepted: false,
      reason: options.reason === DEPTH_EXCEEDED_REASON ? "DEPTH_EXCEEDED" : "CONCURRENCY_LIMIT",
      depth: options.depth,
      maxDepth: options.maxDepth,
      childRunId: null,
      toolCallId,
      rejectedEventSeq: appended.seq,
    };
  }

  /** 子 run 行（零 DDL：只写既有列；`trigger = "subagent"` 是双源还原的 run 侧标记）。 */
  #childRunValues(
    args: SpawnChildArgs,
    parent: AgentRunRow,
    childRunId: string
  ): TenantScopedInsert<AgentRunRow> {
    return {
      id: childRunId,
      agent_id: args.targetAgentId,
      agent_version_id: args.targetVersionId,
      conversation_id: args.conversationId,
      user_id: parent.user_id ?? null,
      task_id: null,
      trigger: RUN_TRIGGER_SUBAGENT,
      run_mode: "INLINE",
      status: "QUEUED",
      trace_id: parent.trace_id ?? null,
      span_id: null,
      last_heartbeat_at: null,
      idempotency_key: null,
      started_at: null,
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
    } as TenantScopedInsert<AgentRunRow>;
  }

  /** 缺省审计入参（调用方没给 `toolInput` 时的兜底，保证 tool_call.input 不为空壳）。 */
  #defaultToolInput(args: SpawnChildArgs): Record<string, unknown> {
    return {
      target_agent_id: args.targetAgentId,
      task: args.task,
    };
  }

  #runs(): AgentRunRepo {
    return new AgentRunRepo(this.#db, this.#scope, this.#dialect);
  }

  /** 父 run 的 tool_call 仓储（父谓词恒为该 run）。 */
  #toolCalls(parentRunId: string): ToolCallRepo {
    return new ToolCallRepo(this.#db, this.#scope, this.#scope.ref(parentRunId), this.#dialect);
  }

  /** 指定 run 的事件仓储（`seq` 由仓储按 `max(seq)+1` 分配，调用方传不进）。 */
  #events(runId: string): AgentEventRepo {
    return new AgentEventRepo(this.#db, this.#scope, this.#scope.ref(runId), this.#dialect);
  }
}
