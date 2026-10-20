// ---------------------------------------------------------------------------
// WBTimeAI · uiStore 单测（V0.4.4 Bug5/8 新增行为 + V0.4.5 B1·F-04 侧栏宽度）
//
// 覆盖：页面搜索配置（setPageSearch 补丁合并）、右栏宽度（clamp 240–600 +
// localStorage 持久化）、提醒未读数（负数归零）；侧栏宽度（clamp 200–420 +
// 默认 212 + localStorage 持久化键 `wbtime-ai.sidebar-width`）。
// ---------------------------------------------------------------------------
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SIDEBAR_WIDTH_DEFAULT,
  SIDEBAR_WIDTH_MAX,
  SIDEBAR_WIDTH_MIN,
  useUiStore,
} from "@/stores/uiStore";

describe("uiStore · Bug5/8 新增行为", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({
      pageSearch: { enabled: false, placeholder: "", query: "" },
      rightPanelWidth: 300,
      sidebarWidth: SIDEBAR_WIDTH_DEFAULT,
      unreadCount: 0,
    });
  });

  it("setPageSearch：补丁合并（enabled/placeholder/query 各自独立更新）", () => {
    useUiStore.getState().setPageSearch({ enabled: true, placeholder: "搜索会话与消息…" });
    expect(useUiStore.getState().pageSearch).toEqual({
      enabled: true,
      placeholder: "搜索会话与消息…",
      query: "",
    });

    useUiStore.getState().setPageSearch({ query: "FAQ" });
    expect(useUiStore.getState().pageSearch.query).toBe("FAQ");
    expect(useUiStore.getState().pageSearch.enabled).toBe(true);

    useUiStore.getState().setPageSearch({ enabled: false, query: "" });
    expect(useUiStore.getState().pageSearch.enabled).toBe(false);
    expect(useUiStore.getState().pageSearch.query).toBe("");
  });

  it("setRightPanelWidth：clamp 240–600 并持久化", () => {
    useUiStore.getState().setRightPanelWidth(400);
    expect(useUiStore.getState().rightPanelWidth).toBe(400);
    expect(window.localStorage.getItem("wbtime-ai.right-panel-width")).toBe("400");

    // 越界收敛。
    useUiStore.getState().setRightPanelWidth(100);
    expect(useUiStore.getState().rightPanelWidth).toBe(240);
    useUiStore.getState().setRightPanelWidth(9999);
    expect(useUiStore.getState().rightPanelWidth).toBe(600);
  });

  it("setUnreadCount：0 隐藏红点口径（负数归零）", () => {
    useUiStore.getState().setUnreadCount(3);
    expect(useUiStore.getState().unreadCount).toBe(3);
    useUiStore.getState().setUnreadCount(-1);
    expect(useUiStore.getState().unreadCount).toBe(0);
  });
});

describe("uiStore · 侧栏宽度（V0.4.5 B1·F-04）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({ sidebarWidth: SIDEBAR_WIDTH_DEFAULT });
  });

  it("边界常量冻结：min 200 / max 420 / 默认 212", () => {
    expect(SIDEBAR_WIDTH_MIN).toBe(200);
    expect(SIDEBAR_WIDTH_MAX).toBe(420);
    expect(SIDEBAR_WIDTH_DEFAULT).toBe(212);
  });

  it("默认值：无持久化 → 读取回落默认 212", () => {
    expect(useUiStore.getState().sidebarWidth).toBe(SIDEBAR_WIDTH_DEFAULT);
  });

  it("setSidebarWidth：clamp 200–420 并写入持久化键", () => {
    useUiStore.getState().setSidebarWidth(320);
    expect(useUiStore.getState().sidebarWidth).toBe(320);
    expect(window.localStorage.getItem("wbtime-ai.sidebar-width")).toBe("320");

    // 下越界 → min；上越界 → max。
    useUiStore.getState().setSidebarWidth(10);
    expect(useUiStore.getState().sidebarWidth).toBe(SIDEBAR_WIDTH_MIN);
    expect(window.localStorage.getItem("wbtime-ai.sidebar-width")).toBe("200");

    useUiStore.getState().setSidebarWidth(9999);
    expect(useUiStore.getState().sidebarWidth).toBe(SIDEBAR_WIDTH_MAX);
    expect(window.localStorage.getItem("wbtime-ai.sidebar-width")).toBe("420");
  });

  it("持久化读写：已有合法值 → 重新加载即采用", async () => {
    window.localStorage.setItem("wbtime-ai.sidebar-width", "256");
    vi.resetModules();
    const { useUiStore: fresh } = await import("@/stores/uiStore");
    expect(fresh.getState().sidebarWidth).toBe(256);
  });

  it("越界持久化值读取即 clamp（>max → max，<min → min）", async () => {
    window.localStorage.setItem("wbtime-ai.sidebar-width", "9999");
    vi.resetModules();
    const { useUiStore: tooBig } = await import("@/stores/uiStore");
    expect(tooBig.getState().sidebarWidth).toBe(SIDEBAR_WIDTH_MAX);

    window.localStorage.setItem("wbtime-ai.sidebar-width", "10");
    vi.resetModules();
    const { useUiStore: tooSmall } = await import("@/stores/uiStore");
    expect(tooSmall.getState().sidebarWidth).toBe(SIDEBAR_WIDTH_MIN);

    window.localStorage.setItem("wbtime-ai.sidebar-width", "not-a-number");
    vi.resetModules();
    const { useUiStore: invalid } = await import("@/stores/uiStore");
    expect(invalid.getState().sidebarWidth).toBe(SIDEBAR_WIDTH_DEFAULT);
  });
});

