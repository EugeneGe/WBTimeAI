/**
 * T3-09 · AgentLoop —— **共享循环内核**（Harness §3 的九步时序）。
 *
 * 九步与它在本文件的落点（每步都写一条 `agent_event` **内部行**，验收 ① 的判据）
 * ---------------------------------------------------------------------------
 * | 步 | 名称 | 本文件位置 | 内部事件（`agent_event.type`，**不下发 SSE**） |
 * |---|---|---|---|
 * | 1 | Acquire | 读消息 + 取消检查 | `loop.turn.started` |
 * | 2 | Prepare | `buildContext()` | `context.built` |
 * | 3 | Call model | `#callModel()` | `model.streamed` |
 * | 4 | Commit turn | `#appendAssistant()` | `turn.committed` |
 * | 5 | Validate intents | `#validateIntents()` | `intents.validated` |
 * | 6 | Authorize | `#authorize()` | `authorize.decided` |
 * | 7 | Execute | `#executeAll()` | `tools.executed` |
 * | 8 | Observe | `#appendToolResult()` | `observations.written` |
 * | 9 | Stop or continue | `evaluateStop()` + `strategy.decide()` | `loop.stopped` |
 *
 * 为什么这些事件是**内部行**而不是 SSE 帧：R3-11 明确「`turn/step` 只落 `agent_event`
 * 内部行」；19 通道是冻结面，本卡不新增帧。内部行**不进** SSE 流（`sse-stream.frameOf`
 * 会跳过非 19 通道的行）。
 *
 * 内核**不拥有**什么（范围红线的接口化）
 * ----------------------------------
 *   - 不拥有 DB：消息读写、事件写都是注入的回调/端口；
 *   - 不拥有安全策略：授权只做**粗筛**（权限码），最终裁决在 `SafetyGate`（T3-13）；
 *   - 不拥有沙箱：工具执行一律经 `ToolExecutorPort`；
 *   - 不拥有 provider 协议：模型调用一律经 `ModelGatewayPort`（R3-10：只有 `stream()`）。
 *
 * 因此本文件可以**完全脱离网络与数据库**做单测：测试注入 fake gateway / fake executor /
 * 内存事件 sink，就能把九步时序、停止条件、续跑判定全部走一遍。
 *
 * 取消传播
 * -------
 *   每一轮开头与工具执行前都检查 `context.signal.aborted`。`signal` 由 `RunCoordinator`
 *   的 `abortController` 提供（T3-08），所以 HTTP `cancel` 能立刻打断循环 —— 不是"下一轮
 *   才发现"。取消的终态由调用方（`RunService`）落库，本内核只返回 `CANCELLED`。
 */

import type {
  MessageRow,
} from "@wbtime/db";
import {
  type BudgetLedger,
  type ModelChunk,
  type ModelMessage,
  type ModelRequest,
  type ModelToolCall,
  type ModelToolSpec,
  type RunCallContext,
  type StopReason,
  type ToolExecutionResult,
} from "@wbtime/domain";
import type { ModelGatewayPort, ToolExecutorPort } from "@wbtime/domain";

import { buildContext, type BuiltContext } from "./context-builder.js";
import type { HarnessStrategy } from "./harness/strategy.js";
import {
  evaluateStop,
  type StopLimits,
  type StopVerdict,
} from "./stop-conditions.js";

/** 内部事件出口（`agent_event` 行，**不进 SSE**）。 */
export interface LoopEventSink {
  appendInternal(type: string, payload: Record<string, unknown>): Promise<number>;
}

