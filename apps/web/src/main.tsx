import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { queryClient } from "@/lib/query";
import { router } from "@/router";
import { useUiStore } from "@/stores/uiStore";

import "./index.css";

// 应用持久化主题（class 策略）。
const initialTheme = useUiStore.getState().theme;
useUiStore.getState().setTheme(initialTheme);

const container = document.getElementById("root");
if (!container) {
  throw new Error("未找到挂载点 #root");
}

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
