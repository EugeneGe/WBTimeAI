/**
 * T3-08 · RunService —— runs **3 op** 的读出与取消（协议面），不含执行。
 *
 * | # | op | 成功码 | 错误 |
 * |---|---|---|---|
 * | 1 | `GET /runs/{run_id}` | 200 `RunResponse` | 不可见 ⇒ **404**（I-1，不是 403） |
 * | 2 | `POST /runs/{run_id}/cancel` | 200 `RunResponse` | 404；**已终态 ⇒ 幂等返回原行**（不是 409） |
 * | 3 | `GET /runs/{run_id}/events` | 200 `text/event-stream` | 404（不可见） |
 *
 * `RunResponse` 是 **21 键**：v0018 的 20 键 + v0019 的 `stop_reason`
 * （`contracts/openapi.v1.frozen.v0019.json` 实测：v0019 相对 v0018 **只多**
 * `RunResponse.stop_reason` / `RunOut.stop_reason` 两个属性，paths/ops/schemas 三集合
 * 完全相同）。TypeBox 侧直接用 `routes/schemas-run.ts` 的 `RunResponseSchema`，
 * **不二次手抄**（那个文件头注就是为这件事写的）。
 *
 * 三个"恒有值 / 恒 null"的口径（都不是随手写的）
 * -------------------------------------------
 *   - `token_usage`：契约 `object`（非可空）⇒ 列值 `null` 时回落 `{}`。
 *   - `cost_status`：契约 `default: "UNPRICED"`；列 NOT NULL ⇒ 原样出。
 *   - `cost`：PG `numeric` 驱动返回**字符串**、SQLite 返回 number ⇒ 统一 `Number(...)`；
 *     `null` 保持 `null`（"未计价"与"计价为 0"必须可分，同 `cost_status` 的 D-3 口径）。
 *
 * 本文件**不**依赖任何执行器：`cancel` 只置信号与终态，`start` 不在本卡
 * （run 的创建由 `POST /agents/{id}/run` 的入口回执负责，见 T3-05 的偏差登记）。
 *
 * T031-04 新增 {@link RunService.open_run}（**不是第 4 个 op**，无路由）：D8② 的
 * 用户入口并发闸单入口 —— `RunDriverDeps.openRun` 钩子经 `app.ts` 装配闭包传真
 * `origin=USER` 调它，`!allowed ⇒ 409 CONFLICT`。判定（{@link guardRunCreation}）
 * 与抛错都在本文件，driver 只发一次可选调用；`origin` 真值只在应用层出现（D10：
 * 豁免判据不落在可能被客户端影响的面上）。
 */

import { ERROR_CODES } from "@wbtime/core";
import {
  AgentEventRepo,
  AgentRunRepo,
  Scope,
  type AgentEventRow,
  type AgentRunRow,
  type DrizzleDatabase,
  type SqlDialect,
} from "@wbtime/db";

import { toIsoOrNull } from "../agent/versioning.js";
import { authError } from "../auth/errors.js";
import {
  RunCoordinator,
  guardRunCreation,
  type GuardRunCreationOutcome,
} from "./coordinator.js";

/** 事件区间读取的上限（单批；`streamRunFrames` 会反复读到终态）。 */
export const RUN_EVENTS_BATCH_LIMIT = 500;

/** 对外 run 视图（契约 `RunResponse` + v0019 的 `stop_reason`，共 21 键）。 */
export interface RunView {
  readonly id: string;
  readonly tenant_id: string | null;
  readonly user_id: string | null;
  readonly agent_id: string;
  readonly agent_version_id: string;
  readonly conversation_id: string;
  readonly task_id: string | null;
  readonly trigger: string;
  readonly run_mode: string;
  readonly status: string;
  readonly trace_id: string | null;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly duration_ms: number | null;
  readonly token_usage: Record<string, unknown>;
  readonly cost: number | null;
  readonly cost_status: string;
  readonly success: boolean | null;
  readonly error: string | null;
  readonly error_type: string | null;
  readonly stop_reason: string | null;
}

/** 服务依赖。 */
export interface RunServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  readonly tenantId: string;
  /** 协调器（取消与终态判定都走它，保证"只有一处 CAS"）。 */
  readonly coordinator: RunCoordinator;
}

