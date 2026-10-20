// ---------------------------------------------------------------------------
// WBTimeAI · Rail 左侧栏单测（V0.4.6 · B-25 可配置模型重构）
//
// 覆盖：
//   ① 固定 4 项恒在（home / agents / knowledge / workbench）+ 默认可选模块 tasks / workflows；
//   ② 渲染顺序**冻结**：home → agents → knowledge → 已启用可选（注册表序）→ workbench；
//   ③ 未启用的可选模块**不在** document（approvals / projects / workspace /
//      remote-tasks / tools / studio / evaluation / memory 默认不上栏）；
//   ④ `railModules: ["tasks","projects"]` → projects 上栏、workflows 下栏、workbench 仍末位；
//   ⑤ `railModules: []` → 只剩固定 4 项；
//   ⑥ 预留槽位 `enterprise` 不渲染，且 `RAIL_ITEMS` 仍含 `enabled === false` 的条目；
//   ⑦ 既有断言保留：active 高亮（普通字符串 className）/ i18n 文案 / 提醒铃与红点
//      （W10 / T2-49 起红点与弹层内容由**真实待办数**驱动，故铃铛用例按接口打桩断言）。
//
// 包装：`Rail` 内含 `UserMenu`（用 `useNavigate` + `useQueryClient`）与铃铛的真实待办
// 查询（`useApprovals` → `GET /approvals`，W10 / T2-49），故需 `MemoryRouter` +
// `QueryClientProvider`；待办端点经 `server.use` **内联打桩**（不改共享 msw 夹具）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { FIXED_RAIL_ITEMS, OPTIONAL_RAIL_ITEMS, Rail, RAIL_ITEMS } from "@/components/layout/Rail";
import { ENTERPRISE_ROUTE_SLOT } from "@/router";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { DEFAULT_RAIL_MODULES, OPTIONAL_RAIL_KEYS, useUiStore } from "@/stores/uiStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** 固定 4 项（`data-testid` 后缀；品牌位另记为 `rail-home`）。 */
const FIXED_KEYS = ["home", "agents", "knowledge", "workbench"] as const;

/** 默认可选模块。 */
const DEFAULT_OPTIONAL_KEYS = ["tasks", "workflows"] as const;

/** 默认不上栏的可选模块（注册表中除 tasks / workflows 之外的 8 项）。 */
const HIDDEN_BY_DEFAULT_KEYS = [
  "approvals",
  "projects",
  "workspace",
  "remote-tasks",
  "tools",
  "studio",
  "evaluation",
  "memory",
] as const;

