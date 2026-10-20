// ---------------------------------------------------------------------------
// WBTimeAI · AppLayout 右栏拖动条 + Sidebar「新聊天」回归（V0.4.5 B1 · QA 独立补测）
//
// 补齐工程师既有用例未覆盖、但**本波明确要求**的两条边界：
//   ① F-04「右侧既有拖宽（240–600）仍在」：`right-panel-resizer` 在 `rightPanelOpen`
//      时渲染，mousedown→左拖 mousemove → `uiStore.rightPanelWidth` 增大，且 clamp 240–600；
//   ② F-02「侧栏原『新聊天』入口仍存在」：删除 Chat 内 aside 后，新建会话能力不得丢失
//      （`sidebar-new-chat` 链接指向 `/chat`）。
//
// ⚠️ V0.4.5 B3·F-10：因「新聊天」改为**仅主界面（/chat）显示**，本条回归改为在
//    `/chat` 路由下渲染断言（原 `/` 路由下入口已按 F-10 隐藏）。
// ⚠️ B-01（V0.4.6）：该入口文案走 i18n `sidebar.newChat`，断言前固定 zh-CN。
//
// 说明：本文件为 **QA 新增**（不改工程师既有测试断言语义）；打桩口径对齐
// `AppLayout.test.tsx`（仅打桩 Rail，其余子件走真实实现、数据依赖 vi.mock）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppLayout } from "@/components/layout/AppLayout";
import { useI18nStore } from "@/stores/i18nStore";
import { useUiStore } from "@/stores/uiStore";

// --- jsdom 补丁：radix（popover / tooltip / toast）所需最小实现 ---
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

// 打桩 Rail（其内 UserMenu 属 WS-C 改动域；本测试关注布局与拖动）。
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

/** 渲染 AppLayout（独立 QueryClient + 路由上下文）。 */
function renderLayout(initialPath = "/"): void {
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

describe("AppLayout · 右栏拖动条回归（V0.4.5 B1·F-04 QA 补测）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({
      sidebarOpen: true,
      sidebarWidth: 212,
      rightPanelOpen: true,
      rightPanelWidth: 300,
    });
  });

  it("既有右栏拖动条仍在：rightPanelOpen 时渲染 right-panel-resizer", () => {
    renderLayout();

    expect(screen.getByTestId("right-panel-resizer")).toBeInTheDocument();
    expect(screen.getByTestId("right-panel")).toBeInTheDocument();
  });

  it("右栏向左拖 → rightPanelWidth 增大", () => {
    renderLayout();
    const resizer = screen.getByTestId("right-panel-resizer");

    fireEvent.mouseDown(resizer, { clientX: 500 });
    fireEvent.mouseMove(window, { clientX: 400 });

    // 右栏在右侧：向左拖（clientX 减小）→ 变宽；300 + (500 - 400) = 400。
    expect(useUiStore.getState().rightPanelWidth).toBe(400);
    fireEvent.mouseUp(window);
  });

  it("右栏拖动越界 → clamp 240–600", () => {
    renderLayout();
    const resizer = screen.getByTestId("right-panel-resizer");

    // 向右拖 → 变窄 → clamp 240。
    fireEvent.mouseDown(resizer, { clientX: 100 });
    fireEvent.mouseMove(window, { clientX: 800 });
    expect(useUiStore.getState().rightPanelWidth).toBe(240);
    fireEvent.mouseUp(window);

    // 向左拖 → 变宽 → clamp 600。
    fireEvent.mouseDown(resizer, { clientX: 900 });
    fireEvent.mouseMove(window, { clientX: 100 });
    expect(useUiStore.getState().rightPanelWidth).toBe(600);
    fireEvent.mouseUp(window);
  });

  it("右栏关闭时不渲染 right-panel-resizer", () => {
    useUiStore.setState({ rightPanelOpen: false });
    renderLayout();

    expect(screen.queryByTestId("right-panel-resizer")).toBeNull();
  });
});

describe("Sidebar「新聊天」入口保留（V0.4.5 B1·F-02 QA 补测）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useUiStore.setState({ sidebarOpen: true, sidebarWidth: 212 });
    // B-01：「新聊天」文案已走 i18n `sidebar.newChat`；本用例沿用中文口径 → 固定 zh-CN。
    useI18nStore.setState({ language: "zh-CN" });
  });

  it("删除 Chat 内 aside 后，主界面 /chat 侧栏「新聊天」入口仍在且指向 /chat", () => {
    renderLayout("/chat");

    const newChat = screen.getByTestId("sidebar-new-chat");
    expect(newChat).toHaveAttribute("href", "/chat");
    expect(newChat).toHaveTextContent("新聊天");
  });
});
