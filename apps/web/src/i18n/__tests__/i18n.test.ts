// ---------------------------------------------------------------------------
// WBTimeAI · i18n 核心 + i18nStore 单测（V0.4.5 B3 · F-12）
//
// 覆盖（对齐任务 T01 验收）：
//   ① 默认语言 = `en`；en 资源可翻译；支持语言集合冻结；
//   ② 插值 `{name}`（未提供参数 → 占位保留）；
//   ③ 缺键回退：目标语言缺 → `en`；`en` 亦缺 → **key 原文**；
//   ④ 切换：`setLanguage` 更新 store + 同步 `<html lang>` + localStorage 持久化；
//   ⑤ 持久化：新模块实例读取 localStorage（合法采用 / 非法回落默认）；
//   ⑥ `useTranslation()` 随语言切换即时重渲染；`t()` 使用当前 store 语言；
//   ⑦ 壳桥接：`hydrateFromShell` 以 `settings.language` 为权威；`setLanguage` 经 `settings:set` 镜像；
//   ⑧ key 对等：`en` 与 `zh-CN` key 集合一致（契约守卫）。
// ---------------------------------------------------------------------------
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  isLanguage,
  registerLanguage,
  t,
  translate,
  useTranslation,
} from "@/i18n";
import { en } from "@/i18n/locales/en";
import { zhCN } from "@/i18n/locales/zh-CN";
import { LANGUAGE_STORAGE_KEY, applyDocumentLanguage, useI18nStore } from "@/stores/i18nStore";

/** 最小壳桥接桩：仅覆盖 `getSettings` / `setSettings`（镜像既有 `settings:*` IPC）。 */
interface FakeShell {
  /** 收到的 `setSettings` 补丁（按调用顺序）。 */
  setCalls: Array<Record<string, unknown>>;
}

/**
 * 安装伪 `window.wbtimeAiDesktop`。
 *
 * @param language 壳设置中初始 `language`（缺省 = 不含该字段）。
 */
function installFakeShell(language?: string): FakeShell {
  const setCalls: Array<Record<string, unknown>> = [];
  const shellState: Record<string, unknown> = {
    rendererMode: "bundled",
    apiBaseUrl: "",
    autoSpawnBackend: true,
    port: 8080,
    dataDir: "",
  };
  if (language !== undefined) {
    shellState.language = language;
  }
  (window as unknown as { wbtimeAiDesktop?: unknown }).wbtimeAiDesktop = {
    getSettings: async (): Promise<Record<string, unknown>> => ({ ...shellState }),
    setSettings: async (patch: Record<string, unknown>): Promise<Record<string, unknown>> => {
      setCalls.push(patch);
      return { ...shellState, ...patch };
    },
  };
  return { setCalls };
}

/** 移除伪壳（回到纯 Web 环境）。 */
function removeFakeShell(): void {
  (window as unknown as { wbtimeAiDesktop?: unknown }).wbtimeAiDesktop = undefined;
}

beforeEach(() => {
  window.localStorage.clear();
  removeFakeShell();
  // 恢复原始资源字典（防「缺键回退」用例对全局注册表的改动外溢）。
  registerLanguage("en", en);
  registerLanguage("zh-CN", zhCN);
  useI18nStore.setState({ language: DEFAULT_LANGUAGE });
  applyDocumentLanguage(DEFAULT_LANGUAGE);
});

afterEach(() => {
  removeFakeShell();
});

