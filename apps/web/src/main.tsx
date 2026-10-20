import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { queryClient } from "@/lib/query";
import { router } from "@/router";
import { applyDocumentLanguage, useI18nStore } from "@/stores/i18nStore";
import { useUiStore } from "@/stores/uiStore";

import "./index.css";

// 应用持久化主题（class 策略）。
const initialTheme = useUiStore.getState().theme;
useUiStore.getState().setTheme(initialTheme);

// 初始化界面语言（V0.4.5 B3 · F-12）：同步 `<html lang>`；壳内以 `settings.json.language`
// 为权威（异步 `hydrateFromShell` 覆盖 localStorage 兜底值），纯 Web 回退 localStorage。
applyDocumentLanguage(useI18nStore.getState().language);
void useI18nStore.getState().hydrateFromShell();

const container = document.getElementById("root");
if (!container) {
  throw new Error("未找到挂载点 #root");
}

// 顶层错误边界包住整个 React 树（含 RouterProvider），任一渲染异常均兜底而非白屏。
createRoot(container).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
