/**
 * T3-08 · SSE 下发（12 帧编码 + **gap-aware** 续读 + 可中断轮询）。
 *
 * 三件事，刻意分成三个函数
 * ----------------------
 *   ① {@link continualFrom} —— **纯函数**：把"读到的区间"裁成"连续的片段"。
 *      gap-aware 的语义就在这里，且**不碰 IO**，所以测试可以只喂一个含洞的数组。
 *   ② {@link framesOf} —— **纯函数**：行 → 已编码帧（`packages/event.encodeDataFrame`）。
 *   ③ {@link streamRunFrames} —— 唯一有 IO 的部分：轮询新事件、写进 `reply.raw`、
 *      终态后收尾、`AbortSignal` 中断。
 *
 * gap-aware 的判据（卡面验收 ② 逐字）
 * ----------------------------------
 *   `Last-Event-ID=5` 且库里有 `5, 6, 8` ⇒ **只补 6**（不返 8、不重放 5、也不返 7 之后）。
 *   规则：从 `afterSeq + 1` 开始，**期望值连续递增**；拿到的 `seq` ≠ 期望值 ⇒ 立即停
 *   （不是跳过、不是补齐 —— 补齐等于伪造事件）。
 *
 * 为什么"遇洞就停"而不是"跳过洞继续发"
 * ----------------------------------
 *   `seq` 是**事件次序**的编号。出现洞只有两种成因：写者崩在中间、或读到了未提交的行。
 *   两种情况下继续往下发，前端拿到的就是一段**缺帧的因果链**（例如 `tool.started` 丢了
 *   但 `tool.completed` 在），它无法判断该不该渲染。停在这里让客户端重连，由下一轮
 *   补齐 —— 这是"宁可晚、不可错"。
 *
 * 续读**不得**触发第二次执行（反例 ②）
 * ---------------------------------
 *   本文件只读 `agent_event`，**不 import** 任何 coordinator / 执行器。
 *   端点的语义是"把已经发生的事再发一遍"，与"重跑"毫无关系 —— 这条靠 import 面就能
 *   机械化断言（`sse-dispatch.test.mjs` 的静态面）。
 */

import { encodeDataFrame, isSseChannel, type SseChannel } from "@wbtime/event";
import type { AgentEventRow } from "@wbtime/db";

/**
 * 从 `afterSeq` 之后取**连续**的一段。
 *
 * @param rows 升序事件行（调用方保证按 `seq` 升序；本函数不排序 —— 排序是仓储的事）。
 * @param afterSeq 客户端已收到的最后 seq（`0` = 从第一条开始）。
 * @returns `afterSeq` 之后连续递增的那一段；遇到第一个空洞即停止。
 *
 * @example
 * continualFrom([{seq:5},{seq:6},{seq:8}], 5) // ⇒ [{seq:6}]
 * continualFrom([{seq:5},{seq:6},{seq:8}], 0) // ⇒ [{seq:5},{seq:6}]
 */
export function continualFrom<T extends { readonly seq: number }>(
  rows: readonly T[],
  afterSeq: number
): T[] {
  const contiguous: T[] = [];
  /**
   * 期望的下一个 seq。
   *
   * 两种客户端状态，语义**不同**（首版把两者混成一个 `afterSeq + 1`，被
   * `event-cursor.test.mjs` 的 A-2 / B-1 同时抓住）：
   *
   *   - **`afterSeq === 0`（客户端没有游标）** ⇒ 从头回放 ⇒ 起点对齐**第一条未发事件**
   *     （`expected = rows[0].seq`）。若库里最早是 `5`（更早的被清理 / 半途接管），
   *     严格按 `1` 对齐会让第一条 `5 > 1` 直接 break ⇒ **一帧都发不出**，客户端永远空回放。
   *   - **`afterSeq > 0`（客户端有游标）** ⇒ 它明确说"我收到了 N" ⇒ 下一个**必须**是
   *     `N + 1`。`N+2` 就是洞，宁可停（`after=3` 且库里只有 `5` ⇒ **0 帧**，
   *     因为客户端还差 4；把 5 当成起点会让它误以为 4 从未存在）。
   *
   * `null` 是"尚未对齐"的哨兵，不是"没有期望值"。
   */
  let expected: number | null = afterSeq === 0 ? null : afterSeq + 1;
  for (const row of rows) {
    if (row.seq <= afterSeq) continue; // 已发过的（重放保护：不重发）
    if (expected === null) expected = row.seq; // 起点对齐第一条未发事件
    if (row.seq > expected) break; // 洞 ⇒ 停（不跳过、不补）
    if (row.seq < expected) continue; // 同一批里的重复行（防御性）
    contiguous.push(row);
    expected += 1;
  }
  return contiguous;
}

