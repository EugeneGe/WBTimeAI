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
import { SAFETY_POLICY_VERSION } from "../safety/gate.js";

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

/**
 * 拒绝原因（**闸的分类**，不含放行态 `OK`）。
 *
 * `SAFETY_DENIED` 是本版（T031-02 / S3 挂点）新增的**第四种真实状态** —— 不是笔误、
 * 也不是把某个既有状态写错名字：`delegation` stage 的 `DENY` 与深度 / 并发 /
 * 父不可见三条路径互斥且都落在同一个拒绝观察面上，只有扩进联合类型才能让
 * `SpawnChildOutcome.reason` 继续是**穷举**的（否则只能退化成 `string`，把
 * "拒绝原因"这个分类信息抹掉）。已在施工记录 `T031-02.md` 登记。
 */
export type SpawnRejectReason = "DEPTH_EXCEEDED" | "CONCURRENCY_LIMIT" | "PARENT_NOT_VISIBLE" | "SAFETY_DENIED";

/** 派生结果的原因（`OK` = 放行，其余见 {@link SpawnRejectReason}）。 */
export type SpawnOutcomeReason = "OK" | SpawnRejectReason;

/** 派生结果。 */
export interface SpawnChildOutcome {
  readonly accepted: boolean;
  readonly reason: SpawnOutcomeReason;
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
      // 防御位（施工记录裁定 4）：origin=SUBAGENT 恒豁免下当前不可达；
      // 可达条件 = T031-04 接线后 origin 误传。保留，不算死代码。
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
    // payload 键序 = channels.delta.json :: subagent.started 的 payload_keys_in_order
    // （T031-01 冻结）：run_id = 本行所属流（子 run）；child_run_id / parent_run_id
    // 恒双在 —— 任何一侧单看都能还原父子关系。
    await this.#events(childRunId).append({
      type: SUBAGENT_STARTED_EVENT,
      payload: {
        run_id: childRunId,
        child_run_id: childRunId,
        parent_run_id: args.parentRunId,
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
  // 拒绝侧：三层观察面（D1）+ 委派挂点标记（S3）
  // -------------------------------------------------------------------------

  /**
   * 拒绝并落观察面（② 事件 + ① 失败的 tool_call；③ 由"未写子 run 行"结构性保证）。
   *
   * `options.stage` 给出时写进事件 payload（S3：`SafetyStage = "delegation"`）；
   * spike 的 D1 路径（{@link spawn}）不给 stage —— payload 形状按调用方语义定，
   * 两者的 reason 都来自调用方原样传递。
   */
  async #reject(
    args: SpawnChildArgs,
    options: { depth: number; maxDepth: number; reason: SpawnRejectReason; stage?: string }
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
        // S3 挂点标记（delegation 路径给；spike 的 D1 路径不给 —— payload 形状按调用方语义）
        ...(options.stage === undefined ? {} : { stage: options.stage }),
      },
    });

    return {
      accepted: false,
      reason: options.reason,
      depth: options.depth,
      maxDepth: options.maxDepth,
      childRunId: null,
      toolCallId,
      rejectedEventSeq: appended.seq,
    };
  }

  // -------------------------------------------------------------------------
  // 委派执行链入口（T031-02 · delegation.ts 的派生单入口落点）
  // -------------------------------------------------------------------------

  /**
   * 委派派生（delegation.ts 的 S3 闸/深度闸**之后**调用；本方法做剩余三步）：
   * 父可见性 → 并发闸（origin=SUBAGENT 豁免）→ 建子 run + 双源写行。
   *
   * 与 {@link spawn} 的差异（按 T031-02 判据《调用契约》）：
   *   - 拒绝事件带 `stage`（S3 挂点标记，判据 S3-3 断言 `payload.stage == "delegation"`）；
   *   - 子侧 `subagent.started` payload 增 `policy_version`（S3-1 断言 == 父快照）；
   *     ⚠️ 行 payload ⊇ 帧冻结键序 —— `policy_version` 是**行级域字段**，T031-05 注册
   *     下发面时按 `channels.delta.json` 的 `payload_keys_in_order` 选键组装帧；
   *   - 返回 `policyVersion`（判据断言 accepted 形态的伴随值）。
   *
   * 预算（D4）：`input.budget` 是**已下拨**的子预算 B（delegation.ts 的
   * `resolveChildBudget` 产物方向）；随 `subagent.started` payload 记 `budget` 快照
   * （零 DDL：JSON 列），触顶判定在执行链消费侧用 `applyChildBudget`。
   */
  async delegate(input: {
    readonly parentRunId: string;
    readonly targetAgentId: string;
    readonly targetVersionId: string;
    readonly conversationId: string;
    readonly task: string;
    readonly depth: number;
    readonly maxDepth: number;
    readonly budget?: Record<string, number>;
    readonly policyVersion?: string;
    readonly rejectionStage: string;
  }): Promise<
    | { readonly accepted: true; readonly childRunId: string; readonly policyVersion: string }
    | { readonly accepted: false; readonly reason: string; readonly stage?: string }
  > {
    const args: SpawnChildArgs = {
      parentRunId: input.parentRunId,
      targetAgentId: input.targetAgentId,
      targetVersionId: input.targetVersionId,
      conversationId: input.conversationId,
      task: input.task,
      depth: input.depth,
      maxDepth: input.maxDepth,
    };

    // 闸：深度（delegation.ts 已闸过一次；此处复闸是防御 —— 两处共用同一纯判定，
    // 不存在口径漂移，代价为一次纯函数调用）。
    const check = isDepthAllowed({ depth: input.depth, maxDepth: input.maxDepth });
    if (!check.allowed) {
      await this.#reject(args, {
        depth: input.depth,
        maxDepth: input.maxDepth,
        reason: DEPTH_EXCEEDED_REASON,
        stage: input.rejectionStage,
      });
      return { accepted: false, reason: DEPTH_EXCEEDED_REASON, stage: input.rejectionStage };
    }

    const parent = await this.#runs().findById(this.#scope.ref(input.parentRunId));
    if (parent === null) {
      return { accepted: false, reason: "PARENT_NOT_VISIBLE" };
    }

    const guard = await guardRunCreation({
      db: this.#db,
      dialect: this.#dialect,
      tenantId: this.#scope.tenantId,
      conversationId: input.conversationId,
      origin: RUN_ORIGIN_SUBAGENT,
      trigger: RUN_TRIGGER_SUBAGENT,
    });
    if (!guard.allowed) {
      // 防御位（裁定 4）：可达条件 = T031-04 接线后 origin 误传。
      await this.#reject(args, {
        depth: input.depth,
        maxDepth: input.maxDepth,
        reason: "CONCURRENCY_LIMIT",
        stage: input.rejectionStage,
      });
      return { accepted: false, reason: "CONCURRENCY_LIMIT", stage: input.rejectionStage };
    }

    const policyVersion = input.policyVersion ?? SAFETY_POLICY_VERSION;
    const childRunId = randomUUID();
    await this.#runs().create(this.#childRunValues(args, parent, childRunId));

    const toolCallId = randomUUID();
    const toolCalls = this.#toolCalls(input.parentRunId);
    await toolCalls.createPending({
      id: toolCallId,
      tool_name: SPAWN_AGENT_TOOL_NAME,
      tool_type: "builtin",
      input: this.#defaultToolInput(args),
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

    // 子侧还原源 + S3 快照继承。行 payload ⊇ 帧冻结键序（policy_version 为行级域字段，
    // budget 为 D4 下拨快照 —— 帧组装时按契约键序选键，见文件头裁定 2 注）。
    await this.#events(childRunId).append({
      type: SUBAGENT_STARTED_EVENT,
      payload: {
        run_id: childRunId,
        child_run_id: childRunId,
        parent_run_id: input.parentRunId,
        target_agent_id: input.targetAgentId,
        task: input.task,
        policy_version: policyVersion,
        ...(input.budget === undefined ? {} : { budget: input.budget }),
      },
    });

    return { accepted: true, childRunId, policyVersion };
  }

  /**
   * 委派拒绝（delegation.ts 的 S3 / 深度闸拒绝路径落点）：与 {@link delegate} 同款
   * 观察面（父 run 的 tool_call FAILED + `subagent.rejected`，payload 带挂点标记），
   * **子 run 行数恒 0**（结构性保证 —— 本方法不写任何 agent_run 行）。
   */
  async rejectDelegation(
    args: {
      readonly parentRunId: string;
      readonly targetAgentId: string;
      readonly task: string;
      readonly depth: number;
      readonly maxDepth: number;
    },
    options: { readonly stage: string; readonly reason: SpawnRejectReason }
  ): Promise<void> {
    await this.#reject(
      {
        parentRunId: args.parentRunId,
        targetAgentId: args.targetAgentId,
        targetVersionId: "",
        conversationId: "",
        task: args.task,
        depth: args.depth,
        maxDepth: args.maxDepth,
      },
      { depth: args.depth, maxDepth: args.maxDepth, reason: options.reason, stage: options.stage }
    );
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
