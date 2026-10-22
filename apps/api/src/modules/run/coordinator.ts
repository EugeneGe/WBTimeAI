/**
 * T3-08 · RunCoordinator —— run 的**生命周期**（lease / 心跳 / 终态 / 取消）。
 *
 * 本层的四件事，以及它们各自为什么不能省
 * ------------------------------------
 *   ① **lease 抢占**（验收 ①）：`tryAcquireLease` 是 **CAS**
 *      （`WHERE id = ? AND status IN (from)`），命中 0 行返 `null`。两个 worker 同时推
 *      同一 run ⇒ **恰一方拿到行**，另一方拿到 `null` 并抛 {@link LeaseRejectedError}。
 *      ⚠️ 为什么这比"先查再写"可靠：`SELECT ... ; if (status===QUEUED) UPDATE` 的两步之间
 *      有窗口，两个 worker 都能通过检查；CAS 把检查与写压进同一条 SQL。
 *      （测试在 SQLite 上跑：`Promise.all` 的两条 update 由驱动串行化，**不构成真并行**，
 *      但 CAS 的判据是"第二次不命中"，与 PG 上的行为同一套语义。）
 *   ② **心跳**：`last_heartbeat_at` 是"worker 还活着"的唯一证据。没有它，崩溃的 worker
 *      留下的 `RUNNING` 行永远无法被接管。
 *   ③ **终态落库**：`finalize` 同时写 `status` + `stop_reason`（v0019）+ `success` /
 *      `error` / `error_type` / `duration_ms` / `completed_at`。`stop_reason` 与状态的
 *      搭配由 `packages/domain.run-stop-reason` 的矩阵裁定，**本层不重写**那套规则。
 *   ④ **取消是幂等的**（py `agent_run_service.py:259`）：
 *      `if run.status not in terminal_values(): 置 CANCELLED ...; return run`。
 *      已是终态 ⇒ **原样返回**（不报 409、不改状态）。这与审批的二次决议（409）**不同**，
 *      因为取消的语义是"确保它停下来"，而它已经停了 —— 再报错只会让调用方以为失败。
 *
 * 进程内取消信号（abort）
 * ----------------------
 *   `#aborts` 是**进程内**的 `Map<runId, AbortController>` —— 取消时要立刻打断正在写的
 *   SSE 流（验收 ⑥）。它不跨进程：别的 worker 取消本进程的流，只能靠"下一轮轮询发现
 *   run 已终态"来收尾。**单进程部署下这条是精确的**；多 worker 时它是"最多晚一个轮询
 *   间隔"，已在施工记录登记（不在本卡解决 —— 那需要分布式取消总线）。
 */

import { ERROR_CODES } from "@wbtime/core";
import {
  AgentRunRepo,
  Scope,
  type AgentRunRow,
  type DrizzleDatabase,
  type FinalizeRunPatch,
  type SqlDialect,
} from "@wbtime/db";
import { TERMINAL_RUN_STATUSES, isTerminalRunStatus } from "@wbtime/domain";

import { authError } from "../auth/errors.js";

/** run 处于非终态（可被取消 / 可被抢占）的四个状态。 */
export const ACTIVE_RUN_STATUSES = [
  "QUEUED",
  "RUNNING",
  "WAITING_APPROVAL",
  "WAITING_INPUT",
] as const;

/** 取消时写入的 `error_type`（py `CANCELLED_ERROR_TYPE` 同值）。 */
export const CANCELLED_ERROR_TYPE = "CANCELLED";

/** lease 没抢到（别的 worker 已经在推这一次 run）。 */
export class LeaseRejectedError extends Error {
  readonly name = "LeaseRejectedError";
  readonly code = ERROR_CODES.CONFLICT;
  readonly runId: string;
  readonly from: readonly string[];

  constructor(runId: string, from: readonly string[]) {
    super(
      `run ${runId} 的 lease 已被别处持有（期望源状态 ${from.join(" | ")}，CAS 命中 0 行）`,
    );
    this.runId = runId;
    this.from = from;
  }
}

/** 协调器依赖。 */
export interface RunCoordinatorDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  readonly tenantId: string;
  /** 时钟（测试注入；缺省真实时钟）。 */
  readonly now?: () => Date;
}

/** run 生命周期协调器。 */
export class RunCoordinator {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #tenantId: string;
  readonly #now: () => Date;
  /** 进程内取消信号（见文件头注）。 */
  readonly #aborts = new Map<string, AbortController>();

  constructor(deps: RunCoordinatorDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
    this.#tenantId = deps.tenantId;
    this.#now = deps.now ?? (() => new Date());
  }

