// ---------------------------------------------------------------------------
// WBTimeAI · AppLayout 单测（V0.4.5 B1·F-04 左侧拖动条；V0.4.5 B4·F-22.1 全局去侧栏）
//
// 覆盖：
//   ① 侧栏展开时渲染 `left-panel-resizer`（折叠时不渲染）；
//   ② mousedown → mousemove → `uiStore.sidebarWidth` 随之变化；
//   ③ 拖动越界 → clamp 200–420；
//   ④ mouseup 后监听解绑，后续 mousemove 不再改变宽度；
//   ⑤ F-22.1：**仅 `/chat`（前缀）** 渲染 `<Sidebar/>` 与左拖动条；其余路由隐藏（Rail 保留）。
//
// 说明：为避免依赖其它工作流在改的 `Rail`/`UserMenu`（F-05c），此处仅打桩
// `@/components/layout/Rail`；其余子件（Sidebar / Topbar / RightPanel）走真实实现，
// 其数据依赖一律以 `vi.mock` 打桩（`useMe()` 亦打桩，避免网络）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppLayout } from "@/components/layout/AppLayout";
import { useUiStore } from "@/stores/uiStore";

// --- jsdom 补丁：radix（toast / popover / tooltip）所需最小实现 ---
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

// 打桩 Rail（其内 UserMenu 属 WS-C 在改；本测试关注布局/拖动，不涉及其内容）。
vi.mock("@/components/layout/Rail", () => ({
  Rail: () => <div data-testid="rail-stub" />,
}));

vi.mock("@/hooks/useAuth", () => ({
  useMe: () => ({ data: null, isLoading: false }),
  useAuth: () => ({ logout: { mutate: vi.fn(), isPending: false } }),
}));

vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => ({ data: [], isLoading: false }),
  // F-09：Topbar 会话标题重命名（真实 Topbar 走此 hook）。
  useRenameConversation: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useProjects", () => ({
  useProjects: () => ({ data: [], isLoading: false }),
}));
vi.mock("@/hooks/useWorkspaces", () => ({
  useWorkspaces: () => ({ data: [], isLoading: false }),
  useCreateWorkspace: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({ data: [], isLoading: false }),
}));

/** 渲染 AppLayout（独立 QueryClient + 路由上下文）。默认落主界面 `/chat`（F-22.1 侧栏保留）。 */
function renderLayout(initialPath = "/chat") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AppLayout />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppLayout · 左栏拖动条（V0.4.5 B1·F-04）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({
      sidebarOpen: true,
      sidebarWidth: 212,
      rightPanelOpen: false,
      rightPanelWidth: 300,
    });
  });

  it("侧栏展开时渲染 left-panel-resizer", () => {
    renderLayout();

    expect(screen.getByTestId("left-panel-resizer")).toBeInTheDocument();
  });

  it("侧栏折叠时不渲染拖动条", () => {
    useUiStore.setState({ sidebarOpen: false });
    renderLayout();

    expect(screen.queryByTestId("left-panel-resizer")).toBeNull();
  });

  it("mousedown → 右拖 mousemove → sidebarWidth 增大", () => {
    renderLayout();
    const resizer = screen.getByTestId("left-panel-resizer");

    fireEvent.mouseDown(resizer, { clientX: 200 });
    fireEvent.mouseMove(window, { clientX: 300 });

    // 212 + (300 - 200) = 312。
    expect(useUiStore.getState().sidebarWidth).toBe(312);
    fireEvent.mouseUp(window);
  });

  it("拖动越界 → clamp 200–420", () => {
    renderLayout();
    const resizer = screen.getByTestId("left-panel-resizer");

    // 左拖 → 变窄 → clamp 200。
    fireEvent.mouseDown(resizer, { clientX: 500 });
    fireEvent.mouseMove(window, { clientX: 100 });
    expect(useUiStore.getState().sidebarWidth).toBe(200);
    fireEvent.mouseUp(window);

    // 右拖 → 变宽 → clamp 420。
    fireEvent.mouseDown(resizer, { clientX: 100 });
    fireEvent.mouseMove(window, { clientX: 900 });
    expect(useUiStore.getState().sidebarWidth).toBe(420);
    fireEvent.mouseUp(window);
  });

  it("mouseup 后监听解绑：后续 mousemove 不再改变宽度", () => {
    renderLayout();
    const resizer = screen.getByTestId("left-panel-resizer");

    fireEvent.mouseDown(resizer, { clientX: 200 });
    fireEvent.mouseMove(window, { clientX: 260 });
    expect(useUiStore.getState().sidebarWidth).toBe(272);
    fireEvent.mouseUp(window);

    fireEvent.mouseMove(window, { clientX: 400 });
    expect(useUiStore.getState().sidebarWidth).toBe(272);
  });
});

