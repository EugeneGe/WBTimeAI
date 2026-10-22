/**
 * T3-10 · `ToolExecutor` —— **四段事务边界**（DoD#6：intent → authorize → execute → result）。
 *
 * 四段与"每段崩溃可判定"
 * -------------------
 * | 段 | 崩溃形态 | 可判定证据 |
 * |---|---|---|
 * | **intent**（解析） | 工具不存在 / 名字写错 | `FAILED` + `errorCode=NOT_FOUND`，**未产生任何副作用** |
 * | **authorize** | 权限不足 | `DENIED` + `PERMISSION_DENIED`，**未执行**（验收 ⑥ 的 exec 计数 == 0） |
 * | **execute** | 工具抛错 / 超时 / 取消 | `FAILED` / `CANCELLED`，带 `durationMs` 与 `sandbox_session_id` |
 * | **result**（映射） | 总是成功（纯函数） | 上游拿到的 `ToolExecutionResult` 恒有 `status` + `durationMs` |
 *
 *   为什么"可判定"值得单独列一条：如果执行器在工具内部抛错时**向上抛**，调用方就只能看到
 *   "一次异常"，无法区分"没执行 / 执行一半 / 执行完但映射失败"。四段各自返回**终态**，
 *   任何一段崩掉都能从 `status + errorCode + durationMs` 反推发生在哪一段。
 *
 * 顺序红线（反例「先执行后检查 ⇒ E4 必红」）
 * --------------------------------------
 *   `authorize` **必须在** `execute` 之前。本文件的 `execute` 方法体顺序就是判据：
 *   解析 → 授权 → 执行。任何"先跑一下看看"的写法都会让 `DENIED` 用例里出现副作用。
 *
 * 本执行器**不写库**
 * ---------------
 *   `tool_call` 行的持久化（intent / running / terminal）由上层（`RunCoordinator` /
 *   T3-13 的挂点）负责。py `tool_executor.py` 的头注也是这么写的（"本执行器不写库"）。
 *   这样执行器可以脱离 DB 单测。
 */

import type {
  RunCallContext,
  ToolExecutionResult,
  ToolExecutorPort,
  ToolInvocation,
} from "@wbtime/domain";

import type { SandboxProvider, SandboxSession } from "../sandbox/types.js";
import { resolveTool, type BuiltinTool, type ToolContext } from "./registry.js";

/** 执行器依赖。 */
export interface ToolExecutorDeps {
  /** 默认超时（毫秒）；工具入参可覆盖。 */
  readonly timeoutMs?: number;
  /** Workspace 根（`filesystem` 的基准）。 */
  readonly workspaceRoot: string;
  /** 沙箱（需沙箱的工具用；缺省 ⇒ 那些工具会返回 `INTERNAL_ERROR`）。 */
  readonly sandbox?: SandboxProvider;
  /** 出网白名单（`http` / `git clone` 用）。 */
  readonly egressAllowlist?: readonly string[];
  /** scope 白名单。 */
  readonly allowedPaths?: readonly string[];
  /** 工具表覆盖（测试注入）。 */
  readonly tools?: ReadonlyMap<string, BuiltinTool>;
  /** 时钟（测试注入）。 */
  readonly now?: () => number;
}

/** 缺省超时。 */
export const DEFAULT_TOOL_TIMEOUT_MS = 30_000;

/**
 * 工具执行器。
 *
 * **会话缓存**：`runId → SandboxSession`。同一 run 的所有工具共用一个会话
 * （这样 `git clone` 之后 `git status` 能看到同一个工作目录）。
 * `destroy()` 由上层在 run 收尾时调用。
 */
export class ToolExecutor implements ToolExecutorPort {
  readonly #deps: ToolExecutorDeps;
  readonly #sessions = new Map<string, SandboxSession>();

  constructor(deps: ToolExecutorDeps) {
    this.#deps = deps;
  }

