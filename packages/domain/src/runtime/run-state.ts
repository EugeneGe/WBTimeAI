// @wbtime/domain · Run 状态机（纯 reducer）。
//
// 契约与裁定来源：
//   · `01-Harness控制流规范.md` §2 目标状态机（原图 9 态）；
//   · `00-施工期裁定.md` **R3-01** —— `BUDGET_EXHAUSTED` / `TIMED_OUT` **不是状态**，
//     折叠为 `FAILED` + 对应 `stop_reason` ⇒ 实现 **7 态 / 11 条迁移**（9 条基本迁移 +
//     预算耗尽、全局超时这两条"同为 RUNNING→FAILED、`stop_reason` 不同"的迁移）；
//   · **R3-04** —— 终态必须带合法 `stop_reason`，非终态必须为空。
//
// 设计约束：
//   · **纯函数**：`applyRunEvent(state, event)` 只返回「下一个状态」或「拒绝」，**不抛异常**、
//     不写库、不读时钟（Harness §2「状态迁移由纯函数校验器统一把关」）；
//   · 终态后零事件（Harness §1-5）：任何事件在终态上都被拒绝，reason = `TERMINAL_STATE`；
//   · 非法转移**不静默忽略**，返回可断言的拒绝码（便于"改坏必红"）。

import { DOMAIN_ERROR_CODES, DomainError } from "../errors.js";
import { RUN_STATUSES, isTerminalRunStatus, type RunStatus } from "./run-status.js";
import {
  STOP_REASONS,
  allowedStopReasons,
  isStopReasonAllowed,
  type StopReason,
} from "./run-stop-reason.js";

/** Run 的可迁移状态（`stop_reason` 与 `status` 恒成对出现）。 */
export interface RunState {
  readonly status: RunStatus;
  readonly stopReason: StopReason | null;
}

/** 初始状态：`QUEUED` + 无 `stop_reason`（v0019 默认值）。 */
export function initialRunState(): RunState {
  return Object.freeze({ status: "QUEUED", stopReason: null });
}

/**
 * 11 个迁移事件。
 *
 * `FAIL` 与 `EXHAUST_BUDGET` 携带 `stopReason`（因为同一个 `RUNNING → FAILED` 迁移有 8 种原因）；
 * 其余事件的 `stop_reason` 由表固定，调用方无权指定。
 */
export type RunEvent =
  | { readonly type: "ACQUIRE_LEASE" }
  | { readonly type: "REQUEST_APPROVAL" }
  | { readonly type: "APPROVE" }
  | { readonly type: "REJECT" }
  | { readonly type: "REQUEST_INPUT" }
  | { readonly type: "PROVIDE_INPUT" }
  | { readonly type: "COMPLETE" }
  | { readonly type: "FAIL"; readonly stopReason: StopReason }
  | { readonly type: "CANCEL" }
  | { readonly type: "EXHAUST_BUDGET"; readonly stopReason: StopReason }
  | { readonly type: "TIMEOUT" };

export type RunEventType = RunEvent["type"];

/** 拒绝码（可断言，不依赖错误文案）。 */
export type RunRejectionCode = "TERMINAL_STATE" | "ILLEGAL_TRANSITION" | "ILLEGAL_STOP_REASON";

export type RunEventResult =
  | { readonly ok: true; readonly state: RunState }
  | { readonly ok: false; readonly code: RunRejectionCode; readonly detail: string };

interface TransitionRule {
  readonly from: RunStatus;
  readonly to: RunStatus;
  /** `fixed` = 由规则固定；`payload` = 由事件携带并校验；`none` = 必须为空。 */
  readonly stopReason: "none" | "fixed" | "payload";
  readonly fixedStopReason?: StopReason;
}

/**
 * 迁移表 —— **11 条**，与任务卡 `T3-04` 验收口径 ① 一一对应。
 *
 * 注意 `FAIL` / `EXHAUST_BUDGET` / `TIMEOUT` 三条都落在 `RUNNING → FAILED`，
 * 但它们携带的 `stop_reason` 不同 ⇒ 计为 3 条独立迁移（R3-01 的折叠口径）。
 */
export const RUN_TRANSITIONS: Readonly<Record<RunEventType, TransitionRule>> = Object.freeze({
  ACQUIRE_LEASE: { from: "QUEUED", to: "RUNNING", stopReason: "none" },
  REQUEST_APPROVAL: { from: "RUNNING", to: "WAITING_APPROVAL", stopReason: "none" },
  APPROVE: { from: "WAITING_APPROVAL", to: "RUNNING", stopReason: "none" },
  REJECT: {
    from: "WAITING_APPROVAL",
    to: "CANCELLED",
    stopReason: "fixed",
    fixedStopReason: "approval_rejected",
  },
  REQUEST_INPUT: { from: "RUNNING", to: "WAITING_INPUT", stopReason: "none" },
  PROVIDE_INPUT: { from: "WAITING_INPUT", to: "RUNNING", stopReason: "none" },
  COMPLETE: {
    from: "RUNNING",
    to: "SUCCEEDED",
    stopReason: "fixed",
    fixedStopReason: "model_finish",
  },
  FAIL: { from: "RUNNING", to: "FAILED", stopReason: "payload" },
  CANCEL: {
    from: "RUNNING",
    to: "CANCELLED",
    stopReason: "fixed",
    fixedStopReason: "cancelled",
  },
  EXHAUST_BUDGET: { from: "RUNNING", to: "FAILED", stopReason: "payload" },
  TIMEOUT: {
    from: "RUNNING",
    to: "FAILED",
    stopReason: "fixed",
    fixedStopReason: "wall_time",
  },
});