/** runs 服务（3 op 的协议面）。 */
export class RunService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #tenantId: string;
  readonly #coordinator: RunCoordinator;

  constructor(deps: RunServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
    this.#tenantId = deps.tenantId;
    this.#coordinator = deps.coordinator;
  }

  /**
   * run 详情。
   *
   * @throws {HttpException} `NOT_FOUND`(404)（不存在 / 跨租户同一形态）。
   */
  async getById(runId: string): Promise<RunView> {
    const row = await this.#coordinator.get(runId);
    if (row === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "Run 不存在", { run_id: runId });
    }
    return toRunView(row);
  }

  /**
   * 取消（**幂等**：已终态 ⇒ 原样返回）。
   *
   * @throws {HttpException} `NOT_FOUND`(404)。
   */
  async cancel(runId: string): Promise<RunView> {
    return toRunView(await this.#coordinator.cancel(runId));
  }

  /**
   * **用户入口并发闸单入口**（T031-04 · D8②/D10；由 `RunDriverDeps.openRun` 钩子调用）。
   *
   * 为什么落在本文件而不是 driver：判定与 409 抛错都属**应用层策略**，driver 只发
   * 一次可选调用；`origin` 由 `app.ts` 装配闭包显式传真（客户端可达面到不了这里
   * ⇒ 无法伪造豁免 —— D10）。
   *
   * 拒绝路径的**零落库**保证：调用点在 `RunDriver.start` 的 conversationId 解析
   * 之后、用户消息 append 之前 ⇒ 抛错即中止，消息不落、run 行不建、新会话不留孤儿。
   *
   * @param args `conversationId` + `origin`（**必显式传真值**，D10 核心；
   *   唯一豁免值 `"SUBAGENT"`，由 `delegateSpawn` 3a 传真 —— 不走本入口）。
   * @returns 判定结果（放行时才返回；调用方一般不需要读它）。
   * @throws {HttpException} `CONFLICT`(409)（会话内活跃 run 数已达上限）。
   */
  async open_run(args: {
    readonly conversationId: string;
    readonly origin: string;
  }): Promise<GuardRunCreationOutcome> {
    const outcome = await guardRunCreation({
      db: this.#db,
      dialect: this.#dialect,
      tenantId: this.#tenantId,
      conversationId: args.conversationId,
      origin: args.origin,
    });
    if (!outcome.allowed) {
      throw authError(
        ERROR_CODES.CONFLICT,
        `会话内已有 ${outcome.activeRuns} 个活跃 run：同一会话同时最多 ${outcome.maxRuns} 个`,
        {
          reason_code: "concurrency_limit",
          conversation_id: args.conversationId,
          active_runs: outcome.activeRuns,
          max_runs_per_conversation: outcome.maxRuns,
        }
      );
    }
    return outcome;
  }

  /**
   * `seq > afterSeq` 的事件（升序，**不含** gap 语义）。
   *
   * gap-aware 是 `sse-stream.continualFrom` 的职责：仓储给区间、策略在上层，
   * 这样测试能单独注入一个洞而不必伪造整条链路。
   */
  listEventRows(runId: string, afterSeq: number, limit = RUN_EVENTS_BATCH_LIMIT): Promise<AgentEventRow[]> {
    const scope = new Scope(this.#tenantId);
    const repo = new AgentEventRepo(this.#db, scope, scope.ref(runId), this.#dialect);
    return repo.listAfter(afterSeq, { limit });
  }

  /** run 是否终态（`MISSING` ⇒ `true`：没有可写事件的目标）。 */
  isTerminal(runId: string): Promise<boolean> {
    return this.#coordinator.isTerminal(runId);
  }

  /** 取消信号（SSE 流用它提前收尾）。 */
  signalOf(runId: string): AbortSignal {
    return this.#coordinator.signalOf(runId);
  }

  /**
   * **仅在 run 已终态时**清掉进程内信号（订阅收尾的正确入口，AUD-02）。
   *
   * 为什么不能无条件 `forget`：本版订阅是有限轮询（≈2s 必到 `finally`），而 run 可能
   * 还在跑。无条件丢弃会让后续 `cancel` 作用在**新建**的 controller 上，`RunDriver`
   * 持有的旧 signal 永不置位 ⇒ 取消失效。详见 `RunCoordinator.forget` 的注释。
   *
   * @returns 是否真的丢弃了（`false` = run 仍在飞）。
   */
  forgetIfTerminal(runId: string): Promise<boolean> {
    return this.#coordinator.forgetIfTerminal(runId);
  }

  /** run 收尾后清掉进程内信号。 */
  forget(runId: string): void {
    this.#coordinator.forget(runId);
  }

  /** 内部：`GET /runs/{id}` 的可见性检查（SSE 端点先调它拿到 404 语义）。 */
  async assertVisible(runId: string): Promise<void> {
    await this.getById(runId);
  }

  /** 供路由层取仓储（目前只有测试用；生产路径都走上面几个方法）。 */
  runs(): AgentRunRepo {
    return new AgentRunRepo(this.#db, new Scope(this.#tenantId), this.#dialect);
  }
}

/**
 * 行 → 契约视图（21 键逐字对齐）。
 *
 * T3-14 起**导出**：`POST /agents/{id}/run` 的入口回执与 `GET /runs/{id}` 必须是
 * 同一形态（21 键），两处各写一份映射就是两条会漂移的真相源。
 */
export function toRunView(row: AgentRunRow): RunView {
  return {
    id: row.id,
    tenant_id: row.tenant_id ?? null,
    user_id: row.user_id ?? null,
    agent_id: row.agent_id,
    agent_version_id: row.agent_version_id,
    conversation_id: row.conversation_id,
    task_id: row.task_id ?? null,
    trigger: row.trigger,
    run_mode: row.run_mode,
    status: row.status,
    trace_id: row.trace_id ?? null,
    started_at: toIsoOrNull(row.started_at),
    completed_at: toIsoOrNull(row.completed_at),
    duration_ms: row.duration_ms ?? null,
    // 契约 `token_usage` 是 object（非可空）⇒ null 回落 `{}`。
    token_usage: (row.token_usage ?? {}) as Record<string, unknown>,
    // PG numeric → string，SQLite → number ⇒ 统一成 number；null 保持 null。
    cost: row.cost === null || row.cost === undefined ? null : Number(row.cost),
    cost_status: row.cost_status,
    success: row.success ?? null,
    error: row.error ?? null,
    error_type: row.error_type ?? null,
    stop_reason: row.stop_reason ?? null,
  };
}
