// ---------------------------------------------------------------------------
// 桌面设置 Hook（V0.4.2 · W2 · T4）
//
// 封装 `window.wbtimeAiDesktop.getSettings()` / `setSettings(patch)`：仅桌面壳内可用
// （`available=false` 时纯 Web 部署不渲染相关 UI）。
//
// 🔴 校验归属：本 Hook 仅做 IPC 读写与错误回显；**权威校验在主进程**
//    （`SettingsStore.update` → `validateDataDir`），非法值经 IPC 拒绝回传。
// ---------------------------------------------------------------------------
import { useCallback, useEffect, useState } from "react";

import type { DesktopSettings, DesktopSettingsPatch } from "@/types/desktop";

/** 从 Electron IPC 错误中提取可读文案（去除 `Error invoking remote method ...` 包装与内层 `Error:` 前缀）。 */
function messageOf(error: unknown): string {
  if (error instanceof Error && error.message !== "") {
    return error.message
      .replace(/^Error invoking remote method '[^']*':\s*/, "")
      .replace(/^Error:\s*/, "");
  }
  return String(error);
}

/** `useDesktopSettings` 返回值。 */
export interface UseDesktopSettingsResult {
  /** 当前是否运行于桌面壳内（`window.wbtimeAiDesktop` 存在）。 */
  available: boolean;
  /** 当前设置（未加载完成 / 不可用 → `null`）。 */
  settings: DesktopSettings | null;
  /** 最近一次错误文案（读 / 写失败）。 */
  error: string | null;
  /** 是否正在加载设置。 */
  loading: boolean;
  /** 重新读取设置。 */
  reload: () => Promise<void>;
  /** 保存补丁（失败 → 记录 `error` 并返回 `null`）。 */
  save: (patch: DesktopSettingsPatch) => Promise<DesktopSettings | null>;
}

/**
 * 桌面设置读写 Hook。
 *
 * @returns 可用性 / 当前设置 / 错误 / 加载态 + `reload` / `save`。
 */
export function useDesktopSettings(): UseDesktopSettingsResult {
  const api = typeof window !== "undefined" ? window.wbtimeAiDesktop : undefined;
  const available = api !== undefined;
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(available);

  const reload = useCallback(async (): Promise<void> => {
    if (api === undefined) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setSettings(await api.getSettings());
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const save = useCallback(
    async (patch: DesktopSettingsPatch): Promise<DesktopSettings | null> => {
      if (api === undefined) {
        return null;
      }
      setError(null);
      try {
        const next = await api.setSettings(patch);
        setSettings(next);
        return next;
      } catch (err) {
        setError(messageOf(err));
        return null;
      }
    },
    [api],
  );

  return { available, settings, error, loading, reload, save };
}