/** 迁移表里的 11 条边（`[from, to, event]`），供"条数恰为 11"这类断言直接消费。 */
export const RUN_TRANSITION_EDGES: readonly {
  readonly event: RunEventType;
  readonly from: RunStatus;
  readonly to: RunStatus;
}[] = Object.freeze(
  (Object.keys(RUN_TRANSITIONS) as RunEventType[]).map((event) =>
    Object.freeze({ event, ...RUN_TRANSITIONS[event] }),
  ),
);

/** 事件携带的 `stop_reason` 是否在该迁移的允许集合内。 */
function payloadStopReasonAllowed(event: RunEvent, rule: TransitionRule): boolean {
  if (event.type !== "FAIL" && event.type !== "EXHAUST_BUDGET") return false;
  if (!isStopReasonAllowed(rule.to, event.stopReason)) return false;
  // `EXHAUST_BUDGET` 只接四项预算原因；`FAIL` 接其余（含预算，便于"预算检查晚于失败"的边角）。
  if (event.type === "EXHAUST_BUDGET") return event.stopReason.startsWith("budget_");
  return true;
}

/**
 * 应用一个事件：返回**下一个状态**或**拒绝**（纯函数，不抛异常）。
 *
 * 拒绝优先级：终态 → 非法转移 → 非法 `stop_reason`。
 */
export function applyRunEvent(state: RunState, event: RunEvent): RunEventResult {
  if (isTerminalRunStatus(state.status)) {
    return {
      ok: false,
      code: "TERMINAL_STATE",
      detail: `run 已处于终态 ${state.status}，拒绝事件 ${event.type}（终态后零事件）`,
    };
  }

  const rule = RUN_TRANSITIONS[event.type];
  if (state.status !== rule.from) {
    return {
      ok: false,
      code: "ILLEGAL_TRANSITION",
      detail: `事件 ${event.type} 要求 ${rule.from}，当前 ${state.status}`,
    };
  }

  let stopReason: StopReason | null = null;
  if (rule.stopReason === "fixed") {
    stopReason = rule.fixedStopReason ?? null;
  } else if (rule.stopReason === "payload") {
    if (!payloadStopReasonAllowed(event, rule)) {
      return {
        ok: false,
        code: "ILLEGAL_STOP_REASON",
        detail: `事件 ${event.type} 的 stop_reason 非法：${String(
          (event as { stopReason?: unknown }).stopReason,
        )}；允许值 = ${(allowedStopReasons(rule.to) ?? []).join(" / ")}`,
      };
    }
    stopReason = event.type === "FAIL" || event.type === "EXHAUST_BUDGET" ? event.stopReason : null;
  }

  // 双保险：产物必须过 R3-04 矩阵（构造上已成立，这里挡住后续误改迁移表）。
  if (!isStopReasonAllowed(rule.to, stopReason)) {
    return {
      ok: false,
      code: "ILLEGAL_STOP_REASON",
      detail: `迁移 ${state.status} → ${rule.to} 产出的组合非法：stop_reason=${String(stopReason)}`,
    };
  }

  return { ok: true, state: Object.freeze({ status: rule.to, stopReason }) };
}

/**
 * 断言一个 `RunState` 自洽（**读取侧**用：`GET /runs/{id}` 序列化前）。
 *
 * 校验三件事：`status` ∈ 7 值、`stop_reason` ∈ 11 值、两者组合在 R3-04 矩阵内。
 */
export function assertRunState(state: RunState): void {
  if (!(RUN_STATUSES as readonly string[]).includes(state.status)) {
    throw new DomainError(`未知 run 状态：${String(state.status)}`, DOMAIN_ERROR_CODES.VALIDATION_ERROR, {
      status: state.status,
    });
  }
  if (state.stopReason !== null && !(STOP_REASONS as readonly string[]).includes(state.stopReason)) {
    throw new DomainError(
      `未知 stop_reason：${String(state.stopReason)}`,
      DOMAIN_ERROR_CODES.VALIDATION_ERROR,
      { stopReason: state.stopReason },
    );
  }
  if (!isStopReasonAllowed(state.status, state.stopReason)) {
    throw new DomainError(
      `run 状态与 stop_reason 不匹配：${state.status} + ${String(state.stopReason)}`,
      DOMAIN_ERROR_CODES.VALIDATION_ERROR,
      { status: state.status, stopReason: state.stopReason },
    );
  }
}
