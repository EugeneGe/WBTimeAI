// ---------------------------------------------------------------------------
// WBTimeAI · Chat 单测（V0.4.5 B1 追加波 · WS-B / F-03；B3 · F-09 去重）
//
// 覆盖关键口径：
//   ① 删除项**均不存在**：会话 / 时间线 tab、会话范围 `chat-agent-select`（「请选择」）、
//      顶部沙箱强度 `sandbox-strength` banner、右侧「事件时间线」栏；
//   ② 聊天面板**满宽**：`chat-titlebar` 存在、`composer` **常驻**、无 tab 行；
//   ③ **F-09 去重**：`chat-titlebar` 仅保留容器（承载流式态 Badge），**不再渲染会话标题**
//      （标题迁至 `Topbar`，其形态见 `Topbar.test.tsx`）；
//   ④ 冻结契约 C1：`?c=<id>` **选中生效**（`chatStore.activeConversationId` 同步 +
//      以该 id 载入消息）；
//   ⑤ 批 F · F1：`?c=<id>` 指向**不存在会话**（msw 404）→ 用户可见提示 +
//      `?c=` 从 URL replace 掉 + 深链选中态清空（下一条消息不带脏 id 发送）。
//
// - 只读数据源（`useAgents` / `useConversationMessages` / `useChatStream` / `useModels`）
//   以 `vi.mock` 打桩，**零网络**（与 msw `onUnhandledRequest:"error"` 兼容）；
// - `Composer` 含 radix 浮层 → 补最小 jsdom 桩（对齐 Composer.test.tsx 范式）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { en } from "@/i18n/locales/en";
import { clearTokens } from "@/lib/token";
import { Chat } from "@/pages/Chat";
import { server } from "@/test/setup";
import { useAuthGateStore } from "@/stores/authGateStore";
import { useAuthStore } from "@/stores/authStore";
import { useChatStore } from "@/stores/chatStore";

// --- jsdom 补丁：radix（dropdown-menu / popover / floating-ui）所需最小实现 ---
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

// 记录 `useConversationMessages` 入参（证明 `?c=` 选中且以该 id 载入消息）；
// `history` 为**稳定引用**（对齐 TanStack Query 缓存语义，避免 effect 依赖抖动成环）。
// `useRealMessagesHook`（批 F · F1）：置 true 时直连**真实** hook（TanStack Query + axios →
// msw），供 404 深链失效用例覆盖服务端行为；其余用例维持零网络打桩形态。
const spy = vi.hoisted(() => ({
  messagesArgs: [] as Array<string | null>,
  history: [] as unknown[],
  useRealMessagesHook: false,
}));

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({
    data: [{ id: "a1", name: "软件架构师" }],
    isLoading: false,
  }),
}));

// `useConversations` 与 `useConversationMessages` 同属该模块 → 同一个 mock 一并导出。
vi.mock("@/hooks/useConversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useConversations")>();
  return {
    useConversations: () => ({
      data: [
        { id: "conv-1", title: "会话标题甲" },
        // 标题为空 → 校验回落 `id`（假定 A-3）。
        { id: "conv-2", title: "" },
      ],
      isLoading: false,
    }),
    useConversationMessages: (id: string | null) => {
      spy.messagesArgs.push(id);
      // 批 F · F1：直连真实实现（走 msw），由用例 `server.use` 决定 200 / 404。
      if (spy.useRealMessagesHook) {
        return actual.useConversationMessages(id);
      }
      return { data: spy.history, isLoading: false };
    },
  };
});

// `useChatStream` 的 `sendMessage` / `cancel` 以稳定 spy 暴露（F-19.3 门控断言「未发送」）。
const chatSpy = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  cancel: vi.fn(),
}));

vi.mock("@/hooks/useChatStream", () => ({
  useChatStream: () => ({
    streaming: false,
    error: null,
    sendMessage: chatSpy.sendMessage,
    cancel: chatSpy.cancel,
  }),
}));

vi.mock("@/hooks/useModels", () => ({
  // Composer 模型胶囊。
  useProviders: () => ({
    data: [{ id: "p1", name: "WB-Time 中" }],
    isLoading: false,
  }),
  // `Composer` 内置设置弹窗（B-08：配置自定义模型 → 设置·模型）→ 补齐其内部 hooks。
  useProviderModels: () => ({ data: [], isLoading: false }),
  useProviderModelsMany: () => [],
  useRegisterProvider: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRegisterModel: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useBindCredential: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveCredential: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
}));

// Composer 内的只读数据源（技能 / 连接器）打桩 → 保证「零网络」（含 F-19.3 已登录用例）。
vi.mock("@/hooks/useSkills", () => ({
  useSkills: () => ({ data: [], isLoading: false }),
}));
vi.mock("@/hooks/useMcp", () => ({
  useMcpServers: () => ({ data: [], isLoading: false }),
}));