  /**
   * 执行一次工具调用（四段）。
   *
   * @param invocation `{callId, toolName, input}`。
   * @param context run 级上下文（取 `runId` / `tenantId` / `signal` / `permissions`）。
   */
  async execute(
    invocation: ToolInvocation,
    context: RunCallContext
  ): Promise<ToolExecutionResult> {
    const now = this.#deps.now ?? (() => Date.now());
    const startedAt = now();

    // ---- 段 1 · intent（解析） -----------------------------------------
    const tool = (this.#deps.tools ?? BUILTIN_LOOKUP).get(invocation.toolName) ?? resolveTool(invocation.toolName);
    if (tool === undefined) {
      return {
        status: "FAILED",
        error: `未知工具 ${JSON.stringify(invocation.toolName)}`,
        durationMs: now() - startedAt,
      };
    }

    // ---- 段 2 · authorize（**先于执行**） -------------------------------
    if (!this.#authorized(tool.name, context.permissions)) {
      return {
        status: "DENIED",
        error: `缺少权限 tool:${tool.name}`,
        durationMs: now() - startedAt,
      };
    }

    // ---- 段 3 · execute -------------------------------------------------
    if (context.signal.aborted) {
      return { status: "CANCELLED", error: "取消信号", durationMs: now() - startedAt };
    }

    // **有效超时**（AUD-04）：工具超时原本完全由模型给的 `timeout_ms` 决定
    // （`code_exec` / `shell` 直传沙箱，无上界），于是 `timeout_ms: 86400000` 能把一个
    // 「秒级」的 run 钉住一天；而 `RunCallContext.deadlineMs`（run 的绝对截止时刻）
    // 全仓**零消费** —— 声明得很清楚，却没有任何一处用它。
    //
    // 这里做两件事：
    //   ① `deadlineMs` 已过 ⇒ **不进工具**，直接 `FAILED` + `TOOL_TIMEOUT`
    //      （进入工具再判等于明知超预算还去跑）；
    //   ② 有效超时 = `min(执行器默认/显式配置, run 剩余时间)`，再经 `ToolContext.timeoutMs`
    //      下发。工具侧一律 `min(请求值, context.timeoutMs)` —— 模型只能**收紧**，
    //      不能放宽（cap 在可信侧计算）。
    const deadlineNow = now();
    const remainingMs = context.deadlineMs - deadlineNow;
    if (remainingMs <= 0) {
      return {
        status: "FAILED",
        error:
          `TOOL_TIMEOUT：run 的截止时刻已过（剩余 ${remainingMs}ms），` +
          `工具 ${tool.name} 未执行`,
        durationMs: deadlineNow - startedAt,
      };
    }
    const effectiveTimeoutMs = Math.min(
      this.#deps.timeoutMs ?? DEFAULT_TOOL_TIMEOUT_MS,
      remainingMs
    );

    // 段 3 的前置条件：需沙箱的工具必须先有沙箱。
    // 为什么在**执行器**判而不是让每个工具自判：5 个工具里 3 个需要沙箱，
    // 各自判会让"忘了判"成为一次真实的宿主直执行；集中一处则不可能漏。
    // （工具内部仍保留自检 —— 那是纵深防御，不是主判据。）
    if (tool.requiresSandbox && this.#deps.sandbox === undefined) {
      return {
        status: "FAILED",
        error: `工具 ${tool.name} 需要沙箱，但执行器未装配沙箱`,
        durationMs: now() - startedAt,
      };
    }

    const toolContext = await this.#toolContext(context, effectiveTimeoutMs);
    if (toolContext === undefined) {
      return {
        status: "FAILED",
        error: `工具 ${tool.name} 的上下文装配失败`,
        durationMs: now() - startedAt,
      };
    }

    let outcome: Awaited<ReturnType<BuiltinTool["execute"]>>;
    try {
      outcome = await tool.execute(
        isPlainObject(invocation.input) ? invocation.input : {},
        toolContext
      );
    } catch (error) {
      // 工具抛错 ⇒ 失败结果（不向上抛：调用方需要的是 observation，不是异常）
      return {
        status: context.signal.aborted ? "CANCELLED" : "FAILED",
        error: error instanceof Error ? error.message : String(error),
        durationMs: now() - startedAt,
      };
    }

    // ---- 段 4 · result（映射） -------------------------------------------
    const durationMs = outcome.durationMs > 0 ? outcome.durationMs : now() - startedAt;
    if (outcome.timedOut === true) {
      return {
        status: "FAILED",
        ...(outcome.error === undefined ? {} : { error: outcome.error }),
        durationMs,
      };
    }
    if (outcome.ok) {
      return {
        status: "SUCCESS",
        ...(outcome.output === undefined ? {} : { output: outcome.output }),
        ...(outcome.exitCode === undefined ? {} : { exitCode: outcome.exitCode }),
        durationMs,
      };
    }
    return {
      status: outcome.errorCode === "PERMISSION_DENIED" ? "DENIED" : "FAILED",
      ...(outcome.error === undefined ? {} : { error: outcome.error }),
      ...(outcome.exitCode === undefined ? {} : { exitCode: outcome.exitCode }),
      durationMs,
    };
  }

  /**
   * 销毁某 run 的沙箱会话（run 收尾时调用；**幂等**）。
   *
   * 落库口径（`sandbox_session.ended_at`）由 `LocalProcessSandbox` 的
   * `onSessionDestroyed` 回调负责。
   */
  async destroySession(runId: string): Promise<void> {
    const session = this.#sessions.get(runId);
    if (session === undefined) return;
    this.#sessions.delete(runId);
    await this.#deps.sandbox?.destroy(session);
  }

  /** 该 run 的会话是否已建（测试断言用）。 */
  hasSession(runId: string): boolean {
    return this.#sessions.has(runId);
  }

  /** 授权判定（空权限集 ⇒ 放行，维持 V0.3.0 现状；真正的裁决在 T3-13 的 SafetyGate）。 */
  #authorized(toolName: string, permissions: readonly string[]): boolean {
    if (permissions.length === 0) return true;
    return permissions.includes(`tool:${toolName}`) || permissions.includes("*");
  }

