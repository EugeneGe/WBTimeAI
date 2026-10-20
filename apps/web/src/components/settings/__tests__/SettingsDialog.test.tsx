// ---------------------------------------------------------------------------
// WBTimeAI · SettingsDialog 单测（V0.4.5 B3 · T03，F-11 + F-13；V0.4.5 B4 · T04 增补）
//
// 覆盖：
//   ① 分区导航 = **7 区固定顺序**（个人→通用→外观→模型→系统→关于→帮助，F-11.1）；
//   ② 遮罩改用语义色 `bg-foreground/40`（替代 `bg-black/60`，F-11.2 / §8.3）；
//   ③ 外观分区 **卡片式**（3 真实主题 + 占位卡），切换写 `uiStore.appearance`（F-11.4）；
//   ④ 个人分区（默认置首）：显示名回显 + **用量占位** + **无**「前往管理中心」（F-11.5）；
//   ⑤ 系统分区含合规明示 `SANDBOX_STRENGTH_NOTE`（A-1 迁移落点）；
//   ⑥ UserMenu（F-13）：**移除**「剩余用量」/外观三选项，保留「外观」单项入口；
//   ⑦ UserMenu 深链：外观 → 设置·外观分区；帮助 → 设置·帮助分区。
//
// V0.4.5 B4 · T04 增补：
//   ⑧ **F-17.2**（通用分区）：`closeAction` 关闭行为项（`settings-close-action`）——
//      桌面壳内渲染、默认「直接退出」；**桌面不可用时优雅降级**（不渲染）；
//   ⑨ **F-18.3**（系统分区）：后端端口可设（`settings-port-input` / `settings-port-save` /
//      `settings-port-hint`）——非法提示、合法经 `settings:set` 保存。
//
// ⚠️ F-19.2（T02）后「未登录头像不再渲染下拉、改为打开登录弹窗」——UserMenu 深链用例
//    须**先置已登录态**（`useAuthStore.setState({ isAuthenticated: true })`）再操作头像菜单。
//
// - 只读数据源（`useSystemSettings` / `usePersonalSettings` / `useProviders` /
//   `useCredentials`）以 `vi.mock` 打桩，避免网络；
// - 浮层为 `ui/dialog` / `ui/dropdown-menu`（radix）→ 补最小 jsdom 桩
//   （对齐 `Composer.test.tsx` 范式）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UserMenu } from "@/components/layout/UserMenu";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import type { SettingsSection } from "@/components/settings/SettingsDialog";
import { en } from "@/i18n/locales/en";
import { SANDBOX_STRENGTH_NOTE } from "@/lib/chat";
import { useAuthStore } from "@/stores/authStore";
import { useUiStore } from "@/stores/uiStore";

// --- jsdom 补丁：radix（dialog / dropdown-menu / floating-ui）所需最小实现 ---
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

// --- 只读设置数据源打桩（避免真实网络请求） ---
vi.mock("@/hooks/useSettings", () => ({
  useSystemSettings: () => ({
    data: { mode: "community", app_name: "WBTimeAI", app_version: "0.4.5" },
    isLoading: false,
  }),
  usePersonalSettings: () => ({
    data: {
      user_id: "u1",
      username: "alice",
      email: "alice@example.com",
      display_name: "Alice",
    },
    isLoading: false,
  }),
  useUpdatePersonalSettings: () => ({ mutate: vi.fn(), isPending: false }),
  // V0.4.6 缺陷 L-3：系统分区新增「组织」只读卡 → 需一并打桩（空列表 → 空态文案）。
  useOrganizations: () => ({ data: [], isPending: false, isError: false, error: null }),
  useOrganization: () => ({ data: undefined, isPending: false, isError: false, error: null }),
}));

