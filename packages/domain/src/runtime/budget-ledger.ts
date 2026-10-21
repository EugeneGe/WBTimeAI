// @wbtime/domain · 预算账本（活动时钟）。
//
// 来源：`00-施工期裁定.md` **R3-07**（审批等待期间墙钟预算暂停、等待单独计时）
//       + **R3-15**（`runtime.max_wall_time_ms` 600000 默认 / 3600000 上界；
//         `max_model_turns` 20 / `max_tool_calls` 50 等）+ **R3-01**（四项预算折叠为 FAILED）。
//
// 核心语义：`maxWallTimeMs` **只累计活动执行时间**（模型请求 + 工具执行 + 循环开销）。
// 进入 `WAITING_APPROVAL` / `WAITING_INPUT` 调 `pause()`，恢复 `resume()`。
// 否则「用户无限挂起审批」就能耗尽预算 —— 这正是 R3-07 要修的病。
//
// 时钟必须可注入（`nowMs`）：测试用假时钟推进，不依赖真实等待。
// 纯内存对象，零 ORM / 零 Web / 不写库。

import { DOMAIN_ERROR_CODES, DomainError } from "../errors.js";
import { pickBudgetStopReason, type StopReason } from "./run-stop-reason.js";

/** 预算上限（字段名对齐 R3-15 的配置项语义，但只保留域层需要的五项）。 */
export interface BudgetLimits {
  readonly maxWallTimeMs: number;
  readonly maxTokens: number;
  readonly maxCost: number;
  readonly maxTurns: number;
  readonly maxToolCalls: number;
}

/** 账本快照（供观测 / 审计 / 断言）。 */
export interface BudgetSnapshot {
  readonly activeWallTimeMs: number;
  readonly waitingWallTimeMs: number;
  readonly tokens: number;
  readonly cost: number;
  readonly turns: number;
  readonly toolCalls: number;
  /** 四项预算里最先耗尽的一项（R3-01 优先序）；未耗尽 = `null`。 */
  readonly exceeded: StopReason | null;
  /** 活动墙钟是否已超 `maxWallTimeMs`（对应 `TIMEOUT` 事件，不属四项预算）。 */
  readonly wallTimeExceeded: boolean;
}

type Phase = "idle" | "running" | "paused" | "stopped";

function assertPositiveNumber(name: string, value: number): void {
  if (!Number.isFinite(value) || value <= 0) {
    throw new DomainError(`预算上限 ${name} 必须是有限正数，实际 ${String(value)}`,
      DOMAIN_ERROR_CODES.CONFIGURATION_ERROR, { name, value });
  }
}

/**
 * 活动时钟 + 五项预算计数器。
 *
 * 相位机：`idle → running ⇄ paused → stopped`。非法相位调用**抛错**（不静默纠正），
 * 因为"在未运行的账本上 pause"通常意味着调用方算错了等待边界。
 */
export class BudgetLedger {
  readonly #limits: BudgetLimits;
  readonly #now: () => number;

  #phase: Phase = "idle";
  /** 已结算的活动执行时长（毫秒）。 */
  #activeMs = 0;
  /** 已结算的等待时长（毫秒；只观测，不计入预算）。 */
  #waitingMs = 0;
  /** 当前活动段起点（phase=running 时非空）。 */
  #activeSince: number | null = null;
  /** 当前等待段起点（phase=paused 时非空）。 */
  #waitingSince: number | null = null;

  #tokens = 0;
  #cost = 0;
  #turns = 0;
  #toolCalls = 0;

  /**
   * @param limits 五项上限（必须为正数，否则抛 `CONFIGURATION_ERROR`）。
   * @param nowMs  单调时钟，默认 `Date.now`；测试注入假时钟。
   */
  constructor(limits: BudgetLimits, nowMs: () => number = Date.now) {
    assertPositiveNumber("maxWallTimeMs", limits.maxWallTimeMs);
    assertPositiveNumber("maxTokens", limits.maxTokens);
    assertPositiveNumber("maxCost", limits.maxCost);
    assertPositiveNumber("maxTurns", limits.maxTurns);
    assertPositiveNumber("maxToolCalls", limits.maxToolCalls);
    this.#limits = Object.freeze({ ...limits });
    this.#now = nowMs;
  }

  /** 当前相位（只读）。 */
  get phase(): Phase {
    return this.#phase;
  }

