// ---------------------------------------------------------------------------
// WBTimeAI · 专家（Agent）展示层纯函数单测（V0.4.6 · D-UI 优化波）
//
// 覆盖：类型 / 状态映射（含未知值原样透出）、相对时间全部分档与边界、
//       `updated_at || created_at` 取值口径、列表排序（最近更新 / 名称）。
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";

import { translate } from "@/i18n";
import {
  AGENT_TYPE_OPTIONS,
  agentDisplayStatus,
  agentStatusKey,
  agentStatusLabel,
  agentTimestamp,
  agentTypeKey,
  agentTypeLabel,
  describeRelativeTime,
  formatRelativeTime,
  sortAgents,
  type TranslateFn,
} from "@/lib/agentDisplay";
import type { AgentResponse } from "@/types";

/** 绑定中文的翻译桩（与 `useTranslation().t` 同签名）。 */
const t: TranslateFn = (key, params) => translate("zh-CN", key, params);

/** 构造最小 Agent 响应。 */
function makeAgent(overrides: Partial<AgentResponse>): AgentResponse {
  return {
    id: "a1",
    name: "示例专家",
    description: null,
    type: "PRIMARY",
    status: "DRAFT",
    created_by: "u1",
    created_at: "2026-10-01T10:00:00",
    updated_at: "2026-10-02T10:00:00",
    ...overrides,
  };
}

describe("agentDisplay · 类型映射", () => {
  it("五种类型全部映射为中文（顺序冻结）", () => {
    expect(AGENT_TYPE_OPTIONS).toEqual([
      "PRIMARY",
      "SUB_AGENT",
      "WORKFLOW_AGENT",
      "SCHEDULED_AGENT",
      "EVENT_AGENT",
    ]);
    expect(agentTypeLabel("PRIMARY", t)).toBe("主智能体");
    expect(agentTypeLabel("SUB_AGENT", t)).toBe("子智能体");
    expect(agentTypeLabel("WORKFLOW_AGENT", t)).toBe("工作流智能体");
    expect(agentTypeLabel("SCHEDULED_AGENT", t)).toBe("定时智能体");
    expect(agentTypeLabel("EVENT_AGENT", t)).toBe("事件智能体");
  });

  it("未知类型原样显示；空类型回落占位符", () => {
    expect(agentTypeKey("PRIMARY")).toBe("agents.type.primary");
    expect(agentTypeKey("SOMETHING_NEW")).toBeNull();
    expect(agentTypeLabel("SOMETHING_NEW", t)).toBe("SOMETHING_NEW");
    expect(agentTypeLabel(null, t)).toBe("—");
    expect(agentTypeLabel("", t)).toBe("—");
  });
});

describe("agentDisplay · 状态映射", () => {
  it("三种状态映射为界面术语「已发布 / 草稿 / 已归档」", () => {
    expect(agentStatusLabel("ACTIVE", t)).toBe("已发布");
    expect(agentStatusLabel("DRAFT", t)).toBe("草稿");
    expect(agentStatusLabel("ARCHIVED", t)).toBe("已归档");
    expect(agentStatusKey("ACTIVE")).toBe("agents.status.published");
  });

  it("展示分组用于徽标配色与主操作分支", () => {
    expect(agentDisplayStatus("ACTIVE")).toBe("published");
    expect(agentDisplayStatus("DRAFT")).toBe("draft");
    expect(agentDisplayStatus("ARCHIVED")).toBe("archived");
    expect(agentDisplayStatus("PAUSED")).toBe("unknown");
    expect(agentDisplayStatus(null)).toBe("unknown");
  });

  it("未知状态原样显示，不吞掉后端新枚举", () => {
    expect(agentStatusLabel("PAUSED", t)).toBe("PAUSED");
    expect(agentStatusLabel(undefined, t)).toBe("—");
  });
});