// --- 模型数据源打桩（B-07：设置·模型分区改为页内添加 + 分组列表） ---
// 批 F · F2：补 `isError` / `refetch`（providers 500 → 「加载失败」+ 重试用例）。
const modelsSpy = vi.hoisted(() => ({
  providers: [] as Array<{
    id: string;
    name: string;
    type?: string;
    config?: Record<string, unknown>;
  }>,
  models: {} as Record<
    string,
    Array<{
      id: string;
      name: string;
      type?: string;
      status?: string;
      context_window?: number | null;
    }>
  >,
  credentials: [] as Array<{
    id: string;
    provider?: string;
    key_type?: string;
    masked_value?: string;
  }>,
  providersFailed: false,
  credentialsFailed: false,
  providersRefetch: vi.fn(),
  credentialsRefetch: vi.fn(),
  registerProvider: vi.fn(),
  registerModel: vi.fn(),
  saveCredential: vi.fn(),
  bindCredential: vi.fn(),
}));

vi.mock("@/hooks/useModels", () => ({
  useProviders: () => ({
    data: modelsSpy.providers,
    isLoading: false,
    isError: modelsSpy.providersFailed,
    refetch: modelsSpy.providersRefetch,
  }),
  useCredentials: () => ({
    data: modelsSpy.credentials,
    isLoading: false,
    isError: modelsSpy.credentialsFailed,
    refetch: modelsSpy.credentialsRefetch,
  }),
  useProviderModelsMany: (providerIds: readonly string[]) =>
    providerIds.map((providerId) => ({
      data: modelsSpy.models[providerId] ?? [],
      isLoading: false,
      refetch: vi.fn(),
    })),
  useRegisterProvider: () => ({ mutateAsync: modelsSpy.registerProvider, isPending: false }),
  useRegisterModel: () => ({ mutateAsync: modelsSpy.registerModel, isPending: false }),
  useSaveCredential: () => ({ mutateAsync: modelsSpy.saveCredential, isPending: false }),
  useBindCredential: () => ({ mutateAsync: modelsSpy.bindCredential, isPending: false }),
}));

// --- 写入口打桩（M07-02 #4：个人分区改走 `PUT /users/me` → `authService.updateMe`） ---
// 仅替换 `updateMe`，其余方法保留原实现（UserMenu 等复用路径不受影响）；
// 不打桩则就地编辑用例会发起真实请求（jsdom 下无网络）。
vi.mock("@/services/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/auth")>();
  return {
    ...actual,
    authService: {
      ...actual.authService,
      updateMe: vi.fn().mockResolvedValue({
        id: "u1",
        username: "alice",
        email: "alice@example.com",
        display_name: "Alice2",
      }),
    },
  };
});

/** 8 分区固定顺序（F-11.1 + B5·F-26 增「快捷键」，插在外观之后）。 */
const SECTION_ORDER: readonly SettingsSection[] = [
  "profile",
  "general",
  "appearance",
  "shortcuts",
  "models",
  "system",
  "about",
  "help",
];

// --- 桌面壳桩（F-17.2 / F-18.3：`window.wbtimeAiDesktop`，仅测试里注入） ---
interface FakeShell {
  /** 收到的 `setSettings` 补丁（按调用顺序）。 */
  setCalls: Array<Record<string, unknown>>;
}

/** 安装伪桌面壳（`getSettings` / `setSettings`），模拟桌面内环境。 */
function installFakeShell(): FakeShell {
  const setCalls: Array<Record<string, unknown>> = [];
  const state = {
    rendererMode: "bundled",
    apiBaseUrl: "",
    autoSpawnBackend: true,
    port: 21212,
    dataDir: "",
    language: "en",
    closeAction: "quit",
  };
  (window as unknown as { wbtimeAiDesktop?: unknown }).wbtimeAiDesktop = {
    getSettings: async (): Promise<Record<string, unknown>> => ({ ...state }),
    setSettings: async (patch: Record<string, unknown>): Promise<Record<string, unknown>> => {
      setCalls.push(patch);
      return { ...state, ...patch };
    },
  };
  return { setCalls };
}

