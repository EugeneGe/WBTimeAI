import { create } from "zustand";

/**
 * UI Zustand store（**纯客户端状态**：外观 / 侧栏 / 右侧栏 / 预览标签 / 轻提示，D6 + D-UI WS-F）。
 *
 * ⚠️ **禁止**在此存放服务数据（服务真相源一律走 TanStack Query）。
 *
 * D-UI 体验优化波 · WS-F 冻结字段：
 * - `appearance: "light" | "dark" | "system"`（`theme` 为其解析结果；`system` 经 `matchMedia` 折算）；
 * - `sidebarOpen` 持久化；`rightPanelOpen` 新增并持久化；
 * - 右栏预览通道 `previewTabs / activePreviewId`（多标签，供 WS-L/WS-C 消费）。
 *
 * V0.4.6 B-25 追加：`railModules`（左侧栏已启用的可选模块，持久化键
 * `wbtime-ai.rail-modules`）+ `toggleRailModule` / `setRailModules`。
 */

type Theme = "light" | "dark";

/** 外观偏好（浅色默认；`system` 跟随系统）。 */
export type Appearance = "light" | "dark" | "system";

/** 轻提示消息。 */
export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "destructive";
}

/** 右栏预览标签页。 */
export interface PreviewTab {
  id: string;
  title: string;
  kind: "log" | "file" | "artifact";
  content: string;
}

/** 页面搜索配置（V0.4.4 Bug5：Topbar 内联搜索，由各页面 opt-in 并消费 query）。 */
export interface PageSearchConfig {
  /** 当前页面是否启用搜索（启用 → Topbar 显示内联输入框与入口按钮）。 */
  enabled: boolean;
  /** 输入框占位文案（由启用页声明，如「搜索会话与消息…」）。 */
  placeholder: string;
  /** 搜索关键词（页面消费以过滤当前页数据）。 */
  query: string;
}

/** 右栏宽度边界（V0.4.4 Bug5 拖宽：clamp 240–600）。 */
export const RIGHT_PANEL_WIDTH_MIN = 240;
export const RIGHT_PANEL_WIDTH_MAX = 600;
export const RIGHT_PANEL_WIDTH_DEFAULT = 300;

/**
 * 侧栏宽度边界（V0.4.5 B1·F-04 左栏拖宽：clamp 200–420，默认 212）。
 *
 * **冻结契约 C2**：常量名 / 默认值(212) / 边界(200–420) / 持久化键
 * `wbtime-ai.sidebar-width` 由 WS-A 独占，语义不得更改。
 */
export const SIDEBAR_WIDTH_MIN = 200;
export const SIDEBAR_WIDTH_MAX = 420;
export const SIDEBAR_WIDTH_DEFAULT = 212;

/** 持久化键（`wbtime-ai.theme` 沿用既有键名，行为兼容）。 */
const THEME_KEY = "wbtime-ai.theme";
const SIDEBAR_KEY = "wbtime-ai.sidebar-open";
const RIGHT_PANEL_KEY = "wbtime-ai.right-panel-open";
const RIGHT_PANEL_WIDTH_KEY = "wbtime-ai.right-panel-width";
/** 侧栏宽度持久化键（V0.4.5 B1·F-04；冻结契约 C2）。 */
const SIDEBAR_WIDTH_KEY = "wbtime-ai.sidebar-width";
/** 左侧栏可选模块持久化键（V0.4.6 · B-25：JSON 数组字符串）。 */
const RAIL_MODULES_KEY = "wbtime-ai.rail-modules";

/**
 * 左侧栏**可选模块 key 全量注册表**（V0.4.6 · B-25；顺序即渲染顺序，勿改）。
 *
 * 🔴 **不得**从 `@/components/layout/Rail` 引入：`Rail` → `uiStore` 已存在单向依赖，
 *    反向引入会形成循环依赖（Rail 顶层常量在 store 初始化时尚未就绪 → `undefined`）。
 *    故此处**独立维护一份 key 列表**，`Rail` 侧按自身 `OPTIONAL_RAIL_ITEMS` 过滤渲染。
 *
 * ⚠️ **顺序契约**：本数组顺序必须与 `Rail.OPTIONAL_RAIL_ITEMS` **完全一致**——
 *    {@link normalizeRailModules} 按此序过滤，落盘 / 回读后的排序均以它为准。
 */
