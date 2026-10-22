/**
 * T3-09 · 上下文构建（Harness §3 第 2 步：**从持久化消息重建，不靠内存**）。
 *
 * 唯一硬约束（验收 ④ 的后半句 + 反例 ③）
 * ------------------------------------
 *   `buildContext` 的输入**只有** `MessageRow[]`（从库里读出来的行），**不接受**
 *   "上一轮的 messages 数组"之类的内存状态。理由不是风格：
 *
 *   - worker 崩溃 / 重启后，内存里的对话历史**必然丢失**。若上下文靠它重建，
 *     恢复出来的 run 会"忘记"自己已经说过什么，于是重复调用工具、重复回复；
 *   - 多 worker 接管同一个 run（lease 到期后另一个进程接手）时，内存态是**另一个进程的**，
 *     根本拿不到。
 *
 *   所以本文件是**纯函数**：`MessageRow[] → ModelMessage[]`。它连 DB 都不碰 ——
 *   取数由调用方（`AgentLoop` 第 2 步）负责，这样"有没有真从库里读"可以在 loop 层断言
 *   （测试用"先写库、再换一个全新的 builder 实例"来证明没有跨实例内存）。
 *
 * epoch 是什么，为什么它是可审计的
 * ------------------------------
 *   `epoch` = **上下文版本号**：每次压缩（丢掉了行）或每次重建（新 run / 恢复）都 +1。
 *   它必须落进事件流，否则"模型为什么没看见某条消息"永远无法事后解释。
 *   本卡把 epoch 作为 `BuiltContext.epoch` 返回，由 `AgentLoop` 写进
 *   `agent_event` 的内部行（**不走 SSE**：19 通道里没有它，且 R3-11 明确
 *   `turn/step` 级事件只落内部行）。
 *
 * token 估算为什么用字符数而不是真 tokenizer
 * ----------------------------------------
 *   V0.3.0 不引入 tokenizer 依赖（零新增依赖红线）。用 `Math.ceil(chars / 4)` 作
 *   **保守上界**估计（中文实际更高，所以这个估法对中文是**低估**）。因此：
 *   - 它只用于**压缩阈值**与**观测**，**不用于** `BudgetLedger.addTokens()`
 *     —— 后者吃的是 provider 返回的真实 usage（`ModelChunk.usage`）；
 *   - 低估的方向是"少压缩"，即宁可多发一点上下文也不误删 —— 这个方向是安全的。
 */

import type { MessageRow } from "@wbtime/db";
import type { ModelMessage } from "@wbtime/domain";

import { compactMessages, type CompactionOutcome } from "./compaction.js";

/** 构建选项。 */
export interface BuildContextOptions {
  /** 字符预算（超过 ⇒ 触发压缩）。 */
  readonly maxChars: number;
  /** 压缩时至少保留的尾部消息数（含最近一轮）。 */
  readonly keepRecent: number;
  /** 父级 epoch（新 run 传 `0`；恢复 / 重放传上一次的值）。 */
  readonly parentEpoch?: number;
}

/** 构建结果（可审计描述）。 */
export interface BuiltContext {
  /** 送进模型的上下文（已按契约键序装配，可直接交给 `ModelRequest.messages`）。 */
  readonly messages: readonly ModelMessage[];
  /** 上下文版本（压缩 +1；未压缩时沿用 `parentEpoch`）。 */
  readonly epoch: number;
  /** 估算字符数（压缩后的）。 */
  readonly chars: number;
  /** 输入消息总数（压缩前）。 */
  readonly inputCount: number;
  /** 压缩结果（`applied=false` 时 `dropped` 为空）。 */
  readonly compaction: CompactionOutcome;
}

/**
 * 从**持久化消息**重建模型上下文。
 *
 * 次序：输入行按 `(created_at, id)` 由仓储给出（`MessageRepo` 自 T3-07 起就是双键全序），
 * 本函数**不重排** —— 重排会让"库里次序"与"模型看到的次序"出现两套真相。
 *
 * @param rows `MessageRepo.list()` 的结果（升序）。
 * @param options 见 {@link BuildContextOptions}。
 */
export function buildContext(
  rows: readonly MessageRow[],
  options: BuildContextOptions
): BuiltContext {
  const compaction = compactMessages(rows, {
    maxChars: options.maxChars,
    keepRecent: options.keepRecent,
  });

  const messages = compaction.kept.map(toModelMessage);
  const chars = messages.reduce((sum, message) => sum + message.content.length, 0);

  // epoch：压缩发生过就 +1（上下文"换了一版"），否则沿用父级。
  const parentEpoch = options.parentEpoch ?? 0;
  const epoch = compaction.applied ? parentEpoch + 1 : parentEpoch;

  return Object.freeze({
    messages: Object.freeze(messages),
    epoch,
    chars,
    inputCount: rows.length,
    compaction,
  });
}

/**
 * 消息行 → 契约 `ModelMessage`。
 *
 * 三处映射是**刻意**的：
 *   - `content` 列可空？实测 `message.content` 是 `text NOT NULL DEFAULT ''`，
 *     但历史行可能有 `null`（早期 DDL）⇒ `?? ""` 兜底，绝不让 `undefined` 进模型；
 *   - `role` 只有四个合法值（`system/user/assistant/tool`），库里是自由 varchar
 *     —— 未知值按 `user` 处理会**冒充**用户发言，故未知值直接抛错（宁可红，不可错）；
 *   - `token_count` **不参与**上下文（它是观测值，不是内容）。
 *
 * @throws {RangeError} `role` 不在四个合法值内。
 */
function toModelMessage(row: MessageRow): ModelMessage {
  const role = row.role;
  if (role !== "system" && role !== "user" && role !== "assistant" && role !== "tool") {
    throw new RangeError(
      `message ${row.id} 的 role=${JSON.stringify(role)} 不在 system/user/assistant/tool 内` +
        `（未知角色按 user 处理会让它冒充用户发言）`
    );
  }
  return Object.freeze({
    role,
    content: row.content ?? "",
  });
}
