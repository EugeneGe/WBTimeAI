// ---------------------------------------------------------------------------
// WBTimeAI · i18n 核心（V0.4.5 B3 · F-12；**自研轻量，零新增依赖**）
//
// 设计裁定（`docs/施工方案/V0.4.5/03-…-设置与导航-2026-10-15.md` §2.2 / §4.2 / §8）：
// - `t(key, params?)`：以**当前 store 语言**翻译（非响应式；在渲染中请用 `useTranslation()`）；
// - `translate(language, key, params?)`：显式指定语言的纯翻译函数；
// - `useTranslation()`：订阅 `i18nStore.language` → 语言切换即时重渲染；
// - `registerLanguage(language, dict)`：注册 / 替换某语言资源字典（语言注册）；
// - **缺键回退**：目标语言缺 → 回退 `en`；`en` 亦缺 → 返回 **key 原文**。
//
// 🔴 **依赖方向**：本模块单向依赖 `@/stores/i18nStore`（核心**不**被 store 反向依赖），
//   语言基元（`Language` / `DEFAULT_LANGUAGE` / `SUPPORTED_LANGUAGES` / `isLanguage`）
//   定义于 store，此处**再导出**以满足 §4.2 公共面，同时规避循环依赖。
// ---------------------------------------------------------------------------
import { useCallback } from "react";

import {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  isLanguage,
  useI18nStore,
} from "@/stores/i18nStore";
import type { Language } from "@/stores/i18nStore";

import { en } from "./locales/en";
import { zhCN } from "./locales/zh-CN";

// 再导出语言基元（§4.2 公共面；定义见 `@/stores/i18nStore`，避免循环依赖）。
export { DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, isLanguage };
export type { Language };

/** 翻译参数（`{ name }` 占位替换）。 */
export type TranslationParams = Record<string, string | number>;

/** 语言资源注册表（语言 → 键值字典）。 */
const RESOURCES: Record<Language, Record<string, string>> = {
  en: { ...en },
  "zh-CN": { ...zhCN },
};

/**
 * 注册（或替换）某语言的资源字典。
 *
 * @param language 目标语言。
 * @param dict 该语言的键值字典（**替换**该语言既有字典）。
 */
export function registerLanguage(language: Language, dict: Record<string, string>): void {
  RESOURCES[language] = { ...dict };
}

/** 读取某语言当前字典（只读快照；供调试 / 测试）。 */
export function getResource(language: Language): Record<string, string> {
  return RESOURCES[language];
}

/** 将 `{name}` 占位替换为 `params` 值（未提供的占位保持原样）。 */
function interpolate(template: string, params?: TranslationParams): string {
  if (params === undefined) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match: string, name: string) => {
    const value = params[name];
    return value === undefined ? match : String(value);
  });
}

/**
 * 以指定语言翻译 key（纯函数）。
 *
 * 回退链：`RESOURCES[language][key]` → `RESOURCES.en[key]` → `key` 原文。
 *
 * @param language 目标语言。
 * @param key i18n key（`<域>.<块>.<名>`）。
 * @param params 插值参数（可选）。
 * @returns 翻译结果（含缺键回退）。
 */
export function translate(language: Language, key: string, params?: TranslationParams): string {
  const primary = RESOURCES[language];
  const raw = primary[key] ?? RESOURCES[DEFAULT_LANGUAGE][key] ?? key;
  return interpolate(raw, params);
}

/**
 * 以**当前 store 语言**翻译 key（非响应式便捷入口）。
 *
 * ⚠️ 在 React 组件内应使用 `useTranslation()`（订阅语言变更以触发重渲染）。
 *
 * @param key i18n key。
 * @param params 插值参数（可选）。
 */
export function t(key: string, params?: TranslationParams): string {
  return translate(useI18nStore.getState().language, key, params);
}

/** `useTranslation()` 返回值。 */
export interface UseTranslationResult {
  /** 绑定当前语言的翻译函数（语言变更后自动更新）。 */
  t: (key: string, params?: TranslationParams) => string;
  /** 当前语言。 */
  language: Language;
}

/**
 * React Hook：订阅当前语言并返回绑定语言的 `t`。
 *
 * 语言经 `i18nStore` 变更时，使用本 Hook 的组件即时重渲染。
 *
 * @returns `{ t, language }`。
 */
export function useTranslation(): UseTranslationResult {
  const language = useI18nStore((state) => state.language);
  const boundT = useCallback(
    (key: string, params?: TranslationParams): string => translate(language, key, params),
    [language],
  );
  return { t: boundT, language };
}
