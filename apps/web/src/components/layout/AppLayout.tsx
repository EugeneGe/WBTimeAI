import { Outlet } from "react-router-dom";

import { Navbar } from "@/components/layout/Navbar";
import { useMe } from "@/hooks/useAuth";
import { useUiStore } from "@/stores/uiStore";

/** 应用外壳：顶栏 + 内容 `Outlet`（登录后引导 `useMe()`）。 */
export function AppLayout() {
  // 登录态引导：拉取 `/users/me`（401 → 拦截器自动 refresh → 重试一次）。
  useMe();
  const toast = useUiStore((state) => state.toast);
  const dismissToast = useUiStore((state) => state.dismissToast);

  return (
    <div className="min-h-screen bg-background">
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <Outlet />
      </main>
      {toast ? (
        <div className="fixed bottom-4 right-4 z-50 max-w-sm rounded-lg border bg-card p-4 shadow-lg">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium">{toast.title}</p>
              {toast.description ? (
                <p className="mt-1 text-xs text-muted-foreground">{toast.description}</p>
              ) : null}
            </div>
            <button
              type="button"
              className="text-xs text-muted-foreground underline"
              onClick={dismissToast}
            >
              关闭
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