describe("AppLayout · 全局去侧栏（V0.4.5 B4·F-22.1）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({
      sidebarOpen: true,
      sidebarWidth: 212,
      rightPanelOpen: false,
      rightPanelWidth: 300,
    });
  });

  it("主界面 `/chat`：渲染 `<Sidebar/>` 与左拖动条", () => {
    renderLayout("/chat");

    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("left-panel-resizer")).toBeInTheDocument();
  });

  it("`/chat` 子路径（`/chat/xxx`）仍显示侧栏（前缀匹配）", () => {
    renderLayout("/chat/xxx");

    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("left-panel-resizer")).toBeInTheDocument();
  });

  it("非主界面（`/agents`）：隐藏 `<Sidebar/>` 与左拖动条，Rail 图标列保留", () => {
    renderLayout("/agents");

    expect(screen.queryByTestId("sidebar")).toBeNull();
    expect(screen.queryByTestId("left-panel-resizer")).toBeNull();
    expect(screen.getByTestId("rail-stub")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// V0.4.5 B5 · F-30：**顶栏两层化**
//
// 口径：外层 `flex-col` 的**第一行**是 `<TitleMenuBar/>`（窗口最顶：名称 + 菜单，
// 占据原系统标题栏位置）；**第二行** `flex` 行承载 Rail / Sidebar / 内容区 / 右栏；
// 内容区顶栏 `<Topbar/>` 回到**中间列内**（主内容之上），智能页整行自隐藏。
// ---------------------------------------------------------------------------
describe("AppLayout · 顶栏两层化（V0.4.5 B5·F-30）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({
      sidebarOpen: true,
      sidebarWidth: 212,
      rightPanelOpen: false,
      rightPanelWidth: 300,
    });
  });

  it("第一行为 TitleMenuBar（整宽名称 + 菜单），第二行承载 Rail / 侧栏 / 内容区", () => {
    renderLayout("/chat");

    const titleBar = screen.getByTestId("title-menu-bar");
    const root = titleBar.parentElement as HTMLElement;

    // 外层为纵向堆叠容器，标题菜单行是第一行。
    expect(root.className).toContain("flex-col");
    expect(root.firstElementChild).toBe(titleBar);

    // 第二行为横向 flex 行，承载 Rail / 侧栏 / 内容区 / 右栏。
    const row = root.children[1] as HTMLElement;
    expect(row.className).toContain("flex");
    expect(row.contains(screen.getByTestId("rail-stub"))).toBe(true);
    expect(row.contains(screen.getByTestId("sidebar"))).toBe(true);
    expect(row.contains(screen.getByTestId("app-main"))).toBe(true);
    // 内容区顶栏也在第二行内（不再占据窗口最顶整宽一行）。
    expect(row.contains(screen.getByTestId("topbar"))).toBe(true);
    expect(titleBar.contains(screen.getByTestId("topbar"))).toBe(false);
    expect(titleBar.contains(screen.getByTestId("app-main"))).toBe(false);
  });

  it("内容区顶栏与主内容同处中间列（顶栏在上、main 在下）", () => {
    renderLayout("/chat");

    const topbar = screen.getByTestId("topbar");
    const main = screen.getByTestId("app-main");
    const column = topbar.parentElement as HTMLElement;

    expect(column).toBe(main.parentElement);
    expect(column.className).toContain("flex-col");
    const order = Array.from(column.children);
    expect(order.indexOf(topbar)).toBeLessThan(order.indexOf(main));
  });

  it("右栏开启时仍在第二行内（标题菜单行下沿起算）", () => {
    useUiStore.setState({ rightPanelOpen: true });
    renderLayout("/chat");

    const titleBar = screen.getByTestId("title-menu-bar");
    const root = titleBar.parentElement as HTMLElement;
    const row = root.children[1] as HTMLElement;

    expect(row.contains(screen.getByTestId("right-panel"))).toBe(true);
    expect(titleBar.contains(screen.getByTestId("right-panel"))).toBe(false);
  });

  it("智能页 `/agents`：内容区顶栏整行不渲染（无空行），TitleMenuBar 仍在", () => {
    renderLayout("/agents");

    expect(screen.getByTestId("title-menu-bar")).toBeInTheDocument();
    expect(screen.queryByTestId("topbar")).toBeNull();
    // 内容直接开始：main 仍在第二行中间列。
    expect(screen.getByTestId("app-main")).toBeInTheDocument();
  });
});
