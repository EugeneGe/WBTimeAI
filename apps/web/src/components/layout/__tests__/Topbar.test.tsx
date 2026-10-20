// ---------------------------------------------------------------------------
// WBTimeAI · Topbar 单测（V0.4.5 B3 · F-09；B-19c 面包屑退场）
//
// 覆盖 F-09 关键口径（裁决 §1 F-09 / §2.4 / §5.2 / §5.4）：
//   ① `/chat` 有会话显示**动态标题**（无静态「对话」文案）；
//   ② 会话标题 hover 显编辑按钮（`chat-title-edit`，默认隐藏于 DOM）→ 点击就地重命名
//      （`useRenameConversation`）；
//   ③ 无会话（无 `?c=`）不渲染标题 / 编辑按钮；
//   ④ 搜索默认隐藏、点击 `topbar-search-toggle` 展开 `topbar-search-input`。
//
// B-19c（V0.4.6）：非 `/chat` 路由面包屑整体退场（原 B-18 五例与既有面包屑断言随功能删除）。
//
// - `useConversations` / `useRenameConversation` 以 `vi.mock` 打桩（零网络）；
// - `pageSearch.enabled` 经 `uiStore.setState` 打开以驱动搜索区。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Topbar } from "@/components/layout/Topbar";
import { en } from "@/i18n/locales/en";
import { useI18nStore } from "@/stores/i18nStore";
import { useUiStore } from "@/stores/uiStore";

const renameMutate = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => ({
    data: [
      { id: "conv-1", title: "会话标题甲" },
      // 标题为空 → 校验回落 `id`。
      { id: "conv-2", title: "" },
    ],
    isLoading: false,
  }),
  useRenameConversation: () => ({ mutate: renameMutate, isPending: false }),
}));

/** 渲染 Topbar（Router 提供 `?c=` 查询上下文；返回 RTL 句柄供 unmount）。 */
function renderTopbar(initialEntry = "/chat") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Topbar />
    </MemoryRouter>,
  );
}

