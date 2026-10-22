/**
 * T3-09 · 上下文压缩（Harness §3 第 2 步的"丢什么"策略）。
 *
 * 为什么压缩必须是**纯函数**且**可解释**
 * ------------------------------------
 *   压缩会**永久改变模型看得见的内容**。一旦它悄悄发生，"模型为什么没提那件事"就再也
 *   查不清了。所以本文件只做两件事：给出保留集 / 给出丢弃集，并**说出理由**
 *   （`reason` 字段），由调用方把 `reason` + 丢弃区间写进 `agent_event` 内部行
 *   （`context.compacted`），成为可审计事实。
 *
 * 策略（V0.3.0 只有一条，刻意的简单）
 * ---------------------------------
 *   - **系统消息永不丢**（`role="system"`）—— 它是行为约束，丢了等于换了个人；
 *   - **最近 N 条永不留丢**（`keepRecent`）—— 它承载当前任务；
 *   - 中间部分：**从最早的块开始丢**，直到估算字符数落回 `maxChars` 以内；
 *   - 若"只保留 system + 最近 N 条"仍然超限 ⇒ **不再丢**（返回 `applied=true` 但
 *     `oversize=true`），由停止条件（tokens 预算）去收尾 —— 压缩不能把对话压成
 *     "只剩两个人名"，那比超预算更糟。
 *
 * 为什么按**配对块**丢而不是按行丢（AUD-05）
 * --------------------------------------
 *   `assistant(tool_call)` 与它后面的 `role="tool"` 结果是一对**协议级不可分**的行：
 *   真实 Provider 对"带 toolCalls 的 assistant 后面没有对应 tool 结果"（以及"孤立
 *   tool 结果"）会直接 400。按行丢一旦把边界切在这两者之间，压缩就会**制造**一次
 *   400 —— 而压缩是静默发生的，排障时很难想到是它干的。
 *
 *   所以丢行单位是块：`assistant(含 tool_call)` 为块头，连同其后**连续的** `tool` 行
 *   构成一块；**整块丢或整块留**。代价是块粒度可能让结果**略微超预算**（一整块都丢
 *   才够，但丢到一半已经满足预算时仍要丢完或都不丢）—— 这是**正确性优先**的取舍：
 *   多留几十个字符只是多花点 token，切坏配对是直接不可用。
 *
 * 不做的事
 * -------
 *   - 不做**摘要式**压缩（需要再调一次模型 ⇒ 引入额外成本与不可复现性，归 V0.4.0 的
 *     记忆/压缩波）；
 *   - 不重排、不改写任何消息内容（改内容会让"模型看到 A、审计看到 B"）。
 */

import type { MessageRow } from "@wbtime/db";

/** 压缩选项。 */
export interface CompactionOptions {
  /** 字符预算（`Math.ceil(chars/4)` 的 token 估算由调用方负责，本函数只看字符）。 */
  readonly maxChars: number;
  /** 至少保留的尾部消息数。 */
  readonly keepRecent: number;
}

/** 压缩结果。 */
export interface CompactionOutcome {
  /** 保留的消息（**原行引用**，未复制、未改写）。 */
  readonly kept: readonly MessageRow[];
  /** 丢弃的消息（按原序）。 */
  readonly dropped: readonly MessageRow[];
  /** 是否发生了丢弃。 */
  readonly applied: boolean;
  /** 只保留 system + 最近 N 条仍超限 ⇒ `true`（交由 tokens 预算收尾）。 */
  readonly oversize: boolean;
  /** 人读理由（`applied=false` ⇒ `"within-budget"`）。 */
  readonly reason: string;
}

/**
 * 计算压缩结果（**纯函数**，无 IO、无副作用）。
 *
 * @param rows 升序消息行（`(created_at, id)` 全序，由仓储保证）。
 * @param options 见 {@link CompactionOptions}。
 */