/** 渲染 Rail（独立 QueryClient + 路由上下文），可指定初始路径以驱动 active 态。 */
function renderRail(initialPath = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Rail />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * 渲染带路由表的 Rail（铃铛点击条目后断言真实跳转）。
 *
 * `/approvals` 落一个哨兵节点，便于断言 `navigate("/approvals")` 生效。
 */
function renderRailWithRoutes(initialPath = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/" element={<Rail />} />
          <Route path="/approvals" element={<div data-testid="approvals-route-sentinel" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** 铃铛待办夹具（`ApprovalResponse` 子集，仅铃铛展示所需字段）。 */
const BELL_APPROVALS = [
  {
    id: "ap1",
    tenant_id: "t1",
    subject_type: "workflow_node",
    subject_ref: "wf1:node-1",
    requested_by: "u-requester",
    status: "PENDING",
    decided_by: null,
    decided_at: null,
    payload: {},
    expires_at: null,
    created_at: "2026-10-13T00:00:00Z",
    updated_at: "2026-10-13T00:00:00Z",
  },
  {
    id: "ap2",
    tenant_id: "t1",
    subject_type: "tool",
    subject_ref: "tool-call-2",
    requested_by: "u-second",
    status: "PENDING",
    decided_by: null,
    decided_at: null,
    payload: {},
    expires_at: null,
    created_at: "2026-10-13T00:00:00Z",
    updated_at: "2026-10-13T00:00:00Z",
  },
] as const;

// 铃铛接了真实待办查询（W10 / T2-49）：默认打桩空列表，避免未打桩请求噪音；
// 需要数据的用例在用例体内再次 `server.use(...)` 覆盖（后注册优先）。
beforeEach(() => {
  server.use(http.get("/api/v1/approvals", () => shell([])));
});

/** 读取 Rail 内导航项的 `data-testid` 有序列表（品牌位 + 常规项，忽略底部铃铛 / 头像）。 */
function railTestIds(): string[] {
  const nav = screen.getByTestId("rail-nav");
  return Array.from(nav.querySelectorAll<HTMLElement>("[data-testid]"))
    .map((el) => el.dataset.testid ?? "")
    .filter((id) => id === "rail-home" || (id.startsWith("rail-nav-") && id !== "rail-nav"));
}

describe("Rail · 固定项与可选模块（V0.4.6 B-25）", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
    // 默认可选模块（UI store 初值来自 localStorage，用例内显式复位以保证独立）。
    useUiStore.setState({ railModules: [...DEFAULT_OPTIONAL_KEYS] });
  });

  it("固定 4 项恒在 + 默认可选模块（tasks / workflows）在栏", () => {
    renderRail();

    expect(screen.getByTestId("rail-home")).toBeInTheDocument();
    for (const key of ["agents", "knowledge", "workbench"] as const) {
      expect(screen.getByTestId(`rail-nav-${key}`)).toBeInTheDocument();
    }
    for (const key of DEFAULT_OPTIONAL_KEYS) {
      expect(screen.getByTestId(`rail-nav-${key}`)).toBeInTheDocument();
    }
  });

  it("渲染顺序冻结：home → agents → knowledge → tasks → workflows → workbench", () => {
    renderRail();

    expect(railTestIds()).toEqual([
      "rail-home",
      "rail-nav-agents",
      "rail-nav-knowledge",
      "rail-nav-tasks",
      "rail-nav-workflows",
      "rail-nav-workbench",
    ]);
  });

  it("默认不上栏的可选模块不在 document（8 项）", () => {
    renderRail();

    for (const key of HIDDEN_BY_DEFAULT_KEYS) {
      expect(screen.queryByTestId(`rail-nav-${key}`)).toBeNull();
    }
  });

  it("切换 railModules=[tasks, projects]：projects 上栏、workflows 下栏、workbench 仍末位", () => {
    useUiStore.setState({ railModules: ["tasks", "projects"] });
    renderRail();

    expect(screen.getByTestId("rail-nav-projects")).toBeInTheDocument();
    expect(screen.queryByTestId("rail-nav-workflows")).toBeNull();

    const ordered = railTestIds();
    expect(ordered).toEqual([
      "rail-home",
      "rail-nav-agents",
      "rail-nav-knowledge",
      "rail-nav-tasks",
      "rail-nav-projects",
      "rail-nav-workbench",
    ]);
    // 工作台恒为**最后一个导航项**。
    expect(ordered[ordered.length - 1]).toBe("rail-nav-workbench");
  });

  it("railModules=[] → 仅剩固定 4 项", () => {
    useUiStore.setState({ railModules: [] });
    renderRail();

    expect(railTestIds()).toEqual([
      "rail-home",
      "rail-nav-agents",
      "rail-nav-knowledge",
      "rail-nav-workbench",
    ]);
    for (const key of DEFAULT_OPTIONAL_KEYS) {
      expect(screen.queryByTestId(`rail-nav-${key}`)).toBeNull();
    }
  });

  it("注册表结构：固定 4 项 / 可选 10 项（注册表序）/ RAIL_ITEMS = 固定 + 可选 + enterprise", () => {
    expect(FIXED_RAIL_ITEMS.map((item) => item.key)).toEqual([...FIXED_KEYS]);
    expect(FIXED_RAIL_ITEMS.every((item) => item.group === "fixed")).toBe(true);

    expect(OPTIONAL_RAIL_ITEMS.map((item) => item.key)).toEqual([
      "tasks",
      "approvals",
      "workflows",
      "projects",
      "workspace",
      "remote-tasks",
      "tools",
      "studio",
      "evaluation",
      "memory",
    ]);
    expect(OPTIONAL_RAIL_ITEMS).toHaveLength(10);
    expect(OPTIONAL_RAIL_ITEMS.every((item) => item.group === "optional")).toBe(true);

    expect(RAIL_ITEMS).toHaveLength(FIXED_RAIL_ITEMS.length + OPTIONAL_RAIL_ITEMS.length + 1);
  });

  it("顺序契约：Rail.OPTIONAL_RAIL_ITEMS 与 uiStore.OPTIONAL_RAIL_KEYS 逐项同序", () => {
    expect(OPTIONAL_RAIL_ITEMS.map((item) => item.key)).toEqual([...OPTIONAL_RAIL_KEYS]);
  });

  it("审批中心（approvals）：已注册为可选项，但默认不上栏（不在 DEFAULT_RAIL_MODULES）", () => {
    expect(OPTIONAL_RAIL_KEYS).toContain("approvals");
    // 两条互补：一守「不含新项」，一守「整体未被他人悄悄扩写」（如把 projects 塞进默认值）。
    expect(DEFAULT_RAIL_MODULES).not.toContain("approvals");
    expect([...DEFAULT_RAIL_MODULES]).toEqual(["tasks", "workflows"]);

    const approvals = OPTIONAL_RAIL_ITEMS.find((item) => item.key === "approvals");
    expect(approvals).toBeDefined();
    expect(approvals?.to).toBe("/approvals");
    expect(approvals?.labelKey).toBe("nav.approvals");
  });

  it("企业入口隐藏：预留槽位不渲染（queryByTestId === null）", () => {
    renderRail();

    expect(screen.queryByTestId("rail-nav-enterprise")).toBeNull();
  });

  it("槽位保留：RAIL_ITEMS 仍含 enterprise 且 enabled === false", () => {
    const enterprise = RAIL_ITEMS.find((item) => item.key === "enterprise");

    expect(enterprise).toBeDefined();
    expect(enterprise?.enabled).toBe(false);
    expect(enterprise?.to).toBe("/enterprise");
  });

  it("路由空槽常量未误删：ENTERPRISE_ROUTE_SLOT.shipped === false", () => {
    expect(ENTERPRISE_ROUTE_SLOT.shipped).toBe(false);
    expect(ENTERPRISE_ROUTE_SLOT.path).toBe("enterprise");
  });

  it("主界面品牌位指向 `/chat`；工作台指向 `/workbench`（B-02/F-21）", () => {
    renderRail();

    expect(screen.getByTestId("rail-home")).toHaveAttribute("href", "/chat");
    expect(screen.getByTestId("rail-nav-workbench")).toHaveAttribute("href", "/workbench");
  });
});

