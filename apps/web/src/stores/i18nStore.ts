import { create } from "zustand";

import type { DesktopSettingsPatch } from "@/types/desktop";

/**
 * 界面语言状态 store（V0.4.5 B3 · F-12；**纯客户端状态**，默认英文）。
 *
 * 设计裁定（`docs/施工方案/V0.4.5/03-…-设置与导航-2026-10-15.md` §2.2 / §4.2 / §8.2）：
 * - `Language = "en" | "zh-CN"`；默认 **`"en"`**（`DEFAULT_LANGUAGE`）；
 * - 持久化：`localStorage["wbtime-ai.language"]`（纯 Web 兜底）；
 * - 壳内权威：`settings.json.language`（经**既有** `settings:get`/`settings:set` IPC 读写，
 *   **不新增 IPC 通道**）；
 * - `<html lang>` 随语言同步（`en` / `zh-CN`）。
 *
 * 🔴 **依赖方向**：本 store **不** import `@/i18n`（避免与 `@/i18n` → 本 store 形成循环依赖）。
 *   `Language` 等语言基元在此定义，`@/i18n` 单向依赖本模块并对外**再导出**（满足 §4.2 公共面）。
 */

/** 界面语言（镜像桌面壳 `protocol.Language`）。 */
export type Language = "en" | "zh-CN";

/** 默认语言（冻结：英文）。 */
export const DEFAULT_LANGUAGE: Language = "en";

/** 支持的语言集合（冻结顺序：默认语言优先）。 */
export const SUPPORTED_LANGUAGES: readonly Language[] = ["en", "zh-CN"];

/** 语言持久化键（冻结，§8.2）。 */
export const LANGUAGE_STORAGE_KEY = "wbtime-ai.language";

/** 类型守卫：`value` 是否为受支持的 `Language`。 */
export function isLanguage(value: unknown): value is Language {
  return value === "en" || value === "zh-CN";
}

/** 安全读 localStorage（忽略存储异常）。 */
function safeGet(key: string): string | null {
  try {
    if (typeof window === "undefined") {
      return null;
    }
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** 安全写 localStorage（忽略存储异常）。 */
function safeSet(key: string, value: string): void {
  try {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(key, value);
  } catch {
    // 忽略存储异常。
  }
}

/**
 * 同步 `<html lang>`（冻结口径：`en` / `zh-CN`）。
 *
 * @param language 目标语言。
 */
export function applyDocumentLanguage(language: Language): void {
  if (typeof document !== "undefined") {
    document.documentElement.lang = language;
  }
}

/** 读取初始语言：localStorage 合法值 → 采用；否则回落默认 `en`。 */
function readInitialLanguage(): Language {
  const stored = safeGet(LANGUAGE_STORAGE_KEY);
  return isLanguage(stored) ? stored : DEFAULT_LANGUAGE;
}

/** 从壳设置对象中提取 `language`（非法 / 缺失 → `null`）。 */
function languageFromSettings(settings: unknown): Language | null {
  if (settings !== null && typeof settings === "object" && "language" in settings) {
    const value = (settings as { language?: unknown }).language;
    if (isLanguage(value)) {
      return value;
    }
  }
  return null;
}

/** i18n store 状态与动作。 */
export interface I18nState {
  /** 当前界面语言（默认 `"en"`）。 */
  language: Language;
  /**
   * 设置语言：持久化 `localStorage`；同步 `<html lang>`；壳内镜像 `settings.json.language`。
   *
   * @param language 目标语言（非法值回落默认 `en`）。
   */
  setLanguage: (language: Language) => void;
  /** 启动时从壳 `settings:get` 载入（存在且合法 → 覆盖本地；无壳 / 失败 → 保留本地兜底）。 */
  hydrateFromShell: () => Promise<void>;
}

const initialLanguage = readInitialLanguage();

export const useI18nStore = create<I18nState>((set, get) => ({
  language: initialLanguage,
  setLanguage: (language) => {
    const next: Language = isLanguage(language) ? language : DEFAULT_LANGUAGE;
    // ① 纯 Web 兜底持久化。
    safeSet(LANGUAGE_STORAGE_KEY, next);
    // ② DOM `<html lang>` 立即同步。
    applyDocumentLanguage(next);
    // ③ 更新状态（订阅 `t()` / `useTranslation()` 的组件即时重渲染）。
    set({ language: next });
    // ④ 壳桥接：写 `settings.json.language`（复用既有 `settings:set`，不新增通道）。
    //    壳不存在（纯 Web）→ 跳过；写入失败（主进程白名单校验 / IPC 异常）→ 不阻塞 UI。
    const api = typeof window !== "undefined" ? window.wbtimeAiDesktop : undefined;
    if (api !== undefined) {
      void api
        .setSettings({ language: next } as unknown as DesktopSettingsPatch)
        .catch(() => undefined);
    }
  },
  hydrateFromShell: async () => {
    const api = typeof window !== "undefined" ? window.wbtimeAiDesktop : undefined;
    if (api === undefined) {
      return;
    }
    try {
      const settings: unknown = await api.getSettings();
      const shellLanguage = languageFromSettings(settings);
      if (shellLanguage !== null && shellLanguage !== get().language) {
        // 壳 `settings.json.language` 为权威：覆盖本地值并同步 DOM（**不回写壳**，避免循环）。
        safeSet(LANGUAGE_STORAGE_KEY, shellLanguage);
        applyDocumentLanguage(shellLanguage);
        set({ language: shellLanguage });
      }
    } catch {
      // 壳不可用 / IPC 失败 → 保留 localStorage 兜底值。
    }
  },
}));

// 模块加载即同步一次 `<html lang>`（首屏语言与初始状态一致）。
applyDocumentLanguage(useI18nStore.getState().language);
