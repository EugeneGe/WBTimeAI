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
 *
 *   ⚠️ **controller 生命周期 = run 生命周期**（AUD-02）：一个 run 从创建到终态**只有
 *   一个** controller。任何"订阅结束就清掉"的写法都会让后续 `cancel()` 作用在新
 *   controller 上，而 `RunDriver` 持有的旧 signal 永不置位 ⇒ 取消失效。故订阅侧只能调
 *   {@link RunCoordinator.forgetIfTerminal}（非终态不丢弃）。
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
   * 终态落库（**条件写**：只有活跃态才写得进去）。
   *
   * 语义（AUD-03）：
   *   - CAS 命中 ⇒ 写入并返回新行；
   *   - 未命中且**行存在**（已被别的路径落了终态）⇒ **幂等返回现状行、不抛 404**
   *     —— 收尾方晚到时不该报"不存在"，那会让"run 到底怎么了"变得不可判；
   *   - 未命中且**行不存在** ⇒ 404（确实没有可收敛的对象）。
   *
   * @throws {HttpException} 404（run 不可见）。
   */
  async finish(runId: string, patch: FinalizeRunPatch): Promise<AgentRunRow> {
    const outcome = await this.#runs().finalizeIfActive(this.#ref(runId), {
      ...patch,
      completedAt: patch.completedAt ?? this.#now(),
    });
    if (outcome.row !== null) return outcome.row;
    throw authError(ERROR_CODES.NOT_FOUND, "Run 不存在", { run_id: runId });
  }

  /**
   * 取消（**幂等**：已终态 ⇒ 原样返回）。
   *
   * 顺序：先置进程内取消信号（尽快打断 SSE 流），再落库。
   * 反过来会让"落库成功但流还在写"的窗口更长。
   *
   * **一次写**（AUD-03）：CAS 与终态字段在**同一条** `UPDATE` 里
   * （`WHERE status IN 活跃态` + 全字段），所以不存在"status 已是 CANCELLED、
   * `success` 还是 null"的中间态，也不存在"CAS 之后第二次 finalize 把别的东西覆写"。
   *
   * @throws {HttpException} 404（run 不可见）。
   */
  async cancel(runId: string): Promise<AgentRunRow> {
    // 先置信号：`#signal()` 只负责"取到（必要时创建）controller"，**必须显式 abort**
    // —— 只取不 abort 等于什么都没做（本行首版就漏了，被 `runs-cancel.test.mjs` B-2 抓住）。
    this.#signal(runId).abort();

    const now = this.#now();
    const outcome = await this.#runs().finalizeIfActive(this.#ref(runId), {
      status: "CANCELLED",
      stopReason: "cancelled",
      success: false,
      errorType: CANCELLED_ERROR_TYPE,
      completedAt: now,
    });
    if (outcome.row !== null) {
      // 命中 ⇒ 本次落库；未命中 ⇒ 已被别的路径推向终态 —— 两种都是"它停了"，
      // 取消的语义是"确保它停下来"，故一致返回现状行（**不是** 409 / 404）。
      return outcome.row;
    }
    throw authError(ERROR_CODES.NOT_FOUND, "Run 不存在", { run_id: runId });
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

  /**
   * 清掉取消信号（**无条件**；仅限"调用方确知 run 已收尾"的场景）。
   *
   * ⚠️ **controller 的生命周期 = run 的生命周期，不是订阅的生命周期**（AUD-02）。
   *
   *   订阅（`GET /runs/{id}/events`）是**短命**的：本版是有限轮询（40 轮 × 50ms ≈ 2s），
   *   必然走到 `finally`。若在那里无条件 `forget`，而 run 还在跑（长工具 / 长模型调用），
   *   下一次 `cancel()` 会**新建**一个 controller 并 abort 新的那个 —— 而
   *   `RunDriver` 在 run 启动时已经 `signalOf(runId)` 拿到了**旧** controller 的 signal
   *   （`driver.ts` 的 `RunCallContext.signal`）。旧 signal 永不置位 ⇒ 循环开头与
   *   工具执行前的 `signal.aborted` 检查全部失效 ⇒ **取消对在飞 run 无效**。
   *
   *   所以订阅收尾一律用 {@link RunCoordinator.forgetIfTerminal}：非终态不丢弃，
   *   让"同一 run 只有一份 controller"这条不变式在订阅反复收尾时依然成立。
   */
  forget(runId: string): void {
    this.#aborts.delete(runId);
  }

  /**
   * **仅在 run 已终态时**丢弃 controller（订阅收尾的正确入口，见 {@link RunCoordinator.forget}）。
   *
   * @returns 是否真的丢弃了（`false` = run 仍在飞，controller 必须留着）。
   */
  async forgetIfTerminal(runId: string): Promise<boolean> {
    // `isTerminal` 把"行不存在"也算终态（没有可写的目标 ⇒ 没有保留 controller 的理由）。
    if (!(await this.isTerminal(runId))) return false;
    this.forget(runId);
    return true;
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
