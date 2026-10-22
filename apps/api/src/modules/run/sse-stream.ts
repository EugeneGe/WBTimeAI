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

/** 一行 → 一帧。通道不在 19 条冻结面里 ⇒ 抛错（不静默丢弃：那会让帧数悄悄少一条）。 */
export function frameOf(row: AgentEventRow): Buffer {
  const channel = row.type;
  if (!isSseChannel(channel)) {
    throw new Error(
      `agent_event.type=${JSON.stringify(channel)} 不是契约 19 通道之一 —— 库里有脏行，不得下发`
    );
  }
  return encodeDataFrame(row.seq, channel as SseChannel, (row.payload ?? {}) as Record<string, unknown>);
}

/** 一批行 → 一批帧（顺序保持）。 */
export function framesOf(rows: readonly AgentEventRow[]): Buffer[] {
  return rows.map(frameOf);
}

/** `streamRunFrames` 的依赖（只读 + 一个终态探针）。 */
export interface StreamRunFramesOptions {
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
   * 最多轮询轮数（缺省 200）。**必须有限**：没有上限的订阅会在"run 永不终态"时
   * 把测试挂死，也会让一个断开的连接长期占着 worker。
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
 * 轮询 + 下发，直到终态 / 中断 / 轮数用尽。
 *
 * 每次轮询都重新 `continualFrom` ⇒ **洞出现时本批只发到洞前**，下一轮从新的
 * `lastSeq` 继续。洞被填上之后自然接续，不需要额外的"重试"状态。
 *
 * @param options 见 {@link StreamRunFramesOptions}。
 * @returns 见 {@link StreamRunFramesResult}。
 */
export async function streamRunFrames(
  options: StreamRunFramesOptions
): Promise<StreamRunFramesResult> {
  const batchLimit = options.batchLimit ?? 500;
  const pollIntervalMs = options.pollIntervalMs ?? 50;
  const maxPolls = options.maxPolls ?? 200;

  let lastSeq = options.afterSeq;
  let frames = 0;

  for (let poll = 0; poll < maxPolls; poll += 1) {
    if (options.signal?.aborted === true) {
      return { frames, lastSeq, reason: "aborted" };
    }

    const rows = await options.readAfter(lastSeq, batchLimit);
    const contiguous = continualFrom(rows, lastSeq);
    for (const row of contiguous) {
      await options.write(frameOf(row));
      frames += 1;
      lastSeq = row.seq;
    }

    // 终态判定放在"发完本批"之后：终态 run 的最后几帧必须发出去，否则前端永远差尾帧。
    if (await options.isTerminal()) {
      // 再读一次，把终态前后脚写入的行也带走（同一轮内的竞态）。
      const tail = continualFrom(await options.readAfter(lastSeq, batchLimit), lastSeq);
      for (const row of tail) {
        await options.write(frameOf(row));
        frames += 1;
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