describe("Rail · active 高亮（V0.4.5 B4·F-21/F-22.2）", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
    useUiStore.setState({ railModules: [...DEFAULT_OPTIONAL_KEYS] });
  });

  it("主界面 active（/chat）→ rail-home 命中路由 + 半透明背景（B-12 无常驻金底）", () => {
    renderRail("/chat");

    const home = screen.getByTestId("rail-home");
    expect(home).toHaveAttribute("aria-current", "page");
    expect(String(home.className)).toContain("bg-primary-foreground/20");
    // B-12：不再有常驻金底 `bg-accent`。
    expect(String(home.className)).not.toContain("bg-accent");
  });

  it("`/chat?c=` 前缀亦高亮 rail-home（F-21 end:false 兼容会话深链）", () => {
    renderRail("/chat?c=abc-123");

    expect(screen.getByTestId("rail-home")).toHaveAttribute("aria-current", "page");
  });

  it("固定项 active（/agents）→ 命中路由 + 渲染左侧金黄指示条", () => {
    renderRail("/agents");

    const agents = screen.getByTestId("rail-nav-agents");
    expect(agents).toHaveAttribute("aria-current", "page");
    expect(agents.querySelector("span[aria-hidden]")).not.toBeNull();
  });

  it("F-27.1a（B-09）：active 背景高亮为真实类名（非函数源码）", () => {
    renderRail("/agents");

    const agents = screen.getByTestId("rail-nav-agents");
    expect(typeof agents.className).toBe("string");
    expect(String(agents.className)).not.toContain("isActive");
    expect(String(agents.className)).toContain("bg-primary-foreground/20");
    expect(String(agents.className)).toContain("text-accent");
  });

  it("非 active（/tasks）→ rail-nav-agents 未命中路由，无指示条", () => {
    renderRail("/tasks");

    const agents = screen.getByTestId("rail-nav-agents");
    expect(agents).not.toHaveAttribute("aria-current");
    expect(agents.querySelector("span[aria-hidden]")).toBeNull();
    expect(String(agents.className)).not.toContain("bg-primary-foreground/20");
  });

  it("B-02 / B-09：`/workbench` 下工作台项高亮、主界面不误高亮", () => {
    renderRail("/workbench");

    const workbench = screen.getByTestId("rail-nav-workbench");
    const home = screen.getByTestId("rail-home");

    expect(workbench).toHaveAttribute("aria-current", "page");
    expect(String(workbench.className)).toContain("bg-primary-foreground/20");
    expect(workbench.querySelector("span[aria-hidden]")).not.toBeNull();

    expect(home).not.toHaveAttribute("aria-current");
    expect(String(home.className)).not.toContain("bg-primary-foreground/20");
    expect(String(home.className)).not.toContain("bg-accent");
    expect(home.querySelector("span[aria-hidden]")).toBeNull();
  });

  it("/chat 下 rail-nav-agents 非 active（前缀匹配不误伤）", () => {
    renderRail("/chat");

    expect(screen.getByTestId("rail-nav-agents")).not.toHaveAttribute("aria-current");
  });

  it("/studio/workflows 下 studio 项不误高亮（end:true，子路由不点亮父项）", () => {
    useUiStore.setState({ railModules: ["workflows", "studio"] });
    renderRail("/studio/workflows");

    expect(screen.getByTestId("rail-nav-workflows")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("rail-nav-studio")).not.toHaveAttribute("aria-current");
  });
});

