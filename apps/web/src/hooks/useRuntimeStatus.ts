// ---------------------------------------------------------------------------
// 便携运行时状态 Hook（V0.4.3 · T6）
//
// 封装 `window.wbtimeAiDesktop` 的运行时 API：仅桌面壳内可用（`available=false` 时
// 纯 Web 部署不渲染相关 UI）。订阅 `onRuntimeProgress` 实时刷新，并提供
// `install`（重试）/ `cancel`（取消）受控操作。**不含业务校验**——状态口径由主进程给定。
// ---------------------------------------------------------------------------
import { useCallback, useEffect, useState } from "react";

import type { DesktopRuntimeStatus } from "@/types/desktop";

/** 从 Electron IPC 错误中提取可读文案。 */
function messageOf(error: unknown): string {
  if (error instanceof Error && error.message !== "") {
    return error.message
      .replace(/^Error invoking remote method '[^']*':\s*/, "")
      .replace(/^Error:\s*/, "");
  }
  return String(error);
}

/** `useRuntimeStatus` 返回值。 */
export interface UseRuntimeStatusResult {
  /** 当前是否运行于桌面壳内（`window.wbtimeAiDesktop` 存在）。 */
  available: boolean;
  /** 当前运行时状态（未加载 / 不可用 → `null`）。 */
  status: DesktopRuntimeStatus | null;
  /** 最近一次错误文案。 */
  error: string | null;
  /** 触发（或重试）解压。 */
  install: () => Promise<void>;
  /** 取消进行中的解压。 */
  cancel: () => Promise<void>;
}

/**
 * 便携运行时状态 Hook。
 *
 * @returns 可用性 / 状态 / 错误 + `install` / `cancel`。
 */
export function useRuntimeStatus(): UseRuntimeStatusResult {
  const api = typeof window !== "undefined" ? window.wbtimeAiDesktop : undefined;
  const available = api !== undefined;
  const [status, setStatus] = useState<DesktopRuntimeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (api === undefined) {
      return;
    }
    let active = true;
    void api
      .getRuntimeStatus()
      .then((next) => {
        if (active) {
          setStatus(next);
        }
      })
      .catch((err) => {
        if (active) {
          setError(messageOf(err));
        }
      });
    const off = api.onRuntimeProgress((next) => {
      if (active) {
        setStatus(next);
      }
    });
    return () => {
      active = false;
      off();
    };
  }, [api]);

  const install = useCallback(async (): Promise<void> => {
    if (api === undefined) {
      return;
    }
    setError(null);
    try {
      setStatus(await api.installRuntime());
    } catch (err) {
      setError(messageOf(err));
    }
  }, [api]);

  const cancel = useCallback(async (): Promise<void> => {
    if (api === undefined) {
      return;
    }
    try {
      setStatus(await api.cancelRuntime());
    } catch (err) {
      setError(messageOf(err));
    }
  }, [api]);

  return { available, status, error, install, cancel };
}
