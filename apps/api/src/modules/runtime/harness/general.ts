/**
 * T3-09 · `GeneralHarness`（ReAct：模型根据观察决定下一步）。
 *
 * 决策规则只有两条（刻意的简单，可解释优先）
 * -------------------------------------
 *   1. **本轮请求了工具** ⇒ `continue`。理由：模型明确表达了"我还需要外部信息"，
 *      停下就等于丢弃它的意图。
 *   2. **本轮没有请求工具** ⇒ `stop(model_finish, SUCCEEDED)`。理由：模型给出了
 *      最终答复，ReAct 循环自然收敛。
 *
 * 为什么不是"看内容是否为空 / 是否含某个结束标记"
 * -------------------------------------------
 *   那需要猜测模型的措辞（"任务完成"、"Done"、"```"…），是典型的脆弱启发式：
 *   同一条回复换个说法就判错，而且**判错的后果是不收敛**（模型已经答完却继续追问）。
 *   `toolCalls` 的有无是**结构化事实**，不依赖措辞。
 *
 * 边界：`tool_failed` 不由本策略判定
 * ------------------------------
 *   工具失败后要不要停，取决于策略（ReAct 通常允许模型看到错误再试一次）。本版的
 *   做法是：**失败的工具结果照样作为 observation 回给模型**，由模型下一轮决定
 *   （重试 / 换工具 / 放弃）。所以 `tool_failed` 不会由 `GeneralHarness` 触发
 *   —— 它只在 `ToolExecutor` 返回不可恢复错误、且循环外判定时使用（归 T3-10 的
 *   执行器错误分类）。
 */

import type { HarnessContext, HarnessDecision, HarnessStrategy } from "./strategy.js";

/** ReAct 策略。 */
export class GeneralHarness implements HarnessStrategy {
  readonly name = "general";

  decide(context: HarnessContext): HarnessDecision {
    if (context.pendingToolCalls.length > 0) {
      return { kind: "continue" };
    }
    return {
      kind: "stop",
      stopReason: "model_finish",
      terminalStatus: "SUCCEEDED",
      detail: `第 ${context.turn} 轮模型未请求工具 ⇒ 视为给出最终答复`,
    };
  }
}

/** 单例（无状态，可安全共享；测试要独立实例时直接 `new`）。 */
export const GENERAL_HARNESS = new GeneralHarness();
