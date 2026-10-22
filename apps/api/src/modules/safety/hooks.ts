/**
 * T3-14 · SafetyGate **六挂点接线**（补 T3-13 遗留 #2 #3）。
 *
 * 接线前实测：`SafetyGate` 全仓零装配点（`new SafetyGate` 命中 0），六个 stage 函数
 * 全部 `export` 却**无调用者** —— 也就是说 T3-13 交的是"能力"，不是"生效的闸"。
 * 本文件是那六个挂点的**唯一**调用面，每一处都写明"它卡在哪个动作之前/之后"。
 *
 * 五个挂点（S3 `delegation` 本版**不装配**，R3-17；第七个 stage 值只是值域占位）
 * -------------------------------------------------------------------------
 * | 挂点 | stage | 位置 | 短路语义 |
 * |---|---|---|---|
 * | **S1** | `input` | **run 创建之前**（`RunDriver.preflight`） | `DENY` ⇒ 422，run **不创建** |
 * | **S2** | `context` | Prepare（消息装载后、模型调用前） | `DENY` ⇒ 该 run `FAILED(SAFETY_DENIED)` |
 * | **S4** | `model_request` | 调模型之前（网关装饰器） | `DENY` ⇒ 不发出请求，run `FAILED` |
 * | **S5** | `tool_args` | `tool_call` intent 落盘后、Authorize 之前 | `DENY` ⇒ **不进执行器**（`tool_call.DENIED`） |
 * | **S6** | `tool_result` | Observe（结果落库前，**先检查后截断**） | `DENY` ⇒ 结果不外传，observation 记拒绝 |
 * | **S7** | `output` | Commit turn 之前（assistant 落库前） | `DENY` ⇒ 消息不落库，run `FAILED` |
 *
 * S6 的采样口径（R3-17 ①′ / 任务卡「采样：头 N/2 + 尾 N/2，先检查后截断」）
 * -------------------------------------------------------------------
 *   长工具输出（`MAX_OUTPUT_CHARS` 级别的 200k 字符）不可能整段送进规则引擎，
 *   但"截断后再检查"会漏掉**落在截断线之后**的违规片段 —— 那正好是最危险的位置
 *   （攻击者只要把 payload 塞在 4000 字符之后）。
 *
 *   所以：**先取头 N/2 + 尾 N/2 拼成检查视图送去检测，再按 N 截断作为落库/回传形态**。
 *   顺序不可换：`sampleToolResult()` 一次返回 `checked`（完整检查视图）与 `stored`
 *   （截断形态），调用方**没有**"只拿 stored 去检查"的接口可走。
 *   `safety-hooks.test.mjs` 的 CE 块钉死这条（把 checked 换成 stored ⇒ 尾部注入漏检 ⇒ 红）。
 */

import type { SafetyStage } from "@wbtime/domain";
import type { Provenance } from "@wbtime/security";

import { evaluateContext } from "./stages/context.js";
import { evaluateInput } from "./stages/input.js";
import { evaluateModelRequest } from "./stages/model-request.js";
import { evaluateOutput } from "./stages/output.js";
import { evaluateToolArgs } from "./stages/tool-args.js";
import { evaluateToolResult } from "./stages/tool-result.js";
import type { SafetyGate, SafetyVerdict } from "./gate.js";

/**
 * S6 采样窗口（字符）。**头 `WINDOW/2` + 尾 `WINDOW/2`**。
 *
 * 4000 的理由：`security` 的本地规则集最长的模式是 3 位凭据前缀 + 上下文，几千字符
 * 的窗口足以覆盖"一次真实泄露"，同时让一次检测的代价与输出长度**脱钩**（否则一个
 * 200k 输出的 docker build 日志会把一次 run 的安全开销放大 50 倍）。
 */
export const TOOL_RESULT_SAMPLE_WINDOW = 4000;

