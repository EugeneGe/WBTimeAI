/**
 * T3-09 · 停止条件（Harness §8 矩阵的**唯一判定点**）。
 *
 * 为什么单独成件而不是散在 loop 里
 * ------------------------------
 * 卡面验收 ② 要求"**每一项**耗尽 ⇒ 可解释终态 + `stop_reason` **精确**"，反例还要求
 * "`stop_reason` 与耗尽项不匹配 ⇒ 必红"。若判定散落在循环各处（`if (turn > max) ...`
 * 写在 Call 前、`if (cost > max) ...` 写在 Commit 后），"哪一项先命中"就取决于**代码
 * 书写顺序**，而 R3-01 规定的是**固定优先序**（turns > tools > tokens > cost）。
 * 集中成纯函数后，优先序只在一处，且可以脱离 IO 单独测。
 *
 * 六项 vs `BudgetLedger` 的四项
 * ---------------------------
 *   `BudgetLedger` 管 **4 项累计预算**（turns / tools / tokens / cost）+ 墙钟（独立判定）。
 *   `max_tool_calls_per_turn` **不在其中**：它是"单轮内"的上限，每轮重置，不累计 ——
 *   把它塞进账本会让 `addToolCall()` 变成两种语义的混合体。
 *   本文件在账本之外补这一项，并让它与 `budget_tools` 共用 stop_reason
 *   （契约 11 值里没有单独的 `budget_tools_per_turn`，**不自造码**）。
 *
 * 契约面：`stop_reason` 只有 11 值，且每个终态只允许其中若干
 * ---------------------------------------------------------
 *   `STOP_REASONS_BY_TERMINAL_STATUS` 实测：`SUCCEEDED` **只能**配 `model_finish`；
 *   预算类与墙钟都在 `FAILED` 里。所以"预算耗尽"必然是 `FAILED` —— 不能写成
 *   `SUCCEEDED` 图好看（那会让 R3-04 矩阵在 `finish()` 处直接抛错）。
 */

import {
  BudgetLedger,
  type BudgetLimits,
  type StopReason,
} from "@wbtime/domain";

/**
 * 六项停止上限（服务端配置 / 策略决定；可按 Agent / 租户覆盖但有全局上界）。
 *
 * 全部是**正整数**，`assertPositive` 在构造时校验 —— `0` 不等于"不限"，它等于
 * "第一次判定就耗尽"，那是几乎必然的配置事故。
 */
export interface StopLimits {
  readonly maxModelTurns: number;
  readonly maxToolCalls: number;
  /** 单轮内工具调用上限（**不累计**，每轮重置）。 */
  readonly maxToolCallsPerTurn: number;
  readonly maxWallTimeMs: number;
  readonly maxTokens: number;
  readonly maxCost: number;
}

/** 触发源（比 `stop_reason` 更细：`max_tool_calls` 与 `..._per_turn` 共用 `budget_tools`）。 */
export type StopSource =
  | "max_model_turns"
  | "max_tool_calls"
  | "max_tool_calls_per_turn"
  | "max_wall_time_ms"
  | "max_tokens"
  | "max_cost";

/** 停止判定结果。`stop=false` 时后三个字段恒 `null`。 */
export interface StopVerdict {
  readonly stop: boolean;
  /** 哪一项先命中（`stop=false` ⇒ `null`）。 */
  readonly source: StopSource | null;
  /** 该终止走哪个**终态**（预算类/墙钟恒 `FAILED`，见文件头注）。 */
  readonly terminalStatus: "SUCCEEDED" | "FAILED" | "CANCELLED" | null;
  /** 契约 11 值之一（`stop=false` ⇒ `null`）。 */
  readonly stopReason: StopReason | null;
  /** 人读的一句话（进 `agent.error` 的 `error` 字段 / 内部事件 payload）。 */
  readonly detail: string | null;
}

/** 未触发的判定结果（复用同一个冻结对象，避免每次 new）。 */
export const NOT_STOPPED: StopVerdict = Object.freeze({
  stop: false,
  source: null,
  terminalStatus: null,
  stopReason: null,
  detail: null,
});

/**
 * 缺省上限（**保守值**，按"一次对话不该烧掉一间机房"定）。
 *
 * 这些不是产品参数，是**兜底**：真正的上限由 Agent / 租户配置覆盖
 * （Harness §8 原话"全部由服务端配置 / 策略决定，可按 Agent / 租户覆盖但有全局上界"）。
 */
export const DEFAULT_STOP_LIMITS: StopLimits = Object.freeze({
  maxModelTurns: 20,
  maxToolCalls: 60,
  maxToolCallsPerTurn: 8,
  maxWallTimeMs: 600_000,
  maxTokens: 200_000,
  maxCost: 5,
});

/**
 * 六项上限 → `BudgetLedger` 的四项 + 墙钟。
 *
 * `maxToolCallsPerTurn` **不映射**（见文件头注），故此处被丢弃。
 */