describe("i18n 核心 · 契约", () => {
  it("默认语言为英文，支持语言集合冻结", () => {
    expect(DEFAULT_LANGUAGE).toBe("en");
    expect(SUPPORTED_LANGUAGES).toEqual(["en", "zh-CN"]);
    expect(isLanguage("en")).toBe(true);
    expect(isLanguage("zh-CN")).toBe(true);
    expect(isLanguage("fr")).toBe(false);
    expect(isLanguage(undefined)).toBe(false);
    expect(useI18nStore.getState().language).toBe("en");
  });

  it("translate：按语言返回对应资源", () => {
    expect(translate("en", "nav.home")).toBe(en["nav.home"]);
    expect(translate("zh-CN", "nav.home")).toBe(zhCN["nav.home"]);
  });

  it("插值：{name} 占位替换（未提供参数 → 占位保留）", () => {
    expect(translate("en", "common.greeting", { name: "Alex" })).toBe("Hello, Alex");
    expect(translate("zh-CN", "common.greeting", { name: "阿豆" })).toBe("你好，阿豆");
    expect(translate("en", "common.greeting")).toBe("Hello, {name}");
  });

  it("缺键回退：目标语言缺 → en；两者皆缺 → key 原文", () => {
    // 注册一份「仅含一个键」的 zh-CN 字典，制造 nav.home 缺失。
    registerLanguage("zh-CN", { "only.zh": "仅中文" });
    expect(translate("zh-CN", "only.zh")).toBe("仅中文");
    // zh-CN 缺 nav.home → 回退 en。
    expect(translate("zh-CN", "nav.home")).toBe(en["nav.home"]);
    // en 亦缺 → 返回 key 原文。
    expect(translate("zh-CN", "totally.missing.key")).toBe("totally.missing.key");
    expect(translate("en", "totally.missing.key")).toBe("totally.missing.key");
  });

  it("key 对等：en 与 zh-CN key 集合一致（契约守卫）", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(zhCN).sort());
  });

  it("B-01：品牌名随语言（en = WBTimeAI / zh-CN = 观序智能平台）", () => {
    expect(en["app.name"]).toBe("WBTimeAI");
    expect(zhCN["app.name"]).toBe("观序智能平台");
    // 含品牌名的文案同语言内自洽（不再跨语言混用中文品牌）。
    expect(translate("en", "menu.app.about")).toContain("WBTimeAI");
    expect(translate("en", "menu.file.quit")).toContain("WBTimeAI");
    expect(translate("en", "auth.login.title")).toContain("WBTimeAI");
    expect(translate("en", "auth.register.title")).toContain("WBTimeAI");
    expect(translate("zh-CN", "menu.app.about")).toContain("观序智能平台");
    expect(translate("zh-CN", "auth.login.title")).toContain("观序智能平台");
    // 英文资源内不应再残留中文品牌（防回退）。
    for (const value of Object.values(en)) {
      expect(value).not.toContain("观序智能平台");
    }
  });

  it("B-01：欢迎态 / 侧栏新增 key 双语齐备", () => {
    for (const key of [
      "chat.greeting.title",
      "chat.greeting.description",
      "chat.greeting.chip.1",
      "chat.greeting.chip.2",
      "chat.greeting.chip.3",
      "sidebar.filter.all",
      "sidebar.filter.chats",
      "sidebar.projects",
      "sidebar.projects.empty",
      "sidebar.newChat",
      "sidebar.recent",
      "sidebar.recent.empty",
    ]) {
      expect(en[key], `en 缺 ${key}`).toBeTruthy();
      expect(zhCN[key], `zh-CN 缺 ${key}`).toBeTruthy();
    }
    // `{app}` 插值：品牌随语言。
    expect(translate("en", "chat.greeting.title", { app: en["app.name"] })).toBe(
      "Hi, I'm the WBTimeAI assistant",
    );
    expect(translate("zh-CN", "chat.greeting.title", { app: zhCN["app.name"] })).toBe(
      "你好，我是 观序智能平台 助理",
    );
  });
});

describe("i18nStore · 切换 / DOM lang / 持久化", () => {
  it("setLanguage：更新 store + 同步 <html lang> + localStorage 持久化", () => {
    act(() => {
      useI18nStore.getState().setLanguage("zh-CN");
    });
    expect(useI18nStore.getState().language).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("zh-CN");

    act(() => {
      useI18nStore.getState().setLanguage("en");
    });
    expect(useI18nStore.getState().language).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
  });

  it("useTranslation：随语言切换即时重渲染", () => {
    const { result } = renderHook(() => useTranslation());
    expect(result.current.language).toBe("en");
    expect(result.current.t("nav.home")).toBe(en["nav.home"]);

    act(() => {
      useI18nStore.getState().setLanguage("zh-CN");
    });
    expect(result.current.language).toBe("zh-CN");
    expect(result.current.t("nav.home")).toBe(zhCN["nav.home"]);
  });

  it("t()：使用当前 store 语言", () => {
    expect(t("nav.home")).toBe(en["nav.home"]);
    act(() => {
      useI18nStore.getState().setLanguage("zh-CN");
    });
    expect(t("nav.home")).toBe(zhCN["nav.home"]);
  });

  it("持久化：新模块实例读取 localStorage 合法值", async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "zh-CN");
    vi.resetModules();
    const fresh = await import("@/stores/i18nStore");
    expect(fresh.useI18nStore.getState().language).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("持久化：非法值回落默认 en", async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    vi.resetModules();
    const fresh = await import("@/stores/i18nStore");
    expect(fresh.useI18nStore.getState().language).toBe("en");
  });
});

describe("i18nStore · 壳桥接（settings:get / settings:set）", () => {
  it("hydrateFromShell：壳 settings.language 权威覆盖本地兜底", async () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    installFakeShell("zh-CN");

    await act(async () => {
      await useI18nStore.getState().hydrateFromShell();
    });

    expect(useI18nStore.getState().language).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("zh-CN");
  });

  it("hydrateFromShell：无壳 → 保留本地兜底（不抛错、不改语言）", async () => {
    useI18nStore.setState({ language: "zh-CN" });
    removeFakeShell();

    await act(async () => {
      await useI18nStore.getState().hydrateFromShell();
    });

    expect(useI18nStore.getState().language).toBe("zh-CN");
  });

  it("setLanguage：壳可用 → 经既有 settings:set 镜像 language（不新增通道）", async () => {
    const shell = installFakeShell();

    await act(async () => {
      useI18nStore.getState().setLanguage("zh-CN");
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(shell.setCalls).toContainEqual({ language: "zh-CN" });
  });
});