/**
 * 一行 → 一帧；**内部行（非 19 通道）返回 `null`**。
 *
 * 为什么从"抛错"改成"跳过"（T3-09 起）：R3-11 要求 `turn/step` 级事实落
 * `agent_event` **内部行**（`loop.turn.started` / `context.built` / …），它们与 SSE 帧
 * **共用同一张表与同一个 seq 序列**。若这里抛错，库里一旦有内部行，SSE 流就整条崩掉。
 *
 * 但"跳过"不等于"沉默地丢脏数据"：`isSseChannel` 仍在这里判定，**未知通道**
 * （既不是 12 帧也不是内部行命名空间）依旧会被上层视为可疑 —— 由
 * `sse-dispatch.test.mjs` 的 A-2 保证"12 帧之外的下发"在**写入侧**就被拒，
 * 所以流里出现的非通道行必然是内部行，跳过是安全且必要的。
 */
export function frameOf(row: AgentEventRow): Buffer | null {
  const channel = row.type;
  if (!isSseChannel(channel)) return null;
  return encodeDataFrame(row.seq, channel as SseChannel, (row.payload ?? {}) as Record<string, unknown>);
}

/** 一批行 → 一批帧（顺序保持；内部行被过滤掉）。 */
export function framesOf(rows: readonly AgentEventRow[]): Buffer[] {
  const frames: Buffer[] = [];
  for (const row of rows) {
    const frame = frameOf(row);
    if (frame !== null) frames.push(frame);
  }
  return frames;
}

/** `streamRunFrames` 的依赖（只读 + 一个终态探针）。 */
export interface StreamRunFramesOptions {
  /**
   * **归属过滤**（V0.3.1 · D2-a / D2-b）：只下发来源行 `agent_event.run_id === runId` 的行。
   *
   * 为什么判**行级列**而不是帧 payload（架构裁定 §8.5）：帧 payload 是通道投影的产物，
   * 19 条里有 4 条（`knowledge.indexed` / `memory.written` / `approval.requested` /
   * `approval.decided`）**结构上就不带 `run_id`** —— 把门禁建在 payload 上等于建在
   * 偶然事实上。行级 `run_id` 列是父谓词来源，不可被 payload 伪造。
   *
   * 缺省 `undefined` = 不过滤（既有调用方行为不变；判据 S-2 的反向面靠
   * "传与不传输出不同"钉住 `runId` 必须被真正消费）。
   */
  readonly runId?: string;
  /** 读 `seq > afterSeq` 的行（升序）。 */
  readonly readAfter: (afterSeq: number, limit: number) => Promise<AgentEventRow[]>;
  /** run 是否已终态。终态且无新事件 ⇒ 收尾。 */
  readonly isTerminal: () => Promise<boolean>;
  /** 客户端已收到的最后 seq。 */
  readonly afterSeq: number;
  /** 单批上限（缺省 500）。 */
  readonly batchLimit?: number;
  /** 轮询间隔毫秒（缺省 50；测试可调小）。 */
  readonly pollIntervalMs?: number;
  /**
   * 最多轮询轮数（**缺省无限** —— V0.3.1 · R-4/U5 长连接）。
   *
   * V0.3.0 的语义是"缺省 200、端点传 40"的**有限订阅**（≈2s 用尽即收尾，客户端靠
   * `Last-Event-ID` 重连续传）。V0.3.1 改为**长连接**：缺省无限轮询，订阅随 run
   * 生命周期收尾（终态）或被 `signal` 中断（取消 / 客户端断开）—— 终态前不再出现
   * "轮数用尽"的 `exhausted` 收尾（R-4 判据）。
   *
   * 显式传有限值仍然允许（测试注入 `maxPolls: 1` 等）；显式有限值用尽 ⇒
   * `reason: "exhausted"`。**为什么不保留有限缺省**：那等于把有限订阅藏在库层默认值里，
   * 端点"忘了传"就静默退回旧行为 —— 长连接必须由缺省值本身保证。
   */
  readonly maxPolls?: number;
  /** 外部中断（cancel / 客户端断开）。 */
  readonly signal?: AbortSignal;
  /** 每写出一帧调用一次（生产实现写 `reply.raw`，测试实现收集到数组）。 */
  readonly write: (frame: Buffer) => void | Promise<void>;
}

/** 流式结果：写出了多少帧、最后停在哪。 */
export interface StreamRunFramesResult {
  readonly frames: number;
  readonly lastSeq: number;
  /** 收尾原因：`terminal`（run 终态）/ `aborted`（中断）/ `exhausted`（轮数用尽）。 */
  readonly reason: "terminal" | "aborted" | "exhausted";
}