  /**
   * 抢 lease（CAS）。
   *
   * @param runId run 标识。
   * @param options `from` = 允许的源状态；`to` = 目标状态（缺省 `RUNNING`）。
   * @throws {LeaseRejectedError} 没抢到（状态已不是 `from` 里的任何一个）。
   * @throws {HttpException} 404（run 不可见）。
   */
  async acquire(
    runId: string,
    options: { from?: readonly string[]; to?: string } = {}
  ): Promise<AgentRunRow> {
    const from = options.from ?? ["QUEUED"];
    const to = options.to ?? "RUNNING";
    const row = await this.#runs().tryAcquireLease(this.#ref(runId), {
      from: [...from],
      to,
      at: this.#now(),
    });
    if (row === null) {
      // 区分"没抢到"与"不存在"：先看行在不在，再决定 409 还是 404。
      const existing = await this.get(runId);
      if (existing === null) {
        throw authError(ERROR_CODES.NOT_FOUND, "Run 不存在", { run_id: runId });
      }
      throw new LeaseRejectedError(runId, from);
    }
    return row;
  }

  /** 心跳（刷新 `last_heartbeat_at`）。 */
  async heartbeat(runId: string): Promise<AgentRunRow | null> {
    return this.#runs().heartbeat(this.#ref(runId), this.#now());
  }

  /**
   * 终态落库。
   *
   * @throws {HttpException} 404（run 不可见）。
   */
  async finish(runId: string, patch: FinalizeRunPatch): Promise<AgentRunRow> {
    const updated = await this.#runs().finalize(this.#ref(runId), {
      ...patch,
      completedAt: patch.completedAt ?? this.#now(),
    });
    if (updated === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "Run 不存在", { run_id: runId });
    }
    return updated;
  }

  /**
   * 取消（**幂等**：已终态 ⇒ 原样返回）。
   *
   * 顺序：先置进程内取消信号（尽快打断 SSE 流），再 CAS 落库。
   * 反过来会让"落库成功但流还在写"的窗口更长。
   *
   * @throws {HttpException} 404（run 不可见）。
   */
  async cancel(runId: string): Promise<AgentRunRow> {
    // 先置信号：`#signal()` 只负责"取到（必要时创建）controller"，**必须显式 abort**
    // —— 只取不 abort 等于什么都没做（本行首版就漏了，被 `runs-cancel.test.mjs` B-2 抓住）。
    this.#signal(runId).abort();

    const existing = await this.get(runId);
    if (existing === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "Run 不存在", { run_id: runId });
    }
    if (isTerminalRunStatus(existing.status as never)) {
      // 幂等：已经停了，就原样返回（**不是** 409）。
      return existing;
    }

    const now = this.#now();
    const leased = await this.#runs().tryAcquireLease(this.#ref(runId), {
      from: [...ACTIVE_RUN_STATUSES],
      to: "CANCELLED",
      at: now,
    });
    if (leased === null) {
      // 与上面的终态检查之间被别的请求改掉了 ⇒ 重读一次，仍是"幂等返回"。
      const reread = await this.get(runId);
      if (reread === null) {
        throw authError(ERROR_CODES.NOT_FOUND, "Run 不存在", { run_id: runId });
      }
      return reread;
    }

    // 补齐终态字段。⚠️ 与上面的 CAS 是两次写：窗口期内读到的行 status 已是 CANCELLED、
    // `success` 仍为 null。契约 `success` 可空 ⇒ 该中间态合法（不是脏数据）。
    // 做成单条 update 需要给仓储加 `cancelIfActive`（CAS + 全字段），属 db 层改动；
    // 本卡不动仓储，登记为可选择优化。
    const finalized = await this.#runs().finalize(this.#ref(runId), {
      status: "CANCELLED",
      stopReason: "cancelled",
      success: false,
      errorType: CANCELLED_ERROR_TYPE,
      completedAt: now,
    });
    return finalized ?? leased;
  }

  /** run 是否已终态（`MISSING` ⇒ 视作终态：没有可写的事件目标）。 */
  async isTerminal(runId: string): Promise<boolean> {
    const row = await this.get(runId);
    if (row === null) return true;
    return isTerminalRunStatus(row.status as never);
  }

  /** 取 run（不可见 ⇒ `null`）。 */
  async get(runId: string): Promise<AgentRunRow | null> {
    return this.#runs().findById(this.#ref(runId));
  }

  /** 该 run 的取消信号（不存在则创建；SSE 流用它提前收尾）。 */
  signalOf(runId: string): AbortSignal {
    return this.#signal(runId).signal;
  }

  /** 清掉取消信号（run 收尾后调用，避免 Map 长期持有）。 */
  forget(runId: string): void {
    this.#aborts.delete(runId);
  }

  #signal(runId: string): AbortController {
    let controller = this.#aborts.get(runId);
    if (controller === undefined) {
      controller = new AbortController();
      this.#aborts.set(runId, controller);
    }
    return controller;
  }

  #ref(runId: string) {
    return new Scope(this.#tenantId).ref(runId);
  }

  #runs(): AgentRunRepo {
    return new AgentRunRepo(this.#db, new Scope(this.#tenantId), this.#dialect);
  }
}

/** 终态集合（供路由层/测试复用；与 domain 同源，不另立表）。 */
export { TERMINAL_RUN_STATUSES };