/** 路由探针：把当前 `pathname + search` 渲染到 `data-testid="location-probe"`。 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

/** 渲染 Chat（独立 QueryClient，禁用重试；Router 提供 `?c=` 查询上下文）。 */
function renderChat(initialEntry = "/chat"): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <LocationProbe />
        <Chat />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Chat · V0.4.5 B1 · WS-B（F-03）+ B3 · F-09", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
    spy.messagesArgs.length = 0;
    spy.useRealMessagesHook = false;
    window.localStorage.clear();
    // F-19.3：每个用例复位认证态与门控（默认匿名）。
    clearTokens();
    useAuthStore.setState({ isAuthenticated: false, user: null });
    useAuthGateStore.setState({ open: false, pending: null });
    chatSpy.sendMessage.mockClear();
    chatSpy.cancel.mockClear();
  });

  it("删除项均不存在：会话 / 时间线 tab、Agent「请选择」下拉、沙箱 banner、事件时间线", () => {
    renderChat();

    expect(screen.queryByTestId("chat-toggle-sessions")).toBeNull();
    expect(screen.queryByTestId("chat-toggle-timeline")).toBeNull();
    expect(screen.queryByTestId("chat-agent-select")).toBeNull();
    expect(screen.queryByTestId("sandbox-strength")).toBeNull();
    expect(screen.queryByText("请选择")).toBeNull();
    expect(screen.queryByText("事件时间线")).toBeNull();
  });

  it("聊天面板满宽：标题栏存在、Composer 常驻、无 tab 行按钮", () => {
    renderChat();

    expect(screen.getByTestId("chat-titlebar")).toBeInTheDocument();
    expect(screen.getByTestId("composer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "会话" })).toBeNull();
    expect(screen.queryByRole("button", { name: "时间线" })).toBeNull();
  });

  it("F-09 去重：chat-titlebar 仅保留容器、不再渲染会话标题（标题迁至 Topbar）", () => {
    // 有会话（?c=conv-1）时，标题文本也应**不在** Chat 内（已迁 Topbar）。
    renderChat("/chat?c=conv-1");

    expect(screen.getByTestId("chat-titlebar").textContent?.trim()).toBe("");
    expect(screen.queryByText("会话标题甲")).toBeNull();
  });

  it("冻结契约 C1：?c=<id> 选中生效（activeConversationId 同步 + 以该 id 载入消息）", () => {
    renderChat("/chat?c=conv-1");

    expect(useChatStore.getState().activeConversationId).toBe("conv-1");
    expect(spy.messagesArgs).toContain("conv-1");
  });

  it("F-20.3：无消息 → 欢迎区 + 输入台同屏竖向居中", () => {
    renderChat();

    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    const composer = screen.getByTestId("composer");
    // 居中容器（items-center justify-center）为 Composer 的祖先。
    expect(composer.closest(".justify-center")).not.toBeNull();
  });

  it("F-20.3：有消息 → 消息列表 + 输入台置底（border-t 容器）", () => {
    useChatStore.setState({ messages: [{ id: "m1", role: "user" as const, content: "你好" }] });
    renderChat();

    expect(screen.queryByTestId("empty-state")).toBeNull();
    expect(screen.getByTestId("message-list")).toBeInTheDocument();
    const composer = screen.getByTestId("composer");
    expect(composer.closest(".border-t")).not.toBeNull();
  });

  it("F-19.3：未登录发送 → 打开登录弹窗、不发送", () => {
    renderChat();

    fireEvent.change(screen.getByTestId("composer-input"), { target: { value: "你好" } });
    fireEvent.click(screen.getByTestId("composer-send"));

    expect(useAuthGateStore.getState().open).toBe(true);
    expect(chatSpy.sendMessage).not.toHaveBeenCalled();
  });

  it("F-19.3：已登录发送 → 直接发送（不弹窗）", () => {
    useAuthStore.setState({ isAuthenticated: true });
    renderChat();

    fireEvent.change(screen.getByTestId("composer-input"), { target: { value: "你好" } });
    fireEvent.click(screen.getByTestId("composer-send"));

    expect(useAuthGateStore.getState().open).toBe(false);
    expect(chatSpy.sendMessage).toHaveBeenCalledWith("你好", null);
  });

  it("批F·F1：深链指向不存在会话（GET /conversations/:id/messages 404）→ 提示文案 + 清 ?c= + 下一条消息不带脏 id", async () => {
    // 本用例直连真实 `useConversationMessages`（TanStack Query + axios → msw）。
    spy.useRealMessagesHook = true;
    server.use(
      http.get("/api/v1/conversations/:conversationId/messages", () =>
        HttpResponse.json(
          { code: "NOT_FOUND", message: "conversation not found", data: {} },
          { status: 404 },
        ),
      ),
    );
    useAuthStore.setState({ isAuthenticated: true });
    renderChat("/chat?c=conv-404");

    // ① 用户可见提示出现（i18n 文案，欢迎态上方一行）。
    expect(await screen.findByTestId("chat-deeplink-missing")).toHaveTextContent(
      en["chat.deepLink.missing"],
    );

    // ② `?c=` 已从 URL replace 掉（location-probe 只剩 /chat）。
    await waitFor(() => {
      expect(screen.getByTestId("location-probe")).toHaveTextContent(/^\/chat$/);
    });

    // ③ 深链选中态已清（store 侧）→ 下一条消息不会带着脏 id 发送：
    //    发送走 `sendMessage(text, conversationId)`，本地 conversationId 已被错误分支置空。
    expect(useChatStore.getState().activeConversationId).toBeNull();
    fireEvent.change(screen.getByTestId("composer-input"), { target: { value: "你好" } });
    fireEvent.click(screen.getByTestId("composer-send"));
    expect(chatSpy.sendMessage).toHaveBeenCalledWith("你好", null);
  });
});