describe("agentDisplay · 相对时间分档", () => {
  const now = new Date("2026-10-18T12:00:00");

  it("刚刚（< 1 分钟）", () => {
    expect(describeRelativeTime("2026-10-18T11:59:30", now)).toEqual({ kind: "justNow" });
    expect(formatRelativeTime("2026-10-18T11:59:59", t, now)).toBe("刚刚");
  });

  it("分钟档（1–59 分钟）", () => {
    expect(describeRelativeTime("2026-10-18T11:59:00", now)).toEqual({
      kind: "minutes",
      count: 1,
    });
    expect(formatRelativeTime("2026-10-18T11:01:00", t, now)).toBe("59 分钟前");
  });

  it("小时档（1–23 小时）", () => {
    expect(describeRelativeTime("2026-10-18T11:00:00", now)).toEqual({ kind: "hours", count: 1 });
    expect(formatRelativeTime("2026-10-18T10:00:00", t, now)).toBe("2 小时前");
    expect(formatRelativeTime("2026-10-17T13:00:00", t, now)).toBe("23 小时前");
  });

  it("昨天档（24–48 小时）", () => {
    expect(describeRelativeTime("2026-10-17T12:00:00", now)).toEqual({ kind: "yesterday" });
    expect(formatRelativeTime("2026-10-16T13:00:00", t, now)).toBe("昨天");
  });

  it("天档（2–29 天）", () => {
    expect(describeRelativeTime("2026-10-16T12:00:00", now)).toEqual({ kind: "days", count: 2 });
    expect(formatRelativeTime("2026-09-19T12:00:00", t, now)).toBe("29 天前");
  });

  it("超过 30 天 → 本地日期 YYYY-MM-DD", () => {
    expect(describeRelativeTime("2026-09-18T12:00:00", now)).toEqual({
      kind: "date",
      date: "2026-09-18",
    });
    expect(formatRelativeTime("2026-01-05T08:30:00", t, now)).toBe("2026-01-05");
  });

  it("未来时间（时钟漂移）按「刚刚」；空 / 非法返回 null", () => {
    expect(formatRelativeTime("2026-10-18T12:05:00", t, now)).toBe("刚刚");
    expect(describeRelativeTime(null, now)).toEqual({ kind: "unknown" });
    expect(formatRelativeTime("not-a-date", t, now)).toBeNull();
    expect(formatRelativeTime(undefined, t, now)).toBeNull();
  });
});

describe("agentDisplay · 取值与排序", () => {
  const now = new Date("2026-10-18T12:00:00");

  it("更新时间取 updated_at 优先、回落 created_at", () => {
    expect(agentTimestamp(makeAgent({ updated_at: "2026-10-17T12:00:00" }))).toBe(
      "2026-10-17T12:00:00",
    );
    expect(agentTimestamp(makeAgent({ updated_at: null, created_at: "2026-10-10T12:00:00" }))).toBe(
      "2026-10-10T12:00:00",
    );
    expect(agentTimestamp(makeAgent({ updated_at: null, created_at: null }))).toBeNull();
  });

  it("最近更新：倒序（时间缺失排最后），且不改入参", () => {
    const agents = [
      makeAgent({ id: "old", updated_at: "2026-09-01T10:00:00" }),
      makeAgent({ id: "new", updated_at: "2026-10-17T10:00:00" }),
      makeAgent({ id: "none", updated_at: null, created_at: null }),
      makeAgent({ id: "mid", updated_at: "2026-10-01T10:00:00" }),
    ];
    const sorted = sortAgents(agents, "updated");
    expect(sorted.map((agent) => agent.id)).toEqual(["new", "mid", "old", "none"]);
    expect(agents.map((agent) => agent.id)).toEqual(["old", "new", "none", "mid"]);
    // 相对时间断言在同一 now 下稳定可读。
    expect(formatRelativeTime(sorted[0].updated_at, t, now)).toBe("昨天");
  });

  it("按名称 A→Z（中文拼音序）", () => {
    const agents = [
      makeAgent({ id: "zhou", name: "周报撰写助手" }),
      makeAgent({ id: "dai", name: "代码评审助手" }),
      makeAgent({ id: "ri", name: "日志归因分析" }),
    ];
    expect(sortAgents(agents, "name").map((agent) => agent.id)).toEqual(["dai", "ri", "zhou"]);
  });
});