  /**
   * 按 run 建 / 取工具上下文。需沙箱但未装配 ⇒ `undefined`。
   *
   * `timeoutMs` 是**执行器算好的有效超时**（见 `execute` 的段 3）：它恒有值，
   * 且恒 ≤ `RunCallContext.deadlineMs` 的剩余时间 ⇒ 工具侧 `min(请求值, 它)` 即可，
   * 不需要（也不应该）自己去看 `deadlineMs`（那是 run 级概念，工具不该知道 run 的结构）。
   */
  async #toolContext(context: RunCallContext, timeoutMs: number): Promise<ToolContext | undefined> {
    const base: ToolContext = {
      workspaceRoot: this.#deps.workspaceRoot,
      ...(this.#deps.allowedPaths === undefined ? {} : { allowedPaths: this.#deps.allowedPaths }),
      ...(this.#deps.egressAllowlist === undefined
        ? {}
        : { egressAllowlist: this.#deps.egressAllowlist }),
      // 恒下发：没有它，工具只能信任模型给的 `timeout_ms`（AUD-04 的缺陷形态）。
      timeoutMs,
    };

    if (this.#deps.sandbox === undefined) {
      // 没有沙箱：无沙箱工具（filesystem / http）仍可执行，但它们不需要 session。
      return base;
    }

    let session = this.#sessions.get(context.runId);
    if (session === undefined) {
      session = await this.#deps.sandbox.createSession(this.#deps.workspaceRoot);
      this.#sessions.set(context.runId, session);
    }
    return { ...base, sandbox: this.#deps.sandbox, session };
  }
}

/** 空工具表（带覆盖时用不到；保留以避免 `??` 分支里出现 `undefined`）。 */
const BUILTIN_LOOKUP: ReadonlyMap<string, BuiltinTool> = new Map();

/** 简单对象判定。 */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