describe("Topbar · V0.4.5 B3 · F-09", () => {
  beforeEach(() => {
    renameMutate.mockClear();
    useI18nStore.setState({ language: "en" });
    // 启用页面搜索（Chat 页 opt-in 等价），驱动搜索图标 / 展开输入框。
    useUiStore.setState({
      pageSearch: { enabled: true, placeholder: "", query: "" },
      rightPanelOpen: false,
    });
  });

  afterEach(() => {
    useUiStore.setState({ pageSearch: { enabled: false, placeholder: "", query: "" } });
  });

  it("默认不展示「对话」：有会话时显动态标题 + hover 编辑按钮", () => {
    renderTopbar("/chat?c=conv-1");

    // 不再有静态「对话」文案。
    expect(screen.queryByText("对话")).toBeNull();
    // 动态会话标题承载于标题位。
    expect(screen.getByText("会话标题甲")).toBeInTheDocument();
    // 编辑按钮存在于 DOM（默认经 CSS 隐藏，hover/focus 显现）。
    expect(screen.getByTestId("chat-title-edit")).toBeInTheDocument();
  });

  it("会话无标题 → 回落 conversationId", () => {
    renderTopbar("/chat?c=conv-2");

    expect(screen.getByText("conv-2")).toBeInTheDocument();
  });

  it("无会话（无 ?c=）→ 不渲染标题 / 编辑按钮", () => {
    renderTopbar("/chat");

    expect(screen.queryByText("会话标题甲")).toBeNull();
    expect(screen.queryByText("conv-1")).toBeNull();
    expect(screen.queryByTestId("chat-title-edit")).toBeNull();
  });

  it("点击编辑 → 就地重命名 → Enter 提交调用 useRenameConversation", () => {
    renderTopbar("/chat?c=conv-1");

    fireEvent.click(screen.getByTestId("chat-title-edit"));
    const input = screen.getByTestId("chat-title-input");
    fireEvent.change(input, { target: { value: "追加 V0.4.5 测试问题" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(renameMutate).toHaveBeenCalledWith({ id: "conv-1", title: "追加 V0.4.5 测试问题" });
  });

  it("编辑态 Esc → 取消（不触发重命名）", () => {
    renderTopbar("/chat?c=conv-1");

    fireEvent.click(screen.getByTestId("chat-title-edit"));
    const input = screen.getByTestId("chat-title-input");
    fireEvent.change(input, { target: { value: "不应提交" } });
    fireEvent.keyDown(input, { key: "Escape" });

    expect(renameMutate).not.toHaveBeenCalled();
    // 回到标题展示态。
    expect(screen.getByText("会话标题甲")).toBeInTheDocument();
  });

  it("搜索默认隐藏（无输入框）；点击放大镜展开输入框（B-12：展开后隐藏切换按钮）", () => {
    renderTopbar("/chat");

    expect(screen.queryByTestId("topbar-search-input")).toBeNull();
    expect(screen.getByTestId("topbar-search-toggle")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("topbar-search-toggle"));

    expect(screen.getByTestId("topbar-search-input")).toBeInTheDocument();
    // 展开态：右侧放大镜按钮不再重复展示（输入框内已有放大镜）。
    expect(screen.queryByTestId("topbar-search-toggle")).toBeNull();
  });

  it("F-20.4：展开态为胶囊 + 上/下结果导航 + 关闭 × + 计数占位", () => {
    renderTopbar("/chat");

    fireEvent.click(screen.getByTestId("topbar-search-toggle"));

    // 展开态为**胶囊**（rounded-full）。
    expect(screen.getByTestId("topbar-search-bar").className).toContain("rounded-full");
    expect(screen.getByTestId("topbar-search-input")).toBeInTheDocument();
    expect(screen.getByTestId("topbar-search-prev")).toBeInTheDocument();
    expect(screen.getByTestId("topbar-search-next")).toBeInTheDocument();
    expect(screen.getByTestId("topbar-search-close")).toBeInTheDocument();
    // 计数占位（A-B4-3 骨架：总数占位 0 → 「无结果」）。
    expect(screen.getByTestId("topbar-search-count")).toHaveTextContent(
      en["topbar.search.noResults"],
    );
  });

  it("F-20.4：点击关闭 × → 收起搜索输入框（B-12：关闭后恢复放大镜按钮）", () => {
    renderTopbar("/chat");

    fireEvent.click(screen.getByTestId("topbar-search-toggle"));
    expect(screen.getByTestId("topbar-search-input")).toBeInTheDocument();
    expect(screen.queryByTestId("topbar-search-toggle")).toBeNull();

    fireEvent.click(screen.getByTestId("topbar-search-close"));
    expect(screen.queryByTestId("topbar-search-input")).toBeNull();
    expect(screen.getByTestId("topbar-search-toggle")).toBeInTheDocument();
  });

  it("F-20.4：上/下导航点击不报错（骨架）", () => {
    renderTopbar("/chat");

    fireEvent.click(screen.getByTestId("topbar-search-toggle"));
    fireEvent.click(screen.getByTestId("topbar-search-prev"));
    fireEvent.click(screen.getByTestId("topbar-search-next"));
    // 无结果（总数占位 0）→ 计数保持「无结果」。
    expect(screen.getByTestId("topbar-search-count")).toHaveTextContent(
      en["topbar.search.noResults"],
    );
  });
});

describe("Topbar · V0.4.5 B5 · F-30（内容区顶栏 / 开关回内容区 / 智能页整行自隐藏）", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
    useUiStore.setState({
      pageSearch: { enabled: false, placeholder: "", query: "" },
      rightPanelOpen: false,
    });
  });

  afterEach(() => {
    useUiStore.setState({ pageSearch: { enabled: false, placeholder: "", query: "" } });
  });

  it("F-30：品牌名与 AppMenuBar 已迁至 TitleMenuBar，Topbar 不再渲染", () => {
    renderTopbar("/chat");

    expect(screen.queryByText(en["app.name"])).toBeNull();
    expect(screen.queryByTestId("app-menu-bar")).toBeNull();
  });

  it("F-30：主界面侧栏开关在内容区左端首位（面包屑之前）", () => {
    renderTopbar("/chat");

    expect(screen.getByTestId("topbar-sidebar-toggle")).toBeInTheDocument();

    const header = screen.getByTestId("topbar");
    const children = Array.from(header.children);
    const sidebarToggleIndex = children.findIndex(
      (el) => el.getAttribute("data-testid") === "topbar-sidebar-toggle",
    );
    expect(sidebarToggleIndex).toBe(0);
  });

  it("右栏开关两态：rightPanelOpen=false 显示；true 时 Topbar 不渲染（搬家到 RightPanel）", () => {
    const { rerender } = render(
      <MemoryRouter initialEntries={["/chat"]}>
        <Topbar />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("topbar-right-panel-toggle")).toBeInTheDocument();

    useUiStore.setState({ rightPanelOpen: true });
    rerender(
      <MemoryRouter initialEntries={["/chat"]}>
        <Topbar />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("topbar-right-panel-toggle")).toBeNull();
  });

  it("F-27.1b / F-30：智能页 `/agents` 内容区顶栏整行不渲染", () => {
    renderTopbar("/agents");

    expect(screen.queryByTestId("topbar")).toBeNull();
    expect(screen.queryByTestId("topbar-sidebar-toggle")).toBeNull();
    expect(screen.queryByTestId("topbar-right-panel-toggle")).toBeNull();
  });

  it("F-27.1b / F-30：智能页 `/agents/xxx` 子路径同样整行不渲染", () => {
    renderTopbar("/agents/agent-1");

    expect(screen.queryByTestId("topbar")).toBeNull();
  });
});