  /** 开始执行（`idle → running`）。 */
  start(): void {
    if (this.#phase !== "idle") {
      throw new DomainError(`非法相位：start() 只能在 idle 调用，当前 ${this.#phase}`,
        DOMAIN_ERROR_CODES.VALIDATION_ERROR, { phase: this.#phase });
    }
    this.#phase = "running";
    this.#activeSince = this.#now();
  }

  /** 进入暂停态（`running → paused`）：活动时钟停走，开始累计等待时长。 */
  pause(): void {
    if (this.#phase !== "running") {
      throw new DomainError(`非法相位：pause() 只能在 running 调用，当前 ${this.#phase}`,
        DOMAIN_ERROR_CODES.VALIDATION_ERROR, { phase: this.#phase });
    }
    const now = this.#now();
    this.#activeMs += now - (this.#activeSince ?? now);
    this.#activeSince = null;
    this.#waitingSince = now;
    this.#phase = "paused";
  }

  /** 从暂停态恢复（`paused → running`）。 */
  resume(): void {
    if (this.#phase !== "paused") {
      throw new DomainError(`非法相位：resume() 只能在 paused 调用，当前 ${this.#phase}`,
        DOMAIN_ERROR_CODES.VALIDATION_ERROR, { phase: this.#phase });
    }
    const now = this.#now();
    this.#waitingMs += now - (this.#waitingSince ?? now);
    this.#waitingSince = null;
    this.#activeSince = now;
    this.#phase = "running";
  }

  /** 结束（`running|paused → stopped`）；重复调用幂等。 */
  stop(): void {
    if (this.#phase === "stopped" || this.#phase === "idle") {
      this.#phase = "stopped";
      return;
    }
    const now = this.#now();
    if (this.#phase === "running") this.#activeMs += now - (this.#activeSince ?? now);
    if (this.#phase === "paused") this.#waitingMs += now - (this.#waitingSince ?? now);
    this.#activeSince = null;
    this.#waitingSince = null;
    this.#phase = "stopped";
  }

  /** 活动执行时长（毫秒）—— 落库口径 `agent_run.duration_ms`（R3-07）。 */
  get activeWallTimeMs(): number {
    const live = this.#phase === "running" ? this.#now() - (this.#activeSince ?? this.#now()) : 0;
    return this.#activeMs + live;
  }

  /** 等待时长（毫秒）—— 只观测，进 `audit_log.metadata.wait_ms`，**不计入**预算。 */
  get waitingWallTimeMs(): number {
    const live = this.#phase === "paused" ? this.#now() - (this.#waitingSince ?? this.#now()) : 0;
    return this.#waitingMs + live;
  }

  /** 记一次模型调用的 token 用量。 */
  addTokens(tokens: number): void {
    if (!Number.isFinite(tokens) || tokens < 0) {
      throw new DomainError(`tokens 必须是非负有限数，实际 ${String(tokens)}`,
        DOMAIN_ERROR_CODES.VALIDATION_ERROR, { tokens });
    }
    this.#tokens += tokens;
  }

  /** 记一次模型调用的费用。 */
  addCost(cost: number): void {
    if (!Number.isFinite(cost) || cost < 0) {
      throw new DomainError(`cost 必须是非负有限数，实际 ${String(cost)}`,
        DOMAIN_ERROR_CODES.VALIDATION_ERROR, { cost });
    }
    this.#cost += cost;
  }

  /** 记一个模型轮次。 */
  addTurn(): void {
    this.#turns += 1;
  }

  /** 记一次工具调用。 */
  addToolCall(): void {
    this.#toolCalls += 1;
  }

  /** 四项预算中**最先耗尽**的一项（`turns > tools > tokens > cost`）；未耗尽 = `null`。 */
  exceeded(): StopReason | null {
    return pickBudgetStopReason({
      turns: this.#turns >= this.#limits.maxTurns,
      tools: this.#toolCalls >= this.#limits.maxToolCalls,
      tokens: this.#tokens >= this.#limits.maxTokens,
      cost: this.#cost >= this.#limits.maxCost,
    });
  }

  /** 活动墙钟是否超限（对应 `TIMEOUT` → `FAILED(wall_time)`）。 */
  isWallTimeExceeded(): boolean {
    return this.activeWallTimeMs >= this.#limits.maxWallTimeMs;
  }

  /** 快照。 */
  snapshot(): BudgetSnapshot {
    return Object.freeze({
      activeWallTimeMs: this.activeWallTimeMs,
      waitingWallTimeMs: this.waitingWallTimeMs,
      tokens: this.#tokens,
      cost: this.#cost,
      turns: this.#turns,
      toolCalls: this.#toolCalls,
      exceeded: this.exceeded(),
      wallTimeExceeded: this.isWallTimeExceeded(),
    });
  }

  /** 只读上限（调用方/测试断言用）。 */
  get limits(): BudgetLimits {
    return this.#limits;
  }
}
