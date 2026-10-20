// ---------------------------------------------------------------------------
// WBTimeAI · 文档标题同步（B-01，V0.4.6 BugFix）
//
// 需求：`document.title` 随界面语言变化——
//   `en` → `WBTimeAI`；`zh-CN` → `观序智能平台`（即 `app.name` 的取词结果）。
//
// 挂载点（两处，保证**首屏**与**切换语言后**都正确）：
//   ① `App.tsx`（受保护壳，覆盖 `/` `/chat` `/workbench` 等全部认证页）；
//   ② `pages/Login.tsx` / `pages/Register.tsx`（公开页，不经 `App`）。
//
// 零副作用：渲染 `null`，仅经 `useEffect` 写 `document.title`；语言经
// `useTranslation()` 订阅，切换即时生效（清理函数不还原标题——单实例常驻）。
// ---------------------------------------------------------------------------
import { useEffect } from "react";

import { useTranslation } from "@/i18n";

/**
 * 同步 `document.title` 为当前语言的品牌名（`app.name`）。
 *
 * @returns 恒为 `null`（不产生任何 DOM 节点）。
 */
export function DocumentTitle(): null {
  const { t } = useTranslation();
  const title = t("app.name");

  useEffect(() => {
    document.title = title;
  }, [title]);

  return null;
}
