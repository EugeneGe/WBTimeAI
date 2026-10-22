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
 *   - 中间部分：**从最早开始丢**，直到估算字符数落回 `maxChars` 以内；
 *   - 若"只保留 system + 最近 N 条"仍然超限 ⇒ **不再丢**（返回 `applied=true` 但
 *     `oversize=true`），由停止条件（tokens 预算）去收尾 —— 压缩不能把对话压成
 *     "只剩两个人名"，那比超预算更糟。
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
  const head = rows.slice(0, keepFromIndex);
  const tail = rows.slice(keepFromIndex);

  // 头部里必须保留的：system 消息（不论多早）。
  const pinned = head.filter((row) => row.role === "system");
  const droppable = head.filter((row) => row.role !== "system");

  const pinnedChars = pinned.reduce((sum, row) => sum + (row.content ?? "").length, 0);
  const tailChars = tail.reduce((sum, row) => sum + (row.content ?? "").length, 0);

  // 从最早的 droppable 开始丢，直到落回预算。
  let remaining = pinnedChars + tailChars;
  const dropped: MessageRow[] = [];
  for (const row of droppable) {
    if (remaining <= options.maxChars) break;
    remaining -= (row.content ?? "").length;
    dropped.push(row);
  }

  const droppedIds = new Set(dropped.map((row) => row.id));
  const kept = rows.filter((row) => !droppedIds.has(row.id));
  const oversize = remaining > options.maxChars;

  return Object.freeze({
    kept: Object.freeze(kept),
    dropped: Object.freeze(dropped),
    applied: dropped.length > 0,
    oversize,
    reason: oversize
      ? "still-oversize-after-compaction（system + 最近 N 条已超预算，交由 tokens 预算收尾）"
      : `dropped ${dropped.length} 条最早的非 system 消息`,
  });
}

/** 字符 → token 的**保守上界**估算（见 `context-builder.ts` 的口径说明）。 */
export function estimateTokens(chars: number): number {
  return Math.ceil(chars / 4);
}
