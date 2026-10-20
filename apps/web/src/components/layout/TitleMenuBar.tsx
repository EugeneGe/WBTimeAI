// ---------------------------------------------------------------------------
// WBTimeAI · 窗口最顶行「名称 + 菜单」（V0.4.5 B5 · F-30）
//
// 用户要求（ref28/ref29/ref30）：原系统标题栏（品牌名 + 最小化/最大化/关闭）
// 那一行**由本组件顶替**——即窗口最顶只有一行
// `[品牌名] [文件 编辑 视图 帮助]`，右侧留出系统窗口按钮的位置。
// （B-01：品牌名随语言，en = `WBTimeAI` / zh-CN = `观序智能平台`。）
//
// 结构口径（V0.4.5 B5·F-30）：
// ```
// 窗口最顶（42px，原系统标题栏位置）：[品牌名] [AppMenuBar]      ← 系统按钮 overlay 在最右
// 第 2 行：[Rail] [Sidebar] | <内容区：Topbar + 主内容> | [RightPanel]
// ```
//
// - **壳侧配合**：`apps/desktop/src/main/window.ts` 用
//   `titleBarStyle: "hidden"` + `titleBarOverlay: { height: 42 }`，
//   系统最小化/最大化/关闭按钮以 overlay 绘制在本行右端（约 138px 宽）。
// - **拖拽区**：根元素 `WebkitAppRegion: "drag"`（整行可拖动窗口）；
//   可交互元素（菜单栏）必须 `WebkitAppRegion: "no-drag"`，否则点不动。
// - **右侧留白**：`pr-[140px]` 固定预留系统按钮区（纯 Web 环境无害）。
// - 高度 42px 与壳侧 `titleBarOverlay.height` 严格一致，避免按钮错位。
// ---------------------------------------------------------------------------
import type { CSSProperties } from "react";

import { AppMenuBar } from "@/components/layout/AppMenuBar";
import { useTranslation } from "@/i18n";

/**
 * Electron 无边框窗口拖拽区样式。
 *
 * `WebkitAppRegion` 未收进 React 的 `CSSProperties` 类型定义，故此处显式断言。
 */
const DRAG_REGION_STYLE: CSSProperties = { WebkitAppRegion: "drag" } as CSSProperties;

/** 可交互元素样式：抵消父级拖拽区，恢复点击 / hover 行为。 */
const NO_DRAG_REGION_STYLE: CSSProperties = { WebkitAppRegion: "no-drag" } as CSSProperties;

/**
 * 窗口最顶行：品牌名 + 顶栏 HTML 菜单（文件 / 编辑 / 视图 / 帮助）。
 *
 * 全路由常驻（含智能页 `/agents*`）；由 {@link import("@/components/layout/AppLayout").AppLayout}
 * 渲染为外壳**第一行**（`flex-none`），Rail / Sidebar / 内容区 / 右栏一律在其下方第二行。
 */
export function TitleMenuBar() {
  const { t } = useTranslation();

  return (
    <div
      data-testid="title-menu-bar"
      // `pr-[140px]`：为 overlay 系统窗口按钮（Windows 约 138px）预留右侧空间。
      className="flex h-[42px] w-full flex-none select-none items-center gap-2 bg-background pl-3 pr-[140px] text-xs text-muted-foreground"
      style={DRAG_REGION_STYLE}
    >
      {/* 品牌名（`app.name` i18n 键；B-01 起**随语言**：en `WBTimeAI` / zh-CN `观序智能平台`）。 */}
      <span className="flex-none whitespace-nowrap text-sm font-medium text-foreground">
        {t("app.name")}
      </span>

      {/* 顶栏菜单（可点击 → no-drag 区）。 */}
      <div className="flex min-w-0 items-center" style={NO_DRAG_REGION_STYLE}>
        <AppMenuBar />
      </div>
    </div>
  );
}
