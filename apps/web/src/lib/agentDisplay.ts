// ---------------------------------------------------------------------------
// WBTimeAI · 专家（Agent）展示层纯函数（V0.4.6 · D-UI 优化波 · 专家与智能体页）
//
// 目标：把「类型 / 状态 / 相对时间 / 更新时间取值」这类**展示口径**从组件里抽出来，
// 供 `ExpertCard` / `ExpertsTab` / 列表视图共用，并可单测（边界稳定、无 React 依赖）。
//
// 🔴 口径约束（施工单 §6）：
//   - 只用 `AgentResponse` 真实字段（`type` / `status` / `updated_at` / `created_at`）；
//   - **不存在**「版本号」字段（只有 `current_version_id`），本模块不派生任何 vN；
//   - 文案一律经 i18n：本模块只产出 **i18n key** 或调用注入的 `t`，不硬编码中文。
// ---------------------------------------------------------------------------
import type { AgentResponse } from "@/types";

/** 翻译函数签名（与 `@/i18n` 的 `t` 结构兼容，避免 lib → i18n 的运行时依赖）。 */
export type TranslateFn = (key: string, params?: Record<string, string | number>) => string;

// -- 类型（type）-------------------------------------------------------------

/** Agent 类型 → i18n key（未知类型不在映射内，调用方原样显示枚举值）。 */
export const AGENT_TYPE_KEYS: Readonly<Record<string, string>> = {
  PRIMARY: "agents.type.primary",
  SUB_AGENT: "agents.type.sub",
  WORKFLOW_AGENT: "agents.type.workflow",
  SCHEDULED_AGENT: "agents.type.scheduled",
  EVENT_AGENT: "agents.type.event",
};

/** 类型下拉可选值（顺序冻结：主 / 子 / 工作流 / 定时 / 事件）。 */
export const AGENT_TYPE_OPTIONS: readonly string[] = [
  "PRIMARY",
  "SUB_AGENT",
  "WORKFLOW_AGENT",
  "SCHEDULED_AGENT",
  "EVENT_AGENT",
];

/**
 * 取类型的 i18n key。
 *
 * @param type Agent 类型枚举值（可能为未知值 / 空）。
 * @returns 命中的 i18n key；未知类型返回 `null`（调用方回落原值）。
 */
export function agentTypeKey(type: string | null | undefined): string | null {
  if (!type) {
    return null;
  }
  return AGENT_TYPE_KEYS[type] ?? null;
}

/**
 * 类型的中文 / 英文展示文案。
 *
 * @param type Agent 类型枚举值。
 * @param t 绑定当前语言的翻译函数。
 * @param fallback 无类型时的兜底文案（缺省 `—`）。
 * @returns 已本地化文案；未知枚举 **原样返回**（不吞掉后端新值）。
 */
export function agentTypeLabel(
  type: string | null | undefined,
  t: TranslateFn,
  fallback = "—",
): string {
  if (!type) {
    return fallback;
  }
  const key = agentTypeKey(type);
  return key === null ? type : t(key);
}

// -- 状态（status）-----------------------------------------------------------

/** Agent 状态 → i18n key。 */
export const AGENT_STATUS_KEYS: Readonly<Record<string, string>> = {
  DRAFT: "agents.status.draft",
  ACTIVE: "agents.status.published",
  ARCHIVED: "agents.status.archived",
};

/** 展示用状态分组（未知状态归 `unknown`，不参与状态筛选计数）。 */
export type AgentDisplayStatus = "draft" | "published" | "archived" | "unknown";

/**
 * 取状态的 i18n key。
 *
 * @param status Agent 状态枚举值。
 * @returns 命中的 i18n key；未知状态返回 `null`。
 */
export function agentStatusKey(status: string | null | undefined): string | null {
  if (!status) {
    return null;
  }
  return AGENT_STATUS_KEYS[status] ?? null;
}

/**
 * 状态文案。
 *
 * @param status Agent 状态枚举值。
 * @param t 翻译函数。
 * @param fallback 无状态时的兜底文案（缺省 `—`）。
 * @returns 已本地化文案；未知状态原样返回。
 */
export function agentStatusLabel(
  status: string | null | undefined,
  t: TranslateFn,
  fallback = "—",
): string {
  if (!status) {
    return fallback;
  }
  const key = agentStatusKey(status);
  return key === null ? status : t(key);
}

/**
 * 状态的展示分组（用于徽标配色与主操作分支）。
 *
 * @param status Agent 状态枚举值。
 * @returns `draft` / `published` / `archived`；其余为 `unknown`。
 */
export function agentDisplayStatus(status: string | null | undefined): AgentDisplayStatus {
  if (status === "DRAFT") {
    return "draft";
  }
  if (status === "ACTIVE") {
    return "published";
  }
  if (status === "ARCHIVED") {
    return "archived";
  }
  return "unknown";
}

// -- 相对时间 ----------------------------------------------------------------

/** 分钟 / 小时 / 天的毫秒基数。 */
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
/** 超过该天数 → 直接显示日期（`YYYY-MM-DD`）。 */
const DATE_THRESHOLD_DAYS = 30;

