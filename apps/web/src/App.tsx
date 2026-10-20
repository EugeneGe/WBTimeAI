import { DocumentTitle } from "@/components/common/DocumentTitle";
import { AppLayout } from "@/components/layout/AppLayout";

/**
 * 应用外壳（`AppLayout` 内含 `Outlet`，承载受保护子路由）。
 *
 * B-01（V0.4.6 BugFix）：随语言同步 `document.title`（`en` → `WBTimeAI` /
 * `zh-CN` → `观序智能平台`）；公开页（登录 / 注册）在各自页面另行挂载。
 */
export function App() {
  return (
    <>
      <DocumentTitle />
      <AppLayout />
    </>
  );
}