/** 内核依赖（全部是端口 / 回调 —— 没有一个是具体实现）。 */
export interface AgentLoopDeps {
  readonly gateway: ModelGatewayPort;
  readonly executor: ToolExecutorPort;
  readonly events: LoopEventSink;
  readonly strategy: HarnessStrategy;
  readonly limits: StopLimits;
  /** 模型标识（`ModelRequest.model`）。 */
  readonly model: string;
  /** 本轮可用的工具规格（`ModelRequest.tools`）。 */
  readonly tools: readonly ModelToolSpec[];
  /** **从持久化重建**：读本 run 的全部消息（升序）。 */
  readonly loadMessages: () => Promise<readonly MessageRow[]>;
  /** 落 assistant 消息（第 4 步）。 */
  readonly appendAssistant: (input: {
    readonly content: string;
    readonly toolCalls: readonly ModelToolCall[];
  }) => Promise<void>;
  /** 落 tool 结果消息（第 8 步）。id 必须与 intent 的 `callId` 一对一。 */
  readonly appendToolResult: (input: {
    readonly callId: string;
    readonly toolName: string;
    readonly content: string;
  }) => Promise<void>;
  /** 上下文字符预算（压缩阈值）。 */
  readonly maxContextChars: number;
  /** 压缩时至少保留的尾部消息数。 */
  readonly keepRecent: number;
}

/** 循环终局。 */
export interface LoopOutcome {
  readonly status: "SUCCEEDED" | "FAILED" | "CANCELLED";
  readonly stopReason: StopReason | null;
  readonly turns: number;
  readonly toolCalls: number;
  readonly detail: string;
}

/** 第 5 步的校验结果。 */
interface IntentsValidation {
  readonly accepted: readonly ModelToolCall[];
  readonly rejected: readonly { readonly call: ModelToolCall; readonly reason: string }[];
}

/** 第 6 步的粗筛结果。 */
interface AuthorizationDecision {
  readonly allowed: readonly ModelToolCall[];
  readonly denied: readonly { readonly call: ModelToolCall; readonly reason: string }[];
}

/**
 * 九步循环内核。
 *
 * **单 run 语义**：一个实例跑一次 `run()`；不要跨 run 复用（实例本身无状态，
 * 但复用会让"这一轮的 turn 计数"概念模糊）。
 */
export class AgentLoop {
  readonly #deps: AgentLoopDeps;

  constructor(deps: AgentLoopDeps) {
    this.#deps = deps;
  }

  /**
   * 跑完一个 run（直到终态 / 取消 / 预算耗尽）。
   *
   * @param context 调用上下文（含 `budget` 账本与 `signal`）。
   * @returns 终局（状态 + stop_reason + 计数 + 人读理由）。
   */
  async run(context: RunCallContext): Promise<LoopOutcome> {
    const { events, limits, strategy, loadMessages } = this.#deps;
    const ledger = context.budget;

    ledger.start();
    await events.appendInternal("loop.started", {
      run_id: context.runId,
      strategy: strategy.name,
      limits: {
        max_model_turns: limits.maxModelTurns,
        max_tool_calls: limits.maxToolCalls,
        max_tool_calls_per_turn: limits.maxToolCallsPerTurn,
        max_wall_time_ms: limits.maxWallTimeMs,
        max_tokens: limits.maxTokens,
        max_cost: limits.maxCost,
      },
    });

    let turn = 0;
    let totalToolCalls = 0;

    for (;;) {
      // ---- 步 1 · Acquire ------------------------------------------------
      // 消息**每轮重读**（不是缓存）：模型刚写的 assistant 消息与工具结果都要在下一轮
      // 的上下文里；缓存会让"模型看不见自己的上一句话"。
      const rows = await loadMessages();
      turn += 1;
      ledger.addTurn();
      await events.appendInternal("loop.turn.started", {
        run_id: context.runId,
        turn,
        messages: rows.length,
        aborted: context.signal.aborted,
      });

      if (context.signal.aborted) {
        return this.#finish(context, { turn, totalToolCalls, status: "CANCELLED", stopReason: "cancelled", detail: "取消信号在轮首命中" });
      }

      // ---- 步 2 · Prepare ------------------------------------------------
      const built = buildContext(rows, {
        maxChars: this.#deps.maxContextChars,
        keepRecent: this.#deps.keepRecent,
      });
      await events.appendInternal("context.built", {
        run_id: context.runId,
        turn,
        epoch: built.epoch,
        input_count: built.inputCount,
        kept_count: built.messages.length,
        chars: built.chars,
        compacted: built.compaction.applied,
        oversize: built.compaction.oversize,
        reason: built.compaction.reason,
      });

      // ---- 步 3 · Call model ---------------------------------------------
      const assistant = await this.#callModel(context, built);
      await events.appendInternal("model.streamed", {
        run_id: context.runId,
        turn,
        chars: assistant.content.length,
        tool_calls: assistant.toolCalls.length,
        finish_reason: assistant.finishReason,
      });

      // ---- 步 4 · Commit turn --------------------------------------------
      await this.#deps.appendAssistant({
        content: assistant.content,
        toolCalls: assistant.toolCalls,
      });
      await events.appendInternal("turn.committed", {
        run_id: context.runId,
        turn,
        chars: assistant.content.length,
        tool_calls: assistant.toolCalls.length,
      });