/** 移除伪桌面壳（回到纯 Web 环境）。 */
function removeFakeShell(): void {
  (window as unknown as { wbtimeAiDesktop?: unknown }).wbtimeAiDesktop = undefined;
}

/** 渲染受 QueryClient + Router 上下文的子树（含路由探针，供落点断言）。 */
function renderWithProviders(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LocationProbe />
        {node}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** 路由探针：把当前 `pathname + search` 渲染到 `data-testid="location-probe"`。 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

/** 打开 radix DropdownMenu（触发器响应 pointerdown）。 */
function openDropdown(trigger: HTMLElement): void {
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
}

/** 查找设置弹窗遮罩（radix 渲染为 `div`，语义色类 `bg-foreground/40`）。 */
function findOverlay(): HTMLElement | null {
  return (
    Array.from(document.querySelectorAll<HTMLElement>("div[class]")).find((element) =>
      element.className.split(/\s+/).includes("bg-foreground/40"),
    ) ?? null
  );
}

describe("SettingsDialog", () => {
  beforeEach(() => {
    window.localStorage.clear();
    removeFakeShell();
    // 复位外观，避免用例间相互污染。
    useUiStore.setState({ appearance: "light", theme: "light" });
    // 复位认证态（F-19.2 后 UserMenu 依认证态分流；默认匿名）。
    useAuthStore.setState({ isAuthenticated: false, user: null });
    // 复位模型概览数据（D-UI5 跳转卡计数）+ 批 F · F2 失败态 / 重试 spy。
    modelsSpy.providers = [];
    modelsSpy.models = {};
    modelsSpy.credentials = [];
    modelsSpy.providersFailed = false;
    modelsSpy.credentialsFailed = false;
    modelsSpy.providersRefetch.mockClear();
    modelsSpy.credentialsRefetch.mockClear();
  });

  afterEach(() => {
    removeFakeShell();
  });

  it("分区导航为 8 区固定顺序（个人→通用→外观→快捷键→模型→系统→关于→帮助）", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    const nav = screen.getByTestId("settings-dialog-nav");
    const renderedKeys = Array.from(
      nav.querySelectorAll<HTMLElement>('[data-testid^="settings-dialog-nav-"]'),
    ).map((element) => element.getAttribute("data-testid"));

    expect(renderedKeys).toEqual(SECTION_ORDER.map((key) => `settings-dialog-nav-${key}`));
    expect(screen.getByTestId("settings-dialog-content")).toBeInTheDocument();
  });

  it("遮罩改用语义色 bg-foreground/40（替代 bg-black/60）", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    const overlay = findOverlay();
    expect(overlay).not.toBeNull();
    expect(overlay?.className).toContain("bg-foreground/40");
    expect(overlay?.className).not.toContain("bg-black/60");
  });

  it("「外观」分区为卡片式：3 真实主题 + 占位卡；切换深色 → 写 uiStore.appearance", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-appearance"));

    for (const theme of ["light", "dark", "system"]) {
      expect(screen.getByTestId(`settings-appearance-card-${theme}`)).toBeInTheDocument();
    }
    // 其余主题位为占位卡「敬请期待」。
    expect(screen.getByTestId("settings-appearance-card-coming-soon-0")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("settings-appearance-card-dark"));
    expect(useUiStore.getState().appearance).toBe("dark");
  });

  it("默认分区为「个人」：用户名回显 + 用量占位 + 无「前往管理中心」", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    expect(screen.getByTestId("settings-profile")).toBeInTheDocument();
    // F-26（B5）：显示名 Input/保存按钮删除 → 用户名行展示 + hover 铅笔就地编辑。
    expect(screen.getByTestId("settings-profile-name")).toHaveTextContent("Alice");
    expect(screen.queryByTestId("settings-display-name")).toBeNull();
    expect(screen.queryByTestId("settings-display-name-save")).toBeNull();
    expect(screen.getByTestId("settings-profile-name-edit")).toBeInTheDocument();
    // F-26：退出登录按钮存在。
    expect(screen.getByTestId("settings-profile-logout")).toBeInTheDocument();

    // 用量占位（Q5=A：前端占位 `—`）。
    const usage = screen.getByTestId("settings-profile-usage");
    expect(within(usage).getAllByText("—").length).toBeGreaterThan(0);

    // 精简方向：无「前往管理中心」。
    expect(screen.queryByText(/管理中心/)).toBeNull();
  });

  it("F-26：快捷键分区 → 搜索 / 恢复默认（禁用）/ 只读表格", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-shortcuts"));

    expect(screen.getByTestId("settings-shortcuts")).toBeInTheDocument();
    expect(screen.getByTestId("settings-shortcuts-search")).toBeInTheDocument();
    expect(screen.getByTestId("settings-shortcuts-reset")).toBeDisabled();
    expect(screen.getByTestId("settings-shortcuts-row-new-chat")).toBeInTheDocument();
    expect(screen.getByTestId("settings-shortcuts-row-quit")).toBeInTheDocument();
    expect(screen.getByTestId("settings-shortcuts-delete-new-chat")).toBeDisabled();
  });

  it("F-26：个人分区就地编辑 → Enter 提交 display_name", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-profile-name-edit"));
    const input = screen.getByTestId("settings-profile-name-input");
    fireEvent.change(input, { target: { value: "Alice2" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(screen.queryByTestId("settings-profile-name-input")).toBeNull();
  });

  it("「系统」分区含合规明示文案（SANDBOX_STRENGTH_NOTE，A-1 迁移落点）", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-system"));

    expect(screen.getByTestId("settings-sandbox-note")).toHaveTextContent(SANDBOX_STRENGTH_NOTE);
    expect(screen.getByTestId("settings-system-info")).toHaveTextContent("WBTimeAI");
  });

  it("UserMenu「设置」项 → 打开设置弹窗（缺省「个人」分区，弹窗形态非路由跳转）", () => {
    // F-19.2（T02）：未登录头像改为打开登录弹窗 → 深链用例须先登录。
    useAuthStore.setState({ isAuthenticated: true });
    renderWithProviders(<UserMenu />);

    expect(screen.queryByTestId("settings-dialog")).not.toBeInTheDocument();

    openDropdown(screen.getByTestId("user-menu-trigger"));
    fireEvent.click(screen.getByTestId("user-menu-settings"));

    expect(screen.getByTestId("settings-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("settings-profile")).toBeInTheDocument();
  });

  it("F-13 精简：移除「剩余用量」与外观三选项，保留「外观」单项入口", () => {
    useAuthStore.setState({ isAuthenticated: true });
    renderWithProviders(<UserMenu />);

    openDropdown(screen.getByTestId("user-menu-trigger"));

    expect(screen.queryByTestId("user-menu-usage")).toBeNull();
    expect(screen.queryByTestId("user-menu-appearance-light")).toBeNull();
    expect(screen.queryByTestId("user-menu-appearance-dark")).toBeNull();
    expect(screen.queryByTestId("user-menu-appearance-system")).toBeNull();
    expect(screen.getByTestId("user-menu-appearance")).toBeInTheDocument();
  });

  it("F-13 深链：外观入口 → 打开设置弹窗并跳「外观」分区", () => {
    useAuthStore.setState({ isAuthenticated: true });
    renderWithProviders(<UserMenu />);

    openDropdown(screen.getByTestId("user-menu-trigger"));
    fireEvent.click(screen.getByTestId("user-menu-appearance"));

    expect(screen.getByTestId("settings-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("settings-appearance")).toBeInTheDocument();
  });

  it("F-13 深链：帮助入口 → 打开设置弹窗并跳「帮助」分区", () => {
    useAuthStore.setState({ isAuthenticated: true });
    renderWithProviders(<UserMenu />);

    openDropdown(screen.getByTestId("user-menu-trigger"));
    fireEvent.click(screen.getByTestId("user-menu-help"));

    expect(screen.getByTestId("settings-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("settings-help")).toBeInTheDocument();
  });

  // -- B-07：模型分区改为「页内添加 + 按类型分组折叠」（用户实测裁定）--

  it("B-07：模型分区 = 概览三格 + 添加按钮 + 常用/自定义分组列表（不再跳转）", () => {
    useAuthStore.setState({ isAuthenticated: true });
    modelsSpy.providers = [
      { id: "p1", name: "OpenAI", type: "openai", config: { model_kind: "common" } },
      { id: "p2", name: "自建端点", type: "openai_compatible", config: { model_kind: "custom" } },
    ];
    modelsSpy.models = {
      p1: [{ id: "m1", name: "gpt-4o", type: "CHAT", context_window: 128000 }],
      p2: [{ id: "m2", name: "my-llm", type: "CHAT" }],
    };
    modelsSpy.credentials = [
      { id: "c1", provider: "OpenAI", key_type: "api_key", masked_value: "sk-…abcd" },
    ];
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-models"));
    expect(screen.getByTestId("settings-models")).toBeInTheDocument();

    // ① 概览三格仍在。
    const defaultModel = screen.getByTestId("settings-models-default-model");
    expect(defaultModel).toHaveTextContent("—");
    expect(defaultModel).toHaveTextContent(en["settings.models.jump.notConnected"]);
    expect(screen.getByTestId("settings-models-provider-count")).toHaveTextContent("2");
    expect(screen.getByTestId("settings-models-credential-count")).toHaveTextContent("1");
    // B-09：旧 /models 页下线，凭证掩码列表并入本分区。
    expect(screen.getByTestId("settings-models-credential-c1")).toHaveTextContent("sk-…abcd");

    // ② 页内添加按钮（不再有跳转按钮）。
    expect(screen.getByTestId("settings-models-add")).toBeEnabled();
    expect(screen.queryByTestId("settings-models-jump")).toBeNull();

    // ③ 分组：常用模型 / 自定义模型，各自模型就地展示。
    expect(screen.getByTestId("settings-models-group-common")).toHaveTextContent(
      en["settings.models.group.common"],
    );
    expect(screen.getByTestId("settings-models-group-custom")).toHaveTextContent(
      en["settings.models.group.custom"],
    );
    expect(screen.getByTestId("settings-models-item-m1")).toHaveTextContent("gpt-4o");
    expect(screen.getByTestId("settings-models-item-m2")).toHaveTextContent("my-llm");
  });

  it("B-07：分组可折叠（点组头收起该组模型）", () => {
    modelsSpy.providers = [
      { id: "p1", name: "OpenAI", type: "openai", config: { model_kind: "common" } },
    ];
    modelsSpy.models = { p1: [{ id: "m1", name: "gpt-4o", type: "CHAT" }] };
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-models"));
    const toggle = screen.getByTestId("settings-models-group-common-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("settings-models-item-m1")).toBeInTheDocument();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("settings-models-item-m1")).toBeNull();
  });

  it("B-07：匿名用户 → 添加按钮禁用（登录后管理模型）", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-models"));
    expect(screen.getByTestId("settings-models-add")).toBeDisabled();
  });

  it("B-07：无提供方 → 空态提示 + 两个分组均为空", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-models"));
    expect(screen.getByTestId("settings-models-empty")).toHaveTextContent(
      en["settings.models.jump.empty"],
    );
    expect(screen.getByTestId("settings-models-group-common-empty")).toHaveTextContent(
      en["settings.models.group.empty"],
    );
    expect(screen.getByTestId("settings-models-group-custom-empty")).toHaveTextContent(
      en["settings.models.group.empty"],
    );
  });

  it("批F·F2：providers 请求失败 → 「加载失败」+ 重试按钮，不渲染 0/0/0 概览与空态文案；点重试 → 两个 refetch 均触发", () => {
    // providers 查询出错（如 500）：`data ?? []` 不得再伪装成「尚未配置提供方」。
    modelsSpy.providersFailed = true;
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-models"));

    // ① 「加载失败」提示 + ghost 重试按钮出现。
    expect(screen.getByTestId("settings-models-load-failed")).toHaveTextContent(
      en["settings.models.jump.loadFailed"],
    );
    expect(screen.getByTestId("settings-models-retry")).toHaveTextContent(
      en["settings.models.jump.retry"],
    );

    // ② 概览三格不再渲染（尤其 provider-count 不得显示误导性的 0）。
    expect(screen.queryByTestId("settings-models-default-model")).toBeNull();
    expect(screen.queryByTestId("settings-models-provider-count")).toBeNull();
    expect(screen.queryByTestId("settings-models-credential-count")).toBeNull();

    // ③ 空态文案（「尚未配置提供方」）不出现——失败 ≠ 未配置。
    expect(screen.queryByTestId("settings-models-empty")).toBeNull();

    // ④ 点重试 → providers 与 credentials 两个 refetch 均被再次触发。
    expect(modelsSpy.providersRefetch).not.toHaveBeenCalled();
    expect(modelsSpy.credentialsRefetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("settings-models-retry"));
    expect(modelsSpy.providersRefetch).toHaveBeenCalledTimes(1);
    expect(modelsSpy.credentialsRefetch).toHaveBeenCalledTimes(1);
  });

  it("B-07：点击「添加模型配置」→ 就地打开弹窗，路由不变", () => {
    useAuthStore.setState({ isAuthenticated: true });
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-models"));
    expect(screen.getByTestId("location-probe")).toHaveTextContent(/^\/$/);

    fireEvent.click(screen.getByTestId("settings-models-add"));

    expect(screen.getByTestId("add-model-config-dialog")).toBeInTheDocument();
    // 弹窗就地打开：设置弹窗仍在，路由保持 `/`（不再跳 `/models`）。
    expect(screen.getByTestId("settings-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("location-probe")).toHaveTextContent(/^\/$/);
  });

  // -- V0.4.5 B4 · T04 新增：F-17.2 / F-18.3 ---------------------------------

  it("F-17.2：桌面不可用 → 「关闭行为」项不渲染（优雅降级）；端口项已随 B5·F-26 移除", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-general"));
    expect(screen.queryByTestId("settings-close-action")).toBeNull();

    // V0.4.5 B5 · F-26：系统分区端口块已删除（settings-port-* 消失）。
    fireEvent.click(screen.getByTestId("settings-dialog-nav-system"));
    expect(screen.queryByTestId("settings-port-input")).toBeNull();
    expect(screen.queryByTestId("settings-port-save")).toBeNull();
  });

  it("F-17.2：桌面壳内 → 「关闭行为」项渲染，默认「直接退出」", async () => {
    installFakeShell();
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    fireEvent.click(screen.getByTestId("settings-dialog-nav-general"));
    const trigger = await screen.findByTestId("settings-close-action");
    expect(trigger).toHaveTextContent(en["settings.general.closeAction.quit"]);
  });

  it("B-06：弹窗主体高度固定 70vh，切换分区不抖动；内容列可滚动", () => {
    renderWithProviders(<SettingsDialog open onOpenChange={() => undefined} />);

    expect(screen.getByTestId("settings-dialog-body").className).toContain("h-[70vh]");
    expect(screen.getByTestId("settings-dialog-body").className).not.toContain("min-h-[24rem]");
    expect(screen.getByTestId("settings-dialog-nav").className).toContain("h-full");
    expect(screen.getByTestId("settings-dialog-content").className).toContain("overflow-y-auto");
  });
});
