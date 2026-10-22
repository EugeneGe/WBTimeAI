/**
 * T3-08 · RunEventWriter —— 把一个**已发生**的域事实写成 `agent_event` 行 + SSE 帧。
 *
 * 三条不变量（卡面验收 ③⑤ + 反例 ③）
 * ---------------------------------
 *   ① **只允许白名单帧**：`RUN_SSE_CHANNELS` 是白名单，其余通道
 *      （`agent.failed` / `agent.message` / `workflow.*` 五条 / `knowledge.indexed` /
 *      `memory.written`）**一律拒绝**。基线 19 条通道是 `packages/event` 的冻结面；
 *      V0.3.1 · T031-05 起，delta 契约（`contracts/sse/channels.delta.json`，恰 2 项
 *      `subagent.started` / `subagent.finished`）经生成面注册后**并入本白名单**
 *      （12 → 14 帧；`registration_boundary` 由本卡解除）。反例「下发 `workflow.*` /
 *      未注册通道 ⇒ 必红」的落点在这里。
 *   ② **终态后零事件**（验收 ⑤）：每次写入**先查 run 当前状态**，终态
 *      （`SUCCEEDED / FAILED / CANCELLED`）⇒ 抛 {@link RunTerminalError}，一行不写。
 *      为什么每次查库而不是缓存：多 worker 下"别人刚把 run 推到终态"必须立刻生效；
 *      缓存的终态标记只会在本进程内正确，而这正是"终态后又冒出一条事件"的经典来源。
 *   ③ **`seq` 由仓储分配**（`max(seq)+1`，冲突抛 `ChildConflictError`），本层不重排、
 *      不改号。`seq` 是 **run 内**序号，跨 run 复用是**允许**的（见
 *      `AgentEventRepo.findDuplicateSeq` 的注释）—— 反例 ④「seq 跨 run 复用 ⇒ 必红」
 *      靠的是"查询级断言按 run 隔离"，不是"全局唯一"。
 *
 * 为什么 payload 必须过 `buildEventPayload`
 * ----------------------------------------
 * 它按契约 `payload_keys_in_order` **重建**对象（键序即线上 JSON 键序，`sort_keys=False`
 * 的等价物），并拒绝多余键 / 缺必填键。绕过它直接 `JSON.stringify`，键序就取决于调用方
 * 的对象字面量顺序 —— 那会让 `packages/event` 的 golden sha256 逐帧失配。
 */

import { ERROR_CODES } from "@wbtime/core";
import {
  AgentEventRepo,
  AgentRunRepo,
  Scope,
  type AgentEventRow,
  type DrizzleDatabase,
  type SqlDialect,
} from "@wbtime/db";
import { isTerminalRunStatus } from "@wbtime/domain";
import {
  buildEventPayload,
  channelSpec,
  encodeDataFrame,
  isSseChannel,
  type SseChannel,
} from "@wbtime/event";

/**
 * 允许经 run 流下发的 **14 帧**（R3-11a 的 12 帧 + V0.3.1 · T031-05 注册的 2 条 delta）。
 *
 * 顺序不参与判据，但保持契约顺序便于人眼比对。**不要**按"看着像同一个东西"往这里加
 * —— 加一条就等于新增 SSE 帧：基线 19 项通道属冻结面（channels.json 永久冻结），
 * 追加帧只能经 `channels.delta.json` 契约登记 + 生成面注册（T031-05）进入本清单。
 */
export const RUN_SSE_CHANNELS = [
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
  "approval.requested",
  "approval.decided",
  // V0.3.1 · T031-05 发帧注册（T031-01 契约 `registration_boundary` 的解除）：
  // 此前对这 2 帧维持"既有拒发行为"；生成面注册完成后此处正常放行。
  "subagent.started",
  "subagent.finished",
] as const;

export type RunSseChannel = (typeof RUN_SSE_CHANNELS)[number];

/** 12 帧的集合形态（`has` 判据 O(1)）。 */
const RUN_SSE_CHANNEL_SET: ReadonlySet<string> = new Set(RUN_SSE_CHANNELS);

/** 通道不在 run 流白名单内（含"通道本身未知"与"已知但不许经 run 流下发"两种）。 */
export class RunChannelRejectedError extends Error {
  readonly name = "RunChannelRejectedError";
  readonly code = ERROR_CODES.VALIDATION_ERROR;
  readonly channel: string;

  constructor(channel: string) {
    super(
      `通道 ${JSON.stringify(channel)} 不在 run 流下发白名单内` +
        `（允许：${RUN_SSE_CHANNELS.join(" / ")}）`,
    );
    this.channel = channel;
  }
}

/** run 已终态，拒绝任何新事件（终态后零事件）。 */
export class RunTerminalError extends Error {
  readonly name = "RunTerminalError";
  readonly code = ERROR_CODES.CONFLICT;
  readonly runId: string;
  readonly status: string;
  readonly channel: string;

  constructor(runId: string, status: string, channel: string) {
    super(`run ${runId} 已处于终态 ${status}，拒绝事件 ${channel}（终态后零事件）`);
    this.runId = runId;
    this.status = status;
    this.channel = channel;
  }
}

/** 写入结果：行 + 已编码的帧（同一份 payload，避免"写进去的"和"发出去的"不一致）。 */
export interface AppendedRunEvent {
  readonly seq: number;
  readonly event: AgentEventRow;
  readonly frame: Buffer;
}

