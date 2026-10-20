// ---------------------------------------------------------------------------
// 路由级加载态（D-UI体验优化波 · WS-I · DU-9）
//
// 作用：`React.lazy` 页面分包就绪前的 `<Suspense fallback>` 占位。样式走 token
// 语义类，亮/暗双主题下自然适配，避免加载瞬间的色差闪动。
//
// 具名导出、无 default（裁定 §4.5）；`role="status"` + `aria-live` 提供无障碍反馈。
// ---------------------------------------------------------------------------
import { Loader2 } from "lucide-react";

/** 路由级加载兜底（供 `router.tsx` 的 `<Suspense fallback>` 使用）。 */
export function RouteFallback() {
  return (
    <div
      data-testid="route-fallback"
      role="status"
      aria-live="polite"
      className="flex min-h-[40vh] w-full items-center justify-center p-8"
    >
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" />
        <span className="text-sm">加载中…</span>
      </div>
    </div>
  );
}