export function toBudgetLimits(limits: StopLimits): BudgetLimits {
  assertPositive("maxModelTurns", limits.maxModelTurns);
  assertPositive("maxToolCalls", limits.maxToolCalls);
  assertPositive("maxToolCallsPerTurn", limits.maxToolCallsPerTurn);
  assertPositive("maxWallTimeMs", limits.maxWallTimeMs);
  assertPositive("maxTokens", limits.maxTokens);
  assertPositive("maxCost", limits.maxCost);
  return Object.freeze({
    maxTurns: limits.maxModelTurns,
    maxToolCalls: limits.maxToolCalls,
    maxTokens: limits.maxTokens,
    maxCost: limits.maxCost,
    maxWallTimeMs: limits.maxWallTimeMs,
  });
}

/**
 * 判定是否该停（**纯函数**，无 IO）。
 *
 * 顺序（**固定，不随调用位置变化**）：
 *   1. **墙钟**（`wall_time`）—— 它是最外层的"别把进程拖死"，优先于任何预算；
 *   2. **单轮工具上限**（`budget_tools`）—— 它挡的是"一轮里爆量"，
 *      若放到累计预算之后判定，一个已经被 turns 耗尽的 run 会先报 `budget_turns`，
 *      而真正的原因是这一轮工具打爆了（诊断信息更差）；
 *   3. **账本四项**（`turns > tools > tokens > cost`，由 `BudgetLedger.exceeded()` 保证）；
 *   4. 否则不停。
 *
 * @param ledger 预算台账（`@wbtime/domain`）。
 * @param limits 六项上限。
 * @param turnToolCalls 本轮**已发生**的工具调用数（不是累计）。
 */
export function evaluateStop(
  ledger: BudgetLedger,
  limits: StopLimits,
  turnToolCalls: number
): StopVerdict {
  if (ledger.isWallTimeExceeded()) {
    return freeze({
      source: "max_wall_time_ms",
      terminalStatus: "FAILED",
      stopReason: "wall_time",
      detail: `墙钟超限：${ledger.activeWallTimeMs}ms ≥ ${limits.maxWallTimeMs}ms`,
    });
  }

  if (turnToolCalls >= limits.maxToolCallsPerTurn) {
    return freeze({
      source: "max_tool_calls_per_turn",
      terminalStatus: "FAILED",
      // 契约 11 值里没有 per-turn 专用码 ⇒ 复用 `budget_tools`，**不自造码**。
      stopReason: "budget_tools",
      detail: `本轮工具调用超限：${turnToolCalls} ≥ ${limits.maxToolCallsPerTurn}`,
    });
  }

  const budget = ledger.exceeded();
  if (budget !== null) {
    return freeze({
      source: sourceOfBudget(budget),
      terminalStatus: "FAILED",
      stopReason: budget,
      detail: `预算耗尽：${budget}`,
    });
  }

  return NOT_STOPPED;
}

/**
 * `needsContinuation`（验收 ③：**显式**判定，不靠"循环自然结束"）。
 *
 * 三件事都成立才继续：
 *   - 没有停止判定命中；
 *   - 没有取消（`signal.aborted`）；
 *   - **策略说继续**（`GeneralHarness`：本轮模型请求了工具 ⇒ 还有事要做）。
 *
 * 为什么把它写成独立函数而不是 `while (!stop)`：`while (!stop)` 会让"为什么退出"
 * 只能事后从 `stop` 的终值推断；显式函数让每条退出路径都必须给出理由（返回 `false` 时
 * 调用方**必须**带着 `StopVerdict` 或策略给出的 `stopReason` 收尾）。
 */
export function needsContinuation(input: {
  readonly verdict: StopVerdict;
  readonly signal: AbortSignal;
  readonly strategyWantsContinue: boolean;
}): boolean {
  if (input.verdict.stop) return false;
  if (input.signal.aborted) return false;
  return input.strategyWantsContinue;
}

/** `budget_*` → 触发源（一一对应，`budget_tools` 归累计那一项）。 */
function sourceOfBudget(reason: StopReason): StopSource {
  switch (reason) {
    case "budget_turns":
      return "max_model_turns";
    case "budget_tools":
      return "max_tool_calls";
    case "budget_tokens":
      return "max_tokens";
    case "budget_cost":
      return "max_cost";
    default:
      // 其他 stop_reason 不来自账本；走到这里说明调用方用错了函数。
      throw new RangeError(`evaluateStop：${String(reason)} 不是账本类 stop_reason`);
  }
}

function freeze(verdict: Omit<StopVerdict, "stop">): StopVerdict {
  return Object.freeze({ stop: true, ...verdict });
}

function assertPositive(name: string, value: number): void {
  if (!Number.isFinite(value) || value <= 0) {
    throw new RangeError(
      `停止上限 ${name} 必须是有限正数，实际 ${String(value)}（0 不等于"不限"）`
    );
  }
}