/** 写入器依赖。 */
export interface RunEventWriterDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  readonly tenantId: string;
  readonly runId: string;
}

/**
 * 单 run 的事件写入器。
 *
 * **无内部状态**（除了构造参数）：每次 `append` 都重新取仓储、重新查 run 状态。
 * 这是刻意的 —— 有状态的 writer 一旦被跨请求复用，"终态判定"就会读到旧快照。
 */
export class RunEventWriter {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #tenantId: string;
  readonly #runId: string;

  constructor(deps: RunEventWriterDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
    this.#tenantId = deps.tenantId;
    this.#runId = deps.runId;
  }

  /**
   * 追加一条事件（先判白名单、再判终态、最后写库 + 编码）。
   *
   * @param channel 通道名（必须 ∈ {@link RUN_SSE_CHANNELS}）。
   * @param values payload 的**其余**键（`run_id` 由本方法注入，调用方不必传；
   *   传了会被本方法的同值覆盖，不构成第二个真相源）。
   * @throws {RunChannelRejectedError} 通道不在 run 流白名单。
   * @throws {RunTerminalError} run 已终态。
   * @throws {EventPayloadError} payload 多键 / 缺必填键（来自 `buildEventPayload`）。
   */
  async append(channel: string, values: Record<string, unknown> = {}): Promise<AppendedRunEvent> {
    // ① 白名单先判：不在白名单里的通道连 run 状态都不用查（也避免把 workflow.* 写进库）。
    if (!RUN_SSE_CHANNEL_SET.has(channel) || !isSseChannel(channel)) {
      throw new RunChannelRejectedError(channel);
    }
    const typed = channel as RunSseChannel;

    // ② 终态后零事件：每次查库，拿最新状态。
    const run = await this.#run();
    if (run === null) {
      // 不可见（不存在 / 跨租户）⇒ 与 404 同形；写入器不区分二者，避免泄漏存在性。
      throw new RunTerminalError(this.#runId, "MISSING", channel);
    }
    if (isTerminalRunStatus(run.status as never)) {
      throw new RunTerminalError(this.#runId, run.status, channel);
    }

    // ③ 按契约键序装配。
    // ⚠️ `run_id` **不是每条通道都有**（实测 `approval.requested` 的 `payloadKeysInOrder`
    //    不含它）⇒ 只在契约声明了该键时注入，否则 `buildEventPayload` 会以"含非契约键"拒绝。
    //    注入顺序在 `...values` **之后**：让 `run_id` 恒等于本 writer 的 run，调用方传什么都盖掉
    //    （同一条事件不可能属于两个 run）。
    const spec = channelSpec(typed as SseChannel);
    const withRunId = spec.payloadKeysInOrder.includes("run_id")
      ? { ...values, run_id: this.#runId }
      : { ...values };
    const payload = buildEventPayload(typed as SseChannel, withRunId);

    // ④ seq 由仓储分配；`(run_id, seq)` 冲突由 `appendAt` 的探针抛 `ChildConflictError`。
    const appended = await this.#events().append({ type: typed, payload });

    // ⑤ 编码。同一个 payload 既落库又出帧 ⇒ 库里的与发出去的不可能不一致。
    const frame = encodeDataFrame(appended.seq, typed as SseChannel, payload);

    return { seq: appended.seq, event: appended.row, frame };
  }

  /**
   * 追加一条**内部行**（`agent_event` 行，**不进 SSE**）。
   *
   * 与 {@link append} 的唯一区别：**不校验 12 帧白名单**。理由（R3-11）：
   * 19 通道是"下发给前端的帧"，而 `turn/step` 级事实（`loop.turn.started` /
   * `context.built` / `intents.validated` …）**只落内部行**、从不下发。
   * 它们共用同一张 `agent_event` 表与同一个 `seq` 序列 —— 这样"回放一次 run 的完整
   * 过程"只需要读一张表。
   *
   * 终态检查**仍然生效**（终态后零事件对内部行同样成立）。
   *
   * @throws {RunTerminalError} run 已终态。
   */
  async appendInternal(
    type: string,
    payload: Record<string, unknown> = {}
  ): Promise<{ seq: number; event: AgentEventRow }> {
    const run = await this.#run();
    if (run === null || isTerminalRunStatus(run.status as never)) {
      throw new RunTerminalError(this.#runId, run?.status ?? "MISSING", type);
    }
    const appended = await this.#events().append({ type, payload });
    return { seq: appended.seq, event: appended.row };
  }

  /**
   * `seq > afterSeq` 的事件（升序）。
   *
   * **不含** gap 语义 —— "遇到洞就停"是续读策略（`sse-stream.ts::continualFrom`），
   * 仓储只负责区间。把策略留在上层，才好在测试里单独注入一个洞。
   */
  listAfter(afterSeq: number, limit = 500): Promise<AgentEventRow[]> {
    return this.#events().listAfter(afterSeq, { limit });
  }

  /** 当前最大 seq（无事件 ⇒ 0）。续读端点用它决定"有没有必要继续轮询"。 */
  maxSeq(): Promise<number> {
    return this.#events().maxSeq();
  }

  #events(): AgentEventRepo {
    const scope = new Scope(this.#tenantId);
    return new AgentEventRepo(this.#db, scope, scope.ref(this.#runId), this.#dialect);
  }

  #run() {
    const scope = new Scope(this.#tenantId);
    return new AgentRunRepo(this.#db, scope, this.#dialect).findById(scope.ref(this.#runId));
  }
}