export const OPTIONAL_RAIL_KEYS = [
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
] as const;

/** 可选模块 key 类型。 */
export type OptionalRailKey = (typeof OPTIONAL_RAIL_KEYS)[number];

/**
 * 默认可选模块（首次访问无持久化值时生效）：
 * 任务中心 + Workflow 编排（其余社区版模块由用户在工作台勾选上栏）。
 *
 * ⚠️ 后加的可选模块（如 `approvals`）**只进 {@link OPTIONAL_RAIL_KEYS}、不进本默认值**——
 *    保证既有用户首屏布局零变化，新模块需由用户在工作台图钉显式上栏。
 */
export const DEFAULT_RAIL_MODULES: readonly OptionalRailKey[] = ["tasks", "workflows"];

/** 判定是否为已注册的可选模块 key。 */
function isOptionalRailKey(value: unknown): value is OptionalRailKey {
  return typeof value === "string" && (OPTIONAL_RAIL_KEYS as readonly string[]).includes(value);
}

/**
 * 将任意 key 数组规整为「已注册 key、按注册表顺序、去重」的列表。
 *
 * 未知 key 直接丢弃；空数组是**合法值**（= 用户把所有可选模块都关掉）。
 */
function normalizeRailModules(keys: readonly string[]): string[] {
  return OPTIONAL_RAIL_KEYS.filter((key) => keys.includes(key));
}

/**
 * 读取持久化的左侧栏可选模块。
 *
 * - 键不存在 → {@link DEFAULT_RAIL_MODULES}；
 * - 非法 JSON / 非数组 → 回落默认值；
 * - 含未知 key → 过滤为已注册 key（数组仍按注册表顺序）；
 * - `[]`（空数组）→ **合法值**，原样返回（用户全关）。
 *
 * ⚠️ **未知 key 一律过滤**（不视为「非法值」）：故全为未知 key 的数组
 * （如 `["foo"]`）会被过滤成 `[]`——语义等同「用户把所有可选模块都关掉」，
 * **不会**回落默认；只有「非法 JSON / 非数组」才回落默认。
 */
function readRailModules(): string[] {
  const stored = safeGet(RAIL_MODULES_KEY);
  if (stored === null) {
    return [...DEFAULT_RAIL_MODULES];
  }
  try {
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) {
      return [...DEFAULT_RAIL_MODULES];
    }
    return normalizeRailModules(parsed.filter(isOptionalRailKey));
  } catch {
    return [...DEFAULT_RAIL_MODULES];
  }
}

/** 安全读 localStorage。 */
function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** 安全写 localStorage（忽略存储异常）。 */
function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // 忽略存储异常。
  }
}

/** 读取持久化外观（缺省 = 浅色；兼容旧值 `dark`）。 */
function readAppearance(): Appearance {
  const stored = safeGet(THEME_KEY);
  return stored === "dark" || stored === "system" ? stored : "light";
}

/** 读取持久化布尔（缺省用 fallback）。 */
function readBool(key: string, fallback: boolean): boolean {
  const stored = safeGet(key);
  return stored === null ? fallback : stored === "true";
}

/** 读取持久化右栏宽度（非法 / 越界 → 缺省；读取即 clamp）。 */
function readRightPanelWidth(): number {
  const stored = safeGet(RIGHT_PANEL_WIDTH_KEY);
  const parsed = stored === null ? Number.NaN : Number(stored);
  if (!Number.isFinite(parsed)) {
    return RIGHT_PANEL_WIDTH_DEFAULT;
  }
  return Math.min(RIGHT_PANEL_WIDTH_MAX, Math.max(RIGHT_PANEL_WIDTH_MIN, parsed));
}

/** 读取持久化侧栏宽度（非法 / 越界 → 缺省；读取即 clamp；V0.4.5 B1·F-04）。 */
function readSidebarWidth(): number {
  const stored = safeGet(SIDEBAR_WIDTH_KEY);
  const parsed = stored === null ? Number.NaN : Number(stored);
  if (!Number.isFinite(parsed)) {
    return SIDEBAR_WIDTH_DEFAULT;
  }
  return Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, parsed));
}