/** 采样结果：`checked` 送检测，`stored` 落库/回传。两者**不可互换**（见文件头注）。 */
export interface SampledContent {
  /** 送检测的完整视图（短内容 = 全文；长内容 = 头半 + 尾半）。 */
  readonly checked: string;
  /** 截断后的形态（长内容会被中段省略，并标注省略了多少字符）。 */
  readonly stored: string;
  /** 是否真的发生了采样（`false` ⇒ `checked === stored === 原文`）。 */
  readonly sampled: boolean;
  /** 被省略的字符数（`sampled=false` ⇒ 0）。 */
  readonly omittedChars: number;
}

/**
 * S6 采样：**先检查后截断**（一次调用同时给出两样东西）。
 *
 * @param content 原始工具输出。
 * @param window 窗口字符数（缺省 {@link TOOL_RESULT_SAMPLE_WINDOW}；必须 ≥ 2）。
 * @returns 见 {@link SampledContent}。
 */
export function sampleToolResult(
  content: string,
  window: number = TOOL_RESULT_SAMPLE_WINDOW
): SampledContent {
  if (window < 2) {
    throw new RangeError(`S6 采样窗口必须 ≥ 2（头半 + 尾半），实测 ${window}`);
  }
  if (content.length <= window) {
    return { checked: content, stored: content, sampled: false, omittedChars: 0 };
  }
  const half = Math.floor(window / 2);
  const head = content.slice(0, half);
  // 尾半取 `window - half`：窗口为奇数时不丢字符（头 + 尾 == window）。
  const tail = content.slice(content.length - (window - half));
  const omittedChars = content.length - head.length - tail.length;
  return {
    // 检查视图：头 + 尾直接相连（不插标记）—— 标记本身也可能被规则匹配到，
    // 那是噪声；这里要的是"两段原文都在检测视野内"。
    checked: `${head}${tail}`,
    stored: `${head}\n…[S6 采样：省略 ${omittedChars} 字符]…\n${tail}`,
    sampled: true,
    omittedChars,
  };
}

/** 挂点上下文（一次 run 内恒定）。 */
export interface SafetyHookContext {
  /**
   * run 标识。**S1 必须是 `null`**：run 还没创建，`audit_log.run_id` 有外键指向
   * `agent_run(id)` —— 填一个占位串（如 `"preflight"`）会让审计写入撞 FK 而**静默失败**
   * （`AuditLogRepo.create` 失败不抛），于是"该 stage 零判定记录"这条反例自己变成假绿。
   */
  readonly runId: string | null;
  readonly requestId: string;
  readonly conversationId: string | null;
}

/** 判定是否放行（`ALLOW` 或 `REDACT` 都算放行；`DENY` 才算拦下）。 */
export function isBlocked(verdict: SafetyVerdict): boolean {
  return verdict.decision === "DENY";
}

/**
 * 把判定**作用到文本**上：`DENY` ⇒ 拦下；`REDACT` ⇒ 换成同源脱敏后的文本。
 *
 * 为什么必须有一个统一入口：R3-16 的口径是"REDACT **不是**放行"，
 * 各挂点必须真的把脱敏结果用起来（否则审计写着 REDACT、实际下发原文 —— 那是最坏的
 * 一种假绿：记录说脱敏了，数据没脱敏）。
 *
 * @param verdict 判定。
 * @param text 原始文本。
 * @returns `blocked=true` ⇒ 调用方必须短路；否则用 `text` 继续。
 */
export function applyVerdict(
  verdict: SafetyVerdict,
  text: string
): { readonly blocked: boolean; readonly text: string } {
  if (verdict.decision === "DENY") return { blocked: true, text };
  if (verdict.decision === "REDACT") {
    return { blocked: false, text: verdict.redactedContent ?? text };
  }
  return { blocked: false, text };
}

/**
 * 六挂点的**统一门面**。
 *
 * 为什么不让调用方直接 `gate.evaluate({stage: ...})`：那样每个挂点都能自己选 stage，
 * "S5 被写成 S6"这种偏差在类型上完全合法（两者都是 `SafetyStage`）。本门面把
 * stage 写死在方法里，调用点只表达**语义**（`toolArgs` / `toolResult` / …）。
 */
export class SafetyHooks {
  readonly #gate: SafetyGate;
  readonly #context: SafetyHookContext;

  constructor(gate: SafetyGate, context: SafetyHookContext) {
    this.#gate = gate;
    this.#context = context;
  }