/**
 * 归属过滤（D2）+ 无 `seq` 行的**显式拒绝**（D6，路线①）。
 *
 * ① 归属：`runId` 未传 ⇒ 原样返回（既有行为不变）；传了 ⇒ 只留本 run 的行。
 *
 * ② D6：`seq` 不是 ≥1 整数的行**不得下发、也不得推进游标**（直接剔除）。
 *    理由（裁定登记建议，2026-10-23 工程师结论）：无 `seq` 的行若继续下行，
 *    `encodeDataFrame` 直接 RangeError **崩掉整条流**（QA `sse-watermark.test.mjs`
 *    W-2a 实测抓到的既有崩溃路径）；若给它本地自增编号冒充，则会与父 run 真 seq
 *    **撞号**且三道既有门禁都验不出水位来源。两害相权：写侧（`AgentEventRepo.appendAt`）
 *    本就保证 `seq` 为 ≥1 整数 ⇒ 库里出现无 `seq` 行只能是脏数据 —— 剔除它、让
 *    真事件照常下发，是唯一不崩流、不冒充、不推高水位的处理（QA W-2a 语义 = "rejected"）。
 *
 * ⚠️ **次序是硬约束：先过滤、后 `continualFrom`**（本函数只允许在
 * `streamRunFrames` 里被调用且恰在 continualFrom 之前）。`continualFrom` 是对
 * **单一 seq 序列**的 gap-aware 裁剪 —— 若先裁剪再过滤，父子交错的父行会呈现
 * 1、3、5 的形态而被误判成"洞" ⇒ **父流静默丢帧**。先过滤 ⇒ 每个 run 各自拿到
 * 自己的连续 seq 段，`continualFrom` 的 `afterSeq === 0` 起点对齐分支（`expected
 * = null`）会把起点对齐**过滤后**的第一条未发事件，父 run 首帧 seq 不是 1 也能正常起流。
 */
function selectStreamableRows(
  rows: readonly AgentEventRow[],
  runId: string | undefined
): readonly AgentEventRow[] {
  const owned = runId === undefined ? rows : rows.filter((row) => row.run_id === runId);
  return owned.filter((row) => Number.isInteger(row.seq) && (row.seq as number) >= 1);
}

/**
 * 轮询 + 下发，直到终态 / 中断 /（显式给出的）轮数用尽。
 *
 * 每次轮询都重新 `continualFrom` ⇒ **洞出现时本批只发到洞前**，下一轮从新的
 * `lastSeq` 继续。洞被填上之后自然接续，不需要额外的"重试"状态。
 *
 * 订阅时长模型（V0.3.1 · R-4/U5 长连接）：`maxPolls` 缺省无限，循环只由三个出口
 * 结束 —— ① run 终态（`reason: "terminal"`，终态前后脚的尾帧已带走）；②
 * `signal` 中断（取消 / 客户端断开，`reason: "aborted"`）；③ 调用方显式给了有限
 * `maxPolls` 且用尽（`reason: "exhausted"`，仅测试/特殊场景）。
 *
 * 预落地复核（2026-10-23 基线，T031-05 不得推倒）：归属过滤与"缺 `seq` 行显式拒绝"
 * 都在 {@link selectStreamableRows}，且**次序硬约束**（先过滤、后 `continualFrom`）
 * 在下面的两个调用点保持。
 *
 * @param options 见 {@link StreamRunFramesOptions}。
 * @returns 见 {@link StreamRunFramesResult}。
 */
export async function streamRunFrames(
  options: StreamRunFramesOptions
): Promise<StreamRunFramesResult> {
  const batchLimit = options.batchLimit ?? 500;
  const pollIntervalMs = options.pollIntervalMs ?? 50;
  // 长连接（R-4/U5）：缺省无限轮询；显式有限值（测试注入）仍然生效。
  const maxPolls = options.maxPolls ?? Number.POSITIVE_INFINITY;

  let lastSeq = options.afterSeq;
  let frames = 0;

  for (let poll = 0; poll < maxPolls; poll += 1) {
    if (options.signal?.aborted === true) {
      return { frames, lastSeq, reason: "aborted" };
    }

    const rows = await options.readAfter(lastSeq, batchLimit);
    const contiguous = continualFrom(selectStreamableRows(rows, options.runId), lastSeq);
    for (const row of contiguous) {
      // 内部行（turn/step 级）不进 SSE：`frameOf` 返回 `null` 时**仍然推进游标**
      // —— 否则下一轮会反复读到同一批内部行，永远推不动。
      const frame = frameOf(row);
      if (frame !== null) {
        await options.write(frame);
        frames += 1;
      }
      lastSeq = row.seq;
    }

    // 终态判定放在"发完本批"之后：终态 run 的最后几帧必须发出去，否则前端永远差尾帧。
    if (await options.isTerminal()) {
      // 再读一次，把终态前后脚写入的行也带走（同一轮内的竞态）。
      const tailRows = await options.readAfter(lastSeq, batchLimit);
      const tail = continualFrom(selectStreamableRows(tailRows, options.runId), lastSeq);
      for (const row of tail) {
        const frame = frameOf(row);
        if (frame !== null) {
          await options.write(frame);
          frames += 1;
        }
        lastSeq = row.seq;
      }
      return { frames, lastSeq, reason: "terminal" };
    }

    if (pollIntervalMs > 0) {
      await sleep(pollIntervalMs);
    }
  }

  return { frames, lastSeq, reason: "exhausted" };
}

/** 最小 sleep（不引入依赖；`AbortSignal` 由调用方在循环顶部检查）。 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