/** 系统是否偏好深色（环境不支持时视为浅色）。 */
function systemPrefersDark(): boolean {
  try {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

/** 将由外观解析出的实际主题折算为 light/dark。 */
function resolveTheme(appearance: Appearance): Theme {
  if (appearance === "system") {
    return systemPrefersDark() ? "dark" : "light";
  }
  return appearance;
}

/** 将实际主题同步到 `<html>` class（`darkMode: "class"`）。 */
function applyThemeClass(theme: Theme): void {
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }
}

/** UI store 状态与动作。 */
export interface UiState {
  theme: Theme;
  appearance: Appearance;
  sidebarOpen: boolean;
  rightPanelOpen: boolean;
  /** 右栏宽度（px；clamp 240–600；localStorage 持久化；V0.4.4 Bug5 拖宽）。 */
  rightPanelWidth: number;
  /** 侧栏宽度（px；clamp 200–420；localStorage 持久化；V0.4.5 B1·F-04 左栏拖宽）。 */
  sidebarWidth: number;
  /** 页面搜索配置（V0.4.4 Bug5；默认禁用，由页面 opt-in）。 */
  pageSearch: PageSearchConfig;
  /** 提醒未读数（V0.4.4 Bug8 驱动 Rail 铃铛红点；默认 0 = 无红点）。 */
  unreadCount: number;
  /**
   * 左侧栏**已启用的可选模块** key 列表（V0.4.6 · B-25）。
   *
   * 不含固定项（home / agents / knowledge / workbench）；空数组 = 仅固定 4 项。
   * 持久化于 `wbtime-ai.rail-modules`（JSON 数组字符串）。
   */
  railModules: string[];
  /** 切换某可选模块是否上栏（`key` 必须是已注册的可选模块）。 */
  toggleRailModule: (key: string) => void;
  /** 批量设置可选模块上栏列表（未知 key 丢弃，按注册表顺序归一）。 */
  setRailModules: (keys: string[]) => void;
  /** 字体大小（px；V0.4.5 B5·F-26 本波仅存档，不落盘；三档 14/16/18）。 */
  fontSize: number;
  setFontSize: (size: number) => void;
  toast: ToastMessage | null;
  previewTabs: PreviewTab[];
  activePreviewId: string | null;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setAppearance: (appearance: Appearance) => void;
  toggleSidebar: () => void;
  /** 设置右侧栏开合（缺省 = 打开）。 */
  openRightPanel: (open?: boolean) => void;
  toggleRightPanel: () => void;
  /** 设置右栏宽度（px；入参 clamp 240–600 并持久化；V0.4.4 Bug5）。 */
  setRightPanelWidth: (width: number) => void;
  /** 设置侧栏宽度（px；入参 clamp 200–420 并持久化；V0.4.5 B1·F-04）。 */
  setSidebarWidth: (width: number) => void;
  /** 页面搜索配置补丁更新（V0.4.4 Bug5）。 */
  setPageSearch: (patch: Partial<PageSearchConfig>) => void;
  /** 设置提醒未读数（V0.4.4 Bug8）。 */
  setUnreadCount: (count: number) => void;
  showToast: (toast: Omit<ToastMessage, "id"> & { id?: string }) => void;
  dismissToast: () => void;
  /** 打开/更新预览标签（已存在同 id 则更新内容并激活）。 */
  openPreviewTab: (tab: PreviewTab) => void;
  /** 关闭预览标签（关闭当前活动标签时自动激活相邻或置 null）。 */
  closePreviewTab: (id: string) => void;
  setActivePreviewId: (id: string | null) => void;
}

const initialAppearance = readAppearance();

export const useUiStore = create<UiState>((set, get) => ({
  theme: resolveTheme(initialAppearance),
  appearance: initialAppearance,
  sidebarOpen: readBool(SIDEBAR_KEY, true),
  rightPanelOpen: readBool(RIGHT_PANEL_KEY, false),
  rightPanelWidth: readRightPanelWidth(),
  sidebarWidth: readSidebarWidth(),
  pageSearch: { enabled: false, placeholder: "", query: "" },
  unreadCount: 0,
  railModules: readRailModules(),
  toggleRailModule: (key) => {
    // 未注册 key（含固定项）不参与开关：静默忽略，避免脏数据落盘。
    if (!isOptionalRailKey(key)) {
      return;
    }
    const current = get().railModules;
    const next = normalizeRailModules(
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
    safeSet(RAIL_MODULES_KEY, JSON.stringify(next));
    set({ railModules: next });
  },
  setRailModules: (keys) => {
    const next = normalizeRailModules(keys);
    safeSet(RAIL_MODULES_KEY, JSON.stringify(next));
    set({ railModules: next });
  },
  fontSize: 16,
  setFontSize: (size) => set({ fontSize: Math.min(18, Math.max(14, Math.round(size))) }),
  toast: null,
  previewTabs: [],
  activePreviewId: null,
  setTheme: (theme) => {
    safeSet(THEME_KEY, theme);
    applyThemeClass(theme);
    set({ theme, appearance: theme });
  },
  toggleTheme: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    get().setTheme(next);
  },
  setAppearance: (appearance) => {
    const theme = resolveTheme(appearance);
    safeSet(THEME_KEY, appearance);
    applyThemeClass(theme);
    set({ appearance, theme });
  },
  toggleSidebar: () => {
    const next = !get().sidebarOpen;
    safeSet(SIDEBAR_KEY, String(next));
    set({ sidebarOpen: next });
  },
  openRightPanel: (open = true) => {
    safeSet(RIGHT_PANEL_KEY, String(open));
    set({ rightPanelOpen: open });
  },
  toggleRightPanel: () => {
    get().openRightPanel(!get().rightPanelOpen);
  },
  setRightPanelWidth: (width) => {
    const next = Math.min(RIGHT_PANEL_WIDTH_MAX, Math.max(RIGHT_PANEL_WIDTH_MIN, width));
    safeSet(RIGHT_PANEL_WIDTH_KEY, String(next));
    set({ rightPanelWidth: next });
  },
  setSidebarWidth: (width) => {
    const next = Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, width));
    safeSet(SIDEBAR_WIDTH_KEY, String(next));
    set({ sidebarWidth: next });
  },
  setPageSearch: (patch) => set((state) => ({ pageSearch: { ...state.pageSearch, ...patch } })),
  setUnreadCount: (count) => set({ unreadCount: Math.max(0, Math.floor(count)) }),
  showToast: (toast) =>
    set({
      toast: {
        id: toast.id ?? String(Date.now()),
        title: toast.title,
        description: toast.description,
        variant: toast.variant ?? "default",
      },
    }),
  dismissToast: () => set({ toast: null }),
  openPreviewTab: (tab) =>
    set((state) => {
      const exists = state.previewTabs.some((item) => item.id === tab.id);
      return {
        previewTabs: exists
          ? state.previewTabs.map((item) => (item.id === tab.id ? tab : item))
          : [...state.previewTabs, tab],
        activePreviewId: tab.id,
      };
    }),
  closePreviewTab: (id) =>
    set((state) => {
      const index = state.previewTabs.findIndex((item) => item.id === id);
      if (index === -1) {
        return {};
      }
      const nextTabs = state.previewTabs.filter((item) => item.id !== id);
      if (state.activePreviewId !== id) {
        return { previewTabs: nextTabs };
      }
      // 关闭的是当前活动标签 → 激活右邻（同索引）或左邻，均无则置 null。
      const neighbor = nextTabs[index] ?? nextTabs[index - 1] ?? null;
      return { previewTabs: nextTabs, activePreviewId: neighbor ? neighbor.id : null };
    }),
  setActivePreviewId: (id) => set({ activePreviewId: id }),
}));

/** `system` 外观下监听系统主题变化并即时折算。 */
function bindSystemThemeListener(): void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return;
  }
  try {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (): void => {
      if (useUiStore.getState().appearance !== "system") {
        return;
      }
      const theme: Theme = query.matches ? "dark" : "light";
      applyThemeClass(theme);
      useUiStore.setState({ theme });
    };
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", handleChange);
    } else if (typeof query.addListener === "function") {
      query.addListener(handleChange);
    }
  } catch {
    // 忽略环境不支持。
  }
}

bindSystemThemeListener();