  /** 底层 gate（测试要单独断言 stage 时用；生产路径不绕开本门面）。 */
  get gate(): SafetyGate {
    return this.#gate;
  }

  /** 本门面的 run 上下文（`runId` / `requestId` 由装配方给一次）。 */
  get context(): SafetyHookContext {
    return this.#context;
  }

  /** **S1** · `input`（run 创建前）。 */
  stageInput(content: string): Promise<SafetyVerdict> {
    return evaluateInput(this.#gate, {
      content,
      requestId: this.#context.requestId,
      runId: this.#context.runId,
      conversationId: this.#context.conversationId,
    });
  }

  /** **S2** · `context`（Prepare：拼装后的上下文送模型前）。 */
  stageContext(content: string, provenance: Provenance = "user"): Promise<SafetyVerdict> {
    return evaluateContext(this.#gate, {
      content,
      provenance,
      requestId: this.#context.requestId,
      runId: this.#context.runId,
    });
  }

  /** **S4** · `model_request`（调模型前；本阶段无 REDACT，命中即 DENY）。 */
  stageModelRequest(content: string): Promise<SafetyVerdict> {
    return evaluateModelRequest(this.#gate, {
      content,
      requestId: this.#context.requestId,
      runId: this.#context.runId,
    });
  }

  /** **S5** · `tool_args`（intent 已落盘、Authorize 之前）。 */
  stageToolArgs(toolCallId: string, content: string): Promise<SafetyVerdict> {
    return evaluateToolArgs(this.#gate, {
      content,
      requestId: this.#context.requestId,
      runId: this.#context.runId,
      toolCallId,
    });
  }

  /**
   * **S6** · `tool_result`（Observe；provenance 恒 `untrusted`）。
   *
   * @param toolCallId 工具调用 id（进审计 `tool_call_id`）。
   * @param content **完整**原文（采样在 {@link sampleToolResult} 里做，本方法只判定）。
   * @param window 采样窗口（缺省 {@link TOOL_RESULT_SAMPLE_WINDOW}）。
   * @returns 判定 + 采样结果（调用方据 `sampled.stored` 落库）。
   */
  async stageToolResult(
    toolCallId: string,
    content: string,
    window: number = TOOL_RESULT_SAMPLE_WINDOW
  ): Promise<{ readonly verdict: SafetyVerdict; readonly sampled: SampledContent }> {
    const sampled = sampleToolResult(content, window);
    // ⚠️ 顺序红线：先检查（`sampled.checked`），检查完才轮到调用方用 `sampled.stored`。
    const verdict = await evaluateToolResult(this.#gate, {
      content: sampled.checked,
      requestId: this.#context.requestId,
      runId: this.#context.runId,
      toolCallId,
    });
    return { verdict, sampled };
  }

  /**
   * **S7** · `output`（Commit turn 前 + 流式期终态兜底）。
   *
   * `incident` / `deliveredUnits` 承接 §16 反例 #17（①′）：流式期已下发片段后复核命中
   * ⇒ 审计记 `incident=true` + `delivered_units>0`。
   */
  stageOutput(content: string, options: { incident?: boolean; deliveredUnits?: number } = {}): Promise<SafetyVerdict> {
    return evaluateOutput(this.#gate, {
      content,
      requestId: this.#context.requestId,
      runId: this.#context.runId,
      conversationId: this.#context.conversationId,
      ...(options.incident === undefined ? {} : { incident: options.incident }),
      ...(options.deliveredUnits === undefined ? {} : { deliveredUnits: options.deliveredUnits }),
    });
  }
}

/** 本版装配的挂点（S3 `delegation` **不在**其中 —— R3-17；门禁断言其审计行数恒 0）。 */
export const WIRED_SAFETY_STAGES: readonly SafetyStage[] = [
  "input",
  "context",
  "model_request",
  "tool_args",
  "tool_result",
  "output",
] as const;

/** 未装配的 stage（本版恒 0 行；与 `WIRED_SAFETY_STAGES` 互补）。 */
export const UNWIRED_SAFETY_STAGES: readonly SafetyStage[] = ["delegation"] as const;
