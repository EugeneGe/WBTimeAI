import { create } from "zustand";

/**
 * UI Zustand store（**纯客户端状态**：主题 / 侧栏 / 轻提示，D6）。
 *
 * ⚠️ **禁止**在此存放服务数据（服务真相源一律走 TanStack Query）。
 */

type Theme = "light" | "dark";

export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "destructive";
}

const THEME_KEY = "astra.theme";

function readTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    return stored === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** UI store 状态与动作。 */
export interface UiState {
  theme: Theme;
  sidebarOpen: boolean;
  toast: ToastMessage | null;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  showToast: (toast: Omit<ToastMessage, "id"> & { id?: string }) => void;
  dismissToast: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  theme: readTheme(),
  sidebarOpen: true,
  toast: null,
  setTheme: (theme) => {
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      // 忽略存储异常。
    }
    if (typeof document !== "undefined") {
      document.documentElement.classList.toggle("dark", theme === "dark");
    }
    set({ theme });
  },
  toggleTheme: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    get().setTheme(next);
  },
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
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
}));