/** 相对时间的分档结果（纯数据，便于单测与多语言渲染）。 */
export type RelativeTime =
  | { kind: "justNow" }
  | { kind: "minutes"; count: number }
  | { kind: "hours"; count: number }
  | { kind: "yesterday" }
  | { kind: "days"; count: number }
  | { kind: "date"; date: string }
  | { kind: "unknown" };

/** 两位补零。 */
function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}

/** 本地日期 `YYYY-MM-DD`（后端时间戳为无时区本地 ISO，按本地解析即可）。 */
export function formatLocalDate(value: Date): string {
  return `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`;
}

/**
 * 把 ISO 时间串解析为 `Date`（空 / 非法 → `null`）。
 *
 * @param iso 无时区本地 ISO 串（如 `2026-10-14T09:30:00`）。
 * @returns 合法 `Date`，否则 `null`。
 */
export function parseTimestamp(iso: string | null | undefined): Date | null {
  if (!iso) {
    return null;
  }
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * 相对时间分档。
 *
 * 口径：刚刚（< 1 分钟）/ N 分钟前（< 1 小时）/ N 小时前（< 24 小时）/
 * 昨天（24–48 小时）/ N 天前（2–29 天）/ `YYYY-MM-DD`（≥ 30 天）。
 * 未来时间（时钟漂移）按「刚刚」处理。
 *
 * @param iso 时间串。
 * @param now 参照时刻（缺省 `new Date()`；测试注入固定时刻）。
 * @returns 分档结果。
 */
export function describeRelativeTime(
  iso: string | null | undefined,
  now: Date = new Date(),
): RelativeTime {
  const target = parseTimestamp(iso);
  if (target === null) {
    return { kind: "unknown" };
  }
  const diff = now.getTime() - target.getTime();
  if (diff < MINUTE_MS) {
    return { kind: "justNow" };
  }
  if (diff < HOUR_MS) {
    return { kind: "minutes", count: Math.floor(diff / MINUTE_MS) };
  }
  if (diff < DAY_MS) {
    return { kind: "hours", count: Math.floor(diff / HOUR_MS) };
  }
  if (diff < 2 * DAY_MS) {
    return { kind: "yesterday" };
  }
  if (diff < DATE_THRESHOLD_DAYS * DAY_MS) {
    return { kind: "days", count: Math.floor(diff / DAY_MS) };
  }
  return { kind: "date", date: formatLocalDate(target) };
}

/**
 * 相对时间的本地化文案。
 *
 * @param iso 时间串。
 * @param t 翻译函数。
 * @param now 参照时刻（测试注入）。
 * @returns 文案；无时间 / 非法时间返回 `null`（调用方省略该段）。
 */
export function formatRelativeTime(
  iso: string | null | undefined,
  t: TranslateFn,
  now: Date = new Date(),
): string | null {
  const relative = describeRelativeTime(iso, now);
  switch (relative.kind) {
    case "justNow":
      return t("agents.time.justNow");
    case "minutes":
      return t("agents.time.minutesAgo", { count: relative.count });
    case "hours":
      return t("agents.time.hoursAgo", { count: relative.count });
    case "yesterday":
      return t("agents.time.yesterday");
    case "days":
      return t("agents.time.daysAgo", { count: relative.count });
    case "date":
      return relative.date;
    case "unknown":
    default:
      return null;
  }
}

// -- Agent 派生视图 ----------------------------------------------------------

/** Agent 的「最近更新」时间串（`updated_at` 优先，回落 `created_at`）。 */
export function agentTimestamp(agent: AgentResponse): string | null {
  return agent.updated_at ?? agent.created_at ?? null;
}

/**
 * Agent 的相对更新时间文案。
 *
 * @param agent Agent 响应。
 * @param t 翻译函数。
 * @param now 参照时刻。
 * @returns 文案；两者皆无 / 非法 → `null`。
 */
export function formatAgentUpdatedAt(
  agent: AgentResponse,
  t: TranslateFn,
  now: Date = new Date(),
): string | null {
  return formatRelativeTime(agentTimestamp(agent), t, now);
}

/** 列表排序方式（冻结两档：最近更新 / 名称 A→Z）。 */
export type AgentSortMode = "updated" | "name";

/**
 * 排序 Agent 列表（纯前端，不改入参）。
 *
 * `updated`：按 `updated_at || created_at` 倒序（缺失时间的排最后）；
 * `name`：按名称本地化比较（`zh-CN` 拼音序），大小写不敏感。
 *
 * @param agents 原始列表。
 * @param mode 排序方式。
 * @returns 新数组。
 */
export function sortAgents(agents: readonly AgentResponse[], mode: AgentSortMode): AgentResponse[] {
  const next = [...agents];
  if (mode === "name") {
    next.sort((left, right) => left.name.localeCompare(right.name, "zh-CN"));
    return next;
  }
  next.sort((left, right) => {
    const leftTime = parseTimestamp(agentTimestamp(left))?.getTime() ?? 0;
    const rightTime = parseTimestamp(agentTimestamp(right))?.getTime() ?? 0;
    return rightTime - leftTime;
  });
  return next;
}