      // ---- 步 5 · Validate intents ---------------------------------------
      const intents = this.#validateIntents(assistant.toolCalls);
      await events.appendInternal("intents.validated", {
        run_id: context.runId,
        turn,
        accepted: intents.accepted.length,
        rejected: intents.rejected.map((item) => ({ id: item.call.id, reason: item.reason })),
      });

      // ---- 步 6 · Authorize ----------------------------------------------
      const authorization = this.#authorize(intents.accepted, context.permissions);
      await events.appendInternal("authorize.decided", {
        run_id: context.runId,
        turn,
        allowed: authorization.allowed.length,
        denied: authorization.denied.map((item) => ({ id: item.call.id, reason: item.reason })),
      });

      // ---- 步 7 · Execute -------------------------------------------------
      const executed = await this.#executeAll(context, turn, authorization);
      totalToolCalls += executed.executedCount;
      await events.appendInternal("tools.executed", {
        run_id: context.runId,
        turn,
        executed: executed.executedCount,
        skipped_for_turn_limit: executed.skippedCount,
        statuses: executed.statuses,
      });

      // ---- 步 8 · Observe --------------------------------------------------
      for (const item of executed.results) {
        await this.#deps.appendToolResult({
          callId: item.callId,
          toolName: item.toolName,
          content: item.content,
        });
      }
      await events.appendInternal("observations.written", {
        run_id: context.runId,
        turn,
        count: executed.results.length,
      });

      // ---- 步 9 · Stop or continue ----------------------------------------
      const verdict = evaluateStop(ledger, limits, executed.turnToolCalls);
      if (verdict.stop) {
        await events.appendInternal("loop.stopped", {
          run_id: context.runId,
          turn,
          source: verdict.source,
          stop_reason: verdict.stopReason,
          detail: verdict.detail,
        });
        return this.#finish(context, {
          turn,
          totalToolCalls,
          status: verdict.terminalStatus ?? "FAILED",
          stopReason: verdict.stopReason,
          detail: verdict.detail ?? "停止条件命中",
        });
      }

      const decision = this.#deps.strategy.decide({
        turn,
        assistant: { role: "assistant", content: assistant.content, toolCalls: assistant.toolCalls },
        pendingToolCalls: assistant.toolCalls,
        stopVerdict: verdict,
      });
      if (decision.kind === "stop") {
        await events.appendInternal("loop.stopped", {
          run_id: context.runId,
          turn,
          source: "strategy",
          stop_reason: decision.stopReason,
          detail: decision.detail,
        });
        return this.#finish(context, {
          turn,
          totalToolCalls,
          status: decision.terminalStatus,
          stopReason: decision.stopReason,
          detail: decision.detail,
        });
      }

      if (context.signal.aborted) {
        return this.#finish(context, { turn, totalToolCalls, status: "CANCELLED", stopReason: "cancelled", detail: "取消信号在工具批之后命中" });
      }
    }
  }

  // -------------------------------------------------------------------------
  // 步 3
  // -------------------------------------------------------------------------

  /** 调模型并聚合流：文本拼起来、工具调用收集起来、usage 已由网关记账。 */
  async #callModel(
    context: RunCallContext,
    built: BuiltContext
  ): Promise<{ content: string; toolCalls: ModelToolCall[]; finishReason: string }> {
    const request: ModelRequest = {
      model: this.#deps.model,
      messages: built.messages,
      ...(this.#deps.tools.length === 0 ? {} : { tools: this.#deps.tools }),
    };
    const toolCalls: ModelToolCall[] = [];
    let content = "";
    let finishReason = "model_finish";

    for await (const chunk of this.#deps.gateway.stream(request, context)) {
      if (chunk.type === "text_delta") {
        content += chunk.text;
        continue;
      }
      if (chunk.type === "tool_call") {
        // 同一 `id` 出现两次是上游异常（分片重放）；保留第一条，后续忽略。
        if (!toolCalls.some((call) => call.id === chunk.id)) {
          toolCalls.push({ id: chunk.id, name: chunk.name, input: chunk.input });
        }
        continue;
      }
      if (chunk.type === "finish") {
        finishReason = chunk.reason ?? finishReason;
        continue;
      }
      // `usage`：网关已在转发前 `budget.addTokens()` 记账，这里不重复加。
      void (chunk satisfies ModelChunk);
    }

    return { content, toolCalls, finishReason };
  }

  // -------------------------------------------------------------------------
  // 步 5 / 6 / 7
  // -------------------------------------------------------------------------

  /**
   * 校验工具意图：工具名必须在规格表里、`input` 必须是对象、同轮 `id` 不得重复。
   *
   * 不校验 JSON Schema（那是 `ToolExecutor` 的职责，T3-10）—— 内核只做"这个意图
   * 是不是能送下去"的粗筛，避免两套 schema 校验逻辑。
   */
  #validateIntents(calls: readonly ModelToolCall[]): IntentsValidation {
    const known = new Set(this.#deps.tools.map((tool) => tool.name));
    const accepted: ModelToolCall[] = [];
    const rejected: { call: ModelToolCall; reason: string }[] = [];
    const seen = new Set<string>();

    for (const call of calls) {
      if (seen.has(call.id)) {
        rejected.push({ call, reason: `同轮重复 tool_call id ${call.id}` });
        continue;
      }
      seen.add(call.id);
      if (!known.has(call.name)) {
        rejected.push({ call, reason: `未知工具 ${JSON.stringify(call.name)}` });
        continue;
      }
      if (typeof call.input !== "object" || call.input === null || Array.isArray(call.input)) {
        rejected.push({ call, reason: `工具入参必须是对象，实测 ${Array.isArray(call.input) ? "array" : typeof call.input}` });
        continue;
      }
      accepted.push(call);
    }
    return { accepted, rejected };
  }

  /**
   * 粗筛授权：**只按权限码**。
   *
   * 不做真正的安全判定 —— 那是 `SafetyGate`（T3-13）的职责，卡面范围红线明确
   * 「不自研第二套安全/权限」。本步存在的意义是"在送进执行器之前，把明显没授权的
   * 挡掉"，并留下可审计的 `authorize.decided` 事件。`permissions` 为空时**全部放行**
   * （V0.3.0 还没有权限授予链，放行 = 维持现状；真正的拦截在 T3-13 接入）。
   */
  #authorize(
    calls: readonly ModelToolCall[],
    permissions: readonly string[]
  ): AuthorizationDecision {
    if (permissions.length === 0) {
      return { allowed: calls, denied: [] };
    }
    const allowed: ModelToolCall[] = [];
    const denied: { call: ModelToolCall; reason: string }[] = [];
    for (const call of calls) {
      if (permissions.includes(`tool:${call.name}`) || permissions.includes("*")) {
        allowed.push(call);
      } else {
        denied.push({ call, reason: `缺少权限 tool:${call.name}` });
      }
    }
    return { allowed, denied };
  }

  /**
   * 执行工具批（第 7 步）。
   *
   * 两个上限在这里生效：
   *   - **`maxToolCallsPerTurn`**：超出部分**不执行**（`skippedCount`），
   *     由第 9 步的停止判定收尾 —— 不是"多执行几个然后再说"。
   *   - **拒绝/未知**的意图不送执行器，但**仍然生成 tool result**（拒绝型 observation），
   *     否则模型永远等不到这几条结果的回音（Harness §3 第 6 步："拒绝 → 生成拒绝型
   *     tool result（不抛异常）"）。
   */
  async #executeAll(
    context: RunCallContext,
    turn: number,
    authorization: AuthorizationDecision
  ): Promise<{
    turnToolCalls: number;
    executedCount: number;
    skippedCount: number;
    statuses: Record<string, number>;
    results: readonly { callId: string; toolName: string; content: string }[];
  }> {
    const results: { callId: string; toolName: string; content: string }[] = [];
    const statuses: Record<string, number> = {};
    let executedCount = 0;
    let turnToolCalls = 0;
    let skippedCount = 0;

    // 被拒的先落拒绝型结果（不占工具调用预算：它们没有真的执行）。
    for (const item of authorization.denied) {
      results.push({
        callId: item.call.id,
        toolName: item.call.name,
        content: JSON.stringify({ status: "DENIED", error: item.reason }),
      });
      statuses.DENIED = (statuses.DENIED ?? 0) + 1;
    }

    for (const call of authorization.allowed) {
      if (turnToolCalls >= this.#deps.limits.maxToolCallsPerTurn) {
        skippedCount += 1;
        continue;
      }
      if (context.signal.aborted) {
        results.push({
          callId: call.id,
          toolName: call.name,
          content: JSON.stringify({ status: "CANCELLED", error: "取消信号" }),
        });
        statuses.CANCELLED = (statuses.CANCELLED ?? 0) + 1;
        continue;
      }

      let result: ToolExecutionResult;
      try {
        result = await this.#deps.executor.execute(
          { callId: call.id, toolName: call.name, input: call.input },
          context
        );
      } catch (error) {
        // 执行器抛错也要变成 observation（否则模型这一轮就断了）。
        result = {
          status: "FAILED",
          error: error instanceof Error ? error.message : String(error),
          durationMs: 0,
        };
      }

      this.#deps.limits.maxToolCalls; // 保留引用，避免误删（累计上限由账本管）
      context.budget.addToolCall();
      executedCount += 1;
      turnToolCalls += 1;
      statuses[result.status] = (statuses[result.status] ?? 0) + 1;
      results.push({
        callId: call.id,
        toolName: call.name,
        content: JSON.stringify({
          status: result.status,
          ...(result.output === undefined ? {} : { output: result.output }),
          ...(result.error === undefined ? {} : { error: result.error }),
          duration_ms: result.durationMs,
        }),
      });
    }

    void turn;
    return { turnToolCalls, executedCount, skippedCount, statuses, results };
  }

  // -------------------------------------------------------------------------
  // 收尾
  // -------------------------------------------------------------------------

  /** 停表 + 落 `loop.finished` + 返回终局。 */
  async #finish(
    context: RunCallContext,
    input: {
      turn: number;
      totalToolCalls: number;
      status: LoopOutcome["status"];
      stopReason: StopReason | null;
      detail: string;
    }
  ): Promise<LoopOutcome> {
    const ledger = context.budget;
    // 相位机：`paused` 时不能 `stop()`（会抛），所以只在 running 时停表。
    try {
      ledger.stop();
    } catch {
      // 已经 stopped / 从未 start 的边界情形：停表不是业务路径，不因它中断收尾。
    }
    await this.#deps.events.appendInternal("loop.finished", {
      run_id: context.runId,
      turn: input.turn,
      status: input.status,
      stop_reason: input.stopReason,
      detail: input.detail,
      budget: ledger.snapshot(),
    });
    return Object.freeze({
      status: input.status,
      stopReason: input.stopReason,
      turns: input.turn,
      toolCalls: input.totalToolCalls,
      detail: input.detail,
    });
  }
}

/** 停止判定的再导出（测试与调用方只用这一处口径）。 */
export { evaluateStop };
export type { StopVerdict };