// ---------------------------------------------------------------------------
// V0.4.6 · B-25：左侧栏可选模块（`railModules` + `toggleRailModule` / `setRailModules`）
//
// `uiStore` 在**模块加载时**读取 localStorage，故读取分支用例统一走
// `localStorage.setItem` → `vi.resetModules()` → 动态 `import` 取全新 store 实例
// （与该文件既有「持久化读写」范式一致）。
// ---------------------------------------------------------------------------
describe("uiStore · 左侧栏可选模块（V0.4.6 B-25）", () => {
  /** 模块初始化读取的持久化键。 */
  const RAIL_MODULES_KEY = "wbtime-ai.rail-modules";

  beforeEach(() => {
    window.localStorage.clear();
  });

  it("无持久化键 → 默认 [tasks, workflows]", async () => {
    vi.resetModules();
    const { useUiStore: fresh } = await import("@/stores/uiStore");

    expect(fresh.getState().railModules).toEqual(["tasks", "workflows"]);
  });

  it("非法 JSON（`{oops`）→ 回落默认（不抛错）", async () => {
    window.localStorage.setItem(RAIL_MODULES_KEY, "{oops");
    vi.resetModules();
    const { useUiStore: fresh } = await import("@/stores/uiStore");

    expect(fresh.getState().railModules).toEqual(["tasks", "workflows"]);
  });

  it("非数组（`{}`）→ 回落默认", async () => {
    window.localStorage.setItem(RAIL_MODULES_KEY, "{}");
    vi.resetModules();
    const { useUiStore: fresh } = await import("@/stores/uiStore");

    expect(fresh.getState().railModules).toEqual(["tasks", "workflows"]);
  });

  it("未知 key 混入 → 过滤为已注册 key（按注册表序）", async () => {
    window.localStorage.setItem(RAIL_MODULES_KEY, JSON.stringify(["tasks", "nope", "projects"]));
    vi.resetModules();
    const { useUiStore: fresh } = await import("@/stores/uiStore");

    expect(fresh.getState().railModules).toEqual(["tasks", "projects"]);
  });

  it("空数组合法（`[]`）→ []，不回落默认；再 toggleRailModule 落盘归一化", async () => {
    window.localStorage.setItem(RAIL_MODULES_KEY, "[]");
    vi.resetModules();
    const { useUiStore: fresh } = await import("@/stores/uiStore");

    // 空数组 = 用户把可选模块全关：**不得**回落默认。
    expect(fresh.getState().railModules).toEqual([]);

    fresh.getState().toggleRailModule("tasks");
    expect(fresh.getState().railModules).toEqual(["tasks"]);
    expect(window.localStorage.getItem(RAIL_MODULES_KEY)).toBe(JSON.stringify(["tasks"]));
  });

  it("toggleRailModule / setRailModules：关闭即移除、未知 key 丢弃、写入按注册表序归一化", () => {
    useUiStore.setState({ railModules: ["tasks", "workflows", "projects"] });

    // 关闭 tasks → 移除且落盘。
    useUiStore.getState().toggleRailModule("tasks");
    expect(useUiStore.getState().railModules).toEqual(["workflows", "projects"]);
    expect(window.localStorage.getItem(RAIL_MODULES_KEY)).toBe(
      JSON.stringify(["workflows", "projects"]),
    );

    // 批量设置：乱序 + 未知 key + 固定项 key → 只留可选模块，且按注册表序。
    useUiStore.getState().setRailModules(["memory", "nope", "knowledge", "tasks", "memory"]);
    expect(useUiStore.getState().railModules).toEqual(["tasks", "memory"]);
    expect(window.localStorage.getItem(RAIL_MODULES_KEY)).toBe(JSON.stringify(["tasks", "memory"]));

    // 全部关掉 → 空数组（合法值，且落盘）。
    useUiStore.getState().setRailModules([]);
    expect(useUiStore.getState().railModules).toEqual([]);
    expect(window.localStorage.getItem(RAIL_MODULES_KEY)).toBe("[]");

    // 固定项 key（agents）不可被 toggle 影响。
    useUiStore.getState().toggleRailModule("agents");
    expect(useUiStore.getState().railModules).toEqual([]);
  });
});