export function compactMessages(
  rows: readonly MessageRow[],
  options: CompactionOptions
): CompactionOutcome {
  const totalChars = rows.reduce((sum, row) => sum + (row.content ?? "").length, 0);
  if (totalChars <= options.maxChars) {
    return Object.freeze({
      kept: Object.freeze([...rows]),
      dropped: Object.freeze([]),
      applied: false,
      oversize: false,
      reason: "within-budget",
    });
  }

  // 尾部保留区：最近 `keepRecent` 条（不足则全保留）。
  const keepFromIndex = Math.max(0, rows.length - options.keepRecent);

  // 按**配对块**切（AUD-05）：块是不可分的丢弃单位，见文件头注。
  const blocks = toPairingBlocks(rows);

  // 尾部优先：与保留区**有任何交集**的块整块留下（这也防止 keepRecent 的边界
  // 落在 assistant(tool_call) 与它的 tool 结果之间）。
  // `system` 行不论位置一律留下 —— 它不在尾部也在"必留集"里（预算必须把它们算进去，
  // 否则会算少而少丢，等于用错误的预算做压缩决策）。
  const kept = new Set<number>(); // 行下标
  for (const block of blocks) {
    const pinned = rows[block.start].role === "system";
    if (block.end >= keepFromIndex || pinned) {
      for (let index = block.start; index <= block.end; index += 1) kept.add(index);
    }
  }

  const charsAt = (index: number): number => (rows[index].content ?? "").length;

  let remaining = 0;
  for (const index of kept) remaining += charsAt(index);

  // 从最早的**可丢块**开始整块丢，直到落回预算。
  const droppedIndexes = new Set<number>();
  for (const block of blocks) {
    if (remaining <= options.maxChars) break;
    // 块按原序排列 ⇒ 一旦某个块碰到保留区，它和它之后的块都在保留区里。
    // （这条同时兑现了"keepRecent 的边界不得把配对块切开"—— 跨界的块整块留下。）
    if (block.end >= keepFromIndex) break;
    // system 行永不丢（它是行为约束）。
    if (rows[block.start].role === "system") continue;
    for (let index = block.start; index <= block.end; index += 1) {
      remaining -= charsAt(index);
      droppedIndexes.add(index);
    }
  }

  const dropped = [...droppedIndexes].sort((left, right) => left - right).map((index) => rows[index]);
  const keptRows = rows.filter((_row, index) => !droppedIndexes.has(index));
  const oversize = remaining > options.maxChars;

  return Object.freeze({
    kept: Object.freeze(keptRows),
    dropped: Object.freeze(dropped),
    applied: dropped.length > 0,
    oversize,
    reason: oversize
      ? "still-oversize-after-compaction（system + 最近 N 条已超预算，交由 tokens 预算收尾）"
      : `dropped ${dropped.length} 条最早的非 system 消息（按 tool_call↔tool_result 配对块整块丢弃）`,
  });
}

/**
 * 切成**配对块**（AUD-05）。
 *
 * 规则：`content_parts` 里含 `type === "tool_call"` 的 `assistant` 行是块头，**其后
 * 连续的** `role === "tool"` 行属于同一块；其余每一行自成一块。
 *
 * 为什么只认 `content_parts.type === "tool_call"` 而不认"assistant 后跟 tool"：
 * 没有 tool_call 的 assistant 后面即使跟着 tool 行，也不是一对（那种 tool 行是**孤儿**，
 * 把它和前面的普通回复绑在一起只会让可丢的东西变少）。
 *
 * @param rows 升序消息行。
 * @returns 每块的行下标闭区间（`start <= end`），按原序、互不重叠、覆盖全部行。
 */
function toPairingBlocks(rows: readonly MessageRow[]): { start: number; end: number }[] {
  const blocks: { start: number; end: number }[] = [];
  let index = 0;
  while (index < rows.length) {
    const start = index;
    let end = index;
    if (hasToolCall(rows[index])) {
      // 块头是 assistant(tool_call)：吞掉其后连续的 tool 行。
      while (end + 1 < rows.length && rows[end + 1].role === "tool") {
        end += 1;
      }
    }
    blocks.push({ start, end });
    index = end + 1;
  }
  return blocks;
}

/** 该行是否携带 `tool_call` 分片（块头的判据）。 */
function hasToolCall(row: MessageRow): boolean {
  if (row.role !== "assistant") return false;
  const parts = Array.isArray(row.content_parts) ? (row.content_parts as unknown[]) : [];
  return parts.some(
    (item) =>
      typeof item === "object" &&
      item !== null &&
      (item as Record<string, unknown>).type === "tool_call"
  );
}

/** 字符 → token 的**保守上界**估算（见 `context-builder.ts` 的口径说明）。 */
export function estimateTokens(chars: number): number {
  return Math.ceil(chars / 4);
}