describe("Rail · 导航文案 i18n（V0.4.5 B3·F-12）", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
    useUiStore.setState({ railModules: [...DEFAULT_OPTIONAL_KEYS] });
  });

  it("默认英文：主界面入口 aria-label=Home", () => {
    renderRail();

    expect(screen.getByTestId("rail-home")).toHaveAttribute("aria-label", "Home");
  });

  it("切换 zh-CN：主界面入口 aria-label=主界面", () => {
    useI18nStore.setState({ language: "zh-CN" });
    renderRail();

    expect(screen.getByTestId("rail-home")).toHaveAttribute("aria-label", "主界面");
  });

  it("可选模块文案走 i18n（作业中心 / Workflow 编排）", () => {
    useI18nStore.setState({ language: "zh-CN" });
    renderRail();

    expect(screen.getByTestId("rail-nav-tasks")).toHaveAttribute("aria-label", "任务中心");
    expect(screen.getByTestId("rail-nav-workflows")).toHaveAttribute("aria-label", "Workflow 编排");
  });

  it("导航容器 aria-label 走 i18n（原硬编码「一级导航」已收口为 rail.primaryNav）", () => {
    renderRail();
    expect(screen.getByTestId("rail-nav")).toHaveAttribute("aria-label", "Primary navigation");

    act(() => {
      useI18nStore.setState({ language: "zh-CN" });
    });
    expect(screen.getByTestId("rail-nav")).toHaveAttribute("aria-label", "一级导航");
  });

  it("审批中心上栏后文案走 i18n（默认不上栏，勾选后渲染）", () => {
    useUiStore.setState({ railModules: ["tasks", "approvals", "workflows"] });
    renderRail();

    expect(screen.getByTestId("rail-nav-approvals")).toHaveAttribute("aria-label", "Approvals");

    act(() => {
      useI18nStore.setState({ language: "zh-CN" });
    });
    expect(screen.getByTestId("rail-nav-approvals")).toHaveAttribute("aria-label", "审批中心");
  });
});

describe("Rail · 提醒铃弹层（B-27；W10 / T2-49 接真实待办 + D-10 文案 i18n 化）", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "zh-CN" });
    useUiStore.setState({ unreadCount: 0, railModules: [...DEFAULT_OPTIONAL_KEYS] });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("待办为空 → 无红点；点击铃铛弹出固定宽高空态弹窗", async () => {
    renderRail();

    // 真实待办为 0 → `unreadCount` 同步为 0 → 无红点。
    await waitFor(() => expect(screen.queryByTestId("rail-bell-badge")).toBeNull());

    fireEvent.click(screen.getByTestId("rail-bell"));

    const dialog = await screen.findByTestId("rail-notifications");
    expect(dialog).toBeInTheDocument();
    expect(await screen.findByTestId("rail-notifications-empty")).toHaveTextContent("暂无待办审批");
    // 弹窗（不是窄气泡）：声明固定宽高。
    expect(dialog.className).toContain("w-[440px]");
    expect(dialog.className).toContain("h-[360px]");
    // 可关闭：底部「关闭」按钮（Esc / 遮罩 / 右上 X 由 radix Dialog 提供）。
    expect(screen.getByTestId("rail-notifications-close")).toHaveTextContent("关闭");
  });

  it("2 条待办 → 红点显示 + 弹层列出条目 + 点击跳转 /approvals", async () => {
    server.use(http.get("/api/v1/approvals", () => shell([...BELL_APPROVALS])));

    renderRailWithRoutes();

    // 真实待办 2 条 → 同步进 `uiStore.unreadCount` → 红点出现。
    expect(await screen.findByTestId("rail-bell-badge")).toBeInTheDocument();
    expect(useUiStore.getState().unreadCount).toBe(2);

    fireEvent.click(screen.getByTestId("rail-bell"));

    const list = await screen.findByTestId("rail-notifications-list");
    expect(list).toHaveTextContent("工作流节点");
    expect(list).toHaveTextContent("u-requester");
    expect(list).toHaveTextContent("工具调用");
    expect(screen.queryByTestId("rail-notifications-empty")).toBeNull();

    fireEvent.click(screen.getByTestId("rail-notification-ap2"));

    expect(await screen.findByTestId("approvals-route-sentinel")).toBeInTheDocument();
  });

  it("文案走 i18n：切英文后铃铛 aria-label / 标题 / 空态均为英文", async () => {
    useI18nStore.setState({ language: "en" });
    renderRail();

    await waitFor(() =>
      expect(screen.getByTestId("rail-bell")).toHaveAttribute("aria-label", "Notifications"),
    );

    fireEvent.click(screen.getByTestId("rail-bell"));

    expect(await screen.findByTestId("rail-notifications-empty")).toHaveTextContent(
      "No pending approvals",
    );
    expect(screen.getByTestId("rail-notifications-close")).toHaveTextContent("Close");
  });
});
