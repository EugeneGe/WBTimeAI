// ---------------------------------------------------------------------------
// WBTimeAI · Sidebar 单测（V0.4.5 B1·F-02 头部搜索 / F-04 宽度联动）
//
// 覆盖：
//   ① 头部入口为「搜索」（`sidebar-search`），旧折叠按钮（`sidebar-collapse`）已移除；
//   ② 宽度接 `uiStore.sidebarWidth`（inline style 驱动，不再写死 `w-[212px]`）；
//   ③ 点击搜索 → 对话搜索弹层（`conv-search-input`）出现；
//   ④ 关键词按标题过滤；
//   ⑤ 点击会话项 → `navigate("/chat?c=<id>")`（冻结契约 C1）；
//   ⑥ V0.4.5 B3·F-10：「新聊天」入口**仅主界面（`/chat`）显示**，其它路由隐藏；
//   ⑦ B-01（V0.4.6）：分组标题 / 「新聊天」/ 筛选三态 / 空态文案走 i18n（zh-CN 断言不变，
//      另加英文口径用例）；B-02：「工作台」路径为 `/workbench`（原 `/`）。
//
// - 只读数据源（`useConversations` / `useProjects` / `useWorkspaces` / `useAgents`）
//   以 `vi.mock` 打桩，避免网络；
// - 浮层为 `ui/popover`（radix）→ 补最小 jsdom 桩（范式对齐 Composer.test.tsx）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/layout/Sidebar";
import { useI18nStore } from "@/stores/i18nStore";
import { useUiStore } from "@/stores/uiStore";

// --- jsdom 补丁：radix（popover / floating-ui）所需最小实现 ---
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe(): void {
      void 0;
    }
    unobserve(): void {
      void 0;
    }
    disconnect(): void {
      void 0;
    }
  } as unknown as typeof ResizeObserver;
}
if (typeof window.PointerEvent === "undefined") {
  window.PointerEvent = MouseEvent as unknown as typeof PointerEvent;
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = (): void => {
    void 0;
  };
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = (): boolean => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = (): void => {
    void 0;
  };
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = (): void => {
    void 0;
  };
}

vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => ({
    data: [
      { id: "c1", title: "Guide Book", agent_id: "a1" },
      { id: "c2", title: "数据分析报告", agent_id: "a2" },
      { id: "c3", title: "杂项记录", agent_id: "aX" },
    ],
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useProjects", () => ({
  useProjects: () => ({ data: [], isLoading: false }),
}));

vi.mock("@/hooks/useWorkspaces", () => ({
  useWorkspaces: () => ({ data: [{ id: "w1", name: "Demo" }], isLoading: false }),
  useCreateWorkspace: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({
    data: [
      { id: "a1", name: "软件架构师" },
      { id: "a2", name: "数据分析专家" },
    ],
    isLoading: false,
  }),
}));

/** 路由探针：渲染当前 `pathname + search`，供导航断言。 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

/** 渲染 Sidebar（独立 QueryClient + 路由上下文 + 路由探针）。 */
function renderSidebar(initialPath = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Sidebar />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Sidebar · F-02 头部搜索 / F-04 宽度", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({ sidebarOpen: true, sidebarWidth: 212 });
    // B-01：本组断言沿用既有中文口径 → 固定 zh-CN。
    useI18nStore.setState({ language: "zh-CN" });
  });

  it("头部为「搜索」入口，旧折叠按钮已移除", () => {
    renderSidebar();

    expect(screen.getByTestId("sidebar-search")).toBeInTheDocument();
    expect(screen.queryByTestId("sidebar-collapse")).toBeNull();
  });

  it("F-29：品牌名只在整宽顶栏渲染 → 侧栏内不再出现「观序智能平台」", () => {
    renderSidebar("/chat");

    expect(screen.queryByText("观序智能平台")).toBeNull();
    // 头部搜索入口仍在（移除品牌名后布局不塌陷）。
    expect(screen.getByTestId("sidebar-search")).toBeInTheDocument();
  });

  it("宽度接 uiStore.sidebarWidth（inline style 驱动）", () => {
    useUiStore.setState({ sidebarWidth: 300 });
    renderSidebar();

    expect(screen.getByTestId("sidebar")).toHaveStyle({ width: "300px" });
  });

  it("点击搜索 → 对话搜索弹层与输入框出现", () => {
    renderSidebar();

    expect(screen.queryByTestId("conv-search-input")).toBeNull();
    fireEvent.click(screen.getByTestId("sidebar-search"));
    expect(screen.getByTestId("conv-search-input")).toBeInTheDocument();
    expect(screen.getByTestId("conv-search-input")).toHaveAttribute("placeholder", "搜索对话");
  });

  it("关键词按标题过滤（其余会话消失）", () => {
    renderSidebar();
    fireEvent.click(screen.getByTestId("sidebar-search"));

    fireEvent.change(screen.getByTestId("conv-search-input"), { target: { value: "数据" } });

    expect(screen.getByTestId("conv-search-item-c2")).toBeInTheDocument();
    expect(screen.queryByTestId("conv-search-item-c1")).toBeNull();
    expect(screen.queryByTestId("conv-search-item-c3")).toBeNull();
  });

  it("点击会话标题 → navigate(`/chat?c=<id>`)（冻结契约 C1）", () => {
    renderSidebar();
    fireEvent.click(screen.getByTestId("sidebar-search"));

    fireEvent.click(screen.getByTestId("conv-search-item-c1"));

    expect(screen.getByTestId("location-probe")).toHaveTextContent("/chat?c=c1");
  });
});

describe("Sidebar · F-10「新聊天」入口按路由显隐（V0.4.5 B3）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({ sidebarOpen: true, sidebarWidth: 212 });
    // B-01：本组断言沿用既有中文口径 → 固定 zh-CN。
    useI18nStore.setState({ language: "zh-CN" });
  });

  it("主界面 `/chat`：显示「新聊天」并指向 /chat", () => {
    renderSidebar("/chat");

    const newChat = screen.getByTestId("sidebar-new-chat");
    expect(newChat).toHaveAttribute("href", "/chat");
    expect(newChat).toHaveTextContent("新聊天");
  });

  it("主界面带会话参数 `/chat?c=c1`：仍显示（按 pathname 判定）", () => {
    renderSidebar("/chat?c=c1");

    expect(screen.getByTestId("sidebar-new-chat")).toBeInTheDocument();
  });

  it("任务中心 `/tasks`：隐藏「新聊天」", () => {
    renderSidebar("/tasks");

    expect(screen.queryByTestId("sidebar-new-chat")).toBeNull();
  });

  it("知识库 `/studio/knowledge`：隐藏「新聊天」", () => {
    renderSidebar("/studio/knowledge");

    expect(screen.queryByTestId("sidebar-new-chat")).toBeNull();
  });

  it("工作台 `/workbench`（B-02：原 `/`）：隐藏「新聊天」", () => {
    renderSidebar("/workbench");

    expect(screen.queryByTestId("sidebar-new-chat")).toBeNull();
  });
});

describe("Sidebar · B-01 侧栏文案 i18n（V0.4.6）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({ sidebarOpen: true, sidebarWidth: 212 });
    useI18nStore.setState({ language: "en" });
  });

  it("英文界面：分组 / 新聊天 / 空态文案为英文", () => {
    renderSidebar("/chat");

    expect(screen.getByTestId("sidebar-new-chat")).toHaveTextContent("New chat");
    expect(screen.getByTestId("sidebar-projects")).toHaveTextContent("Projects");
    expect(screen.getByTestId("sidebar-projects")).toHaveTextContent("No projects yet");
    expect(screen.getByTestId("sidebar-recent")).toHaveTextContent("Recent");
    // 会话列表非空（mock 三条）→ 「最近」空态不应出现。
    expect(screen.getByTestId("sidebar-recent")).not.toHaveTextContent("No history yet");
  });

  it("切换 zh-CN：文案随之中文化", () => {
    useI18nStore.setState({ language: "zh-CN" });
    renderSidebar("/chat");

    expect(screen.getByTestId("sidebar-new-chat")).toHaveTextContent("新聊天");
    expect(screen.getByTestId("sidebar-projects")).toHaveTextContent("项目");
    expect(screen.getByTestId("sidebar-projects")).toHaveTextContent("暂无项目");
    expect(screen.getByTestId("sidebar-recent")).toHaveTextContent("最近");
  });
});
