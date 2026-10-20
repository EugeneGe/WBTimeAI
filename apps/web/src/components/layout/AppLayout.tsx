import { useCallback, useEffect, useRef } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { Rail } from "@/components/layout/Rail";
import { RightPanel } from "@/components/layout/RightPanel";
import { Sidebar } from "@/components/layout/Sidebar";
import { TitleMenuBar } from "@/components/layout/TitleMenuBar";
import { Topbar } from "@/components/layout/Topbar";
import { Toaster } from "@/components/ui/toast";
import { useMe } from "@/hooks/useAuth";
import { useUiStore } from "@/stores/uiStore";

/**
 * 应用外壳（D-UI 体验优化波 · WS-L / DU-1/DU-2/DU-3/DU-12）。
 *
 * 结构（V0.4.5 B5·F-30「顶栏两层化」后冻结）：
 *
 * ```
 * <div class="flex h-screen flex-col">
 *   <TitleMenuBar />                          ← 第 1 行：窗口最顶（名称 + 文件/编辑/视图/帮助）
 *   <div class="flex min-h-0 flex-1">          ← 第 2 行：左中右三区
 *     <Rail/> [<Sidebar/> <左拖动条/>]
 *     <div class="flex-col"><Topbar/><main/></div>   ← 内容区顶栏（左=侧栏开关 中=标题 右=搜索+面板开关）
 *     [右拖动条] <RightPanel/>
 *   </div>
 *   <Toaster/>
 * </div>
 * ```
 *
 * - **第 1 行（F-30）**：`<TitleMenuBar/>` 顶到窗口最顶——壳侧 `titleBarStyle: "hidden"` +
 *   `titleBarOverlay(42px)` 隐藏系统标题栏文字，系统最小化/最大化/关闭按钮以 overlay
 *   叠加在本行右端；故 Rail / Sidebar / 内容区 / 右栏全部落在其下方第二行。
 * - **内容区顶栏（F-30）**：`<Topbar/>` 回到第二行中间列内（主内容之上），承载
 *   侧栏开关（左上）、会话标题/面包屑（中）、搜索 + 右栏开关（右上）；智能页整行自隐藏。
 * - 登录态引导：`useMe()`（拉取 `/users/me`，401 → 拦截器自动 refresh → 重试一次）；
 * - 页面宽度由各页 `PageContainer` 按档声明（旧顶栏内单档硬编码宽度已移除）；
 * - 全局提示改由原语 `<Toaster/>` 承载（等价替代旧内联 toast）；
 * - **右栏拖宽（V0.4.4 Bug5）**：主列与 `<RightPanel/>` 之间插入拖动条
 *   （mousedown → window 绑 mousemove/mouseup → 解绑），宽度经
 *   `uiStore.setRightPanelWidth` 持久化（clamp 240–600）。不引入新依赖。
 * - **左栏拖宽（V0.4.5 B1·F-04）**：`<Sidebar/>` 与主列之间插入 `left-panel-resizer`
 *   （同构右栏范式；左栏在左 → 右拖变宽），宽度经 `uiStore.setSidebarWidth`
 *   持久化（clamp 200–420）；`<md` 抽屉态隐藏（`hidden md:block`）。
 * - **全局去侧栏（V0.4.5 B4·F-22.1）**：按 `pathname` 条件渲染——**仅 `/chat`（前缀）**
 *   渲染 `<Sidebar/>` 与左拖动条；其余页面隐藏侧栏，**Rail 图标列保留**。
 */
export function AppLayout() {
  useMe();

  // F-22.1（V0.4.5 B4）：**仅主界面 `/chat`** 渲染 `<Sidebar/>` 与左侧拖动条；
  // 其余页面（智能/任务中心/知识库/Workflow/工作台…）隐藏侧栏，**Rail 图标列保留**（q8 全局规则）。
  const { pathname } = useLocation();
  const showSidebar = pathname === "/chat" || pathname.startsWith("/chat/");

  const sidebarOpen = useUiStore((state) => state.sidebarOpen);
  const setSidebarWidth = useUiStore((state) => state.setSidebarWidth);
  const rightPanelOpen = useUiStore((state) => state.rightPanelOpen);
  const setRightPanelWidth = useUiStore((state) => state.setRightPanelWidth);
  const draggingRef = useRef(false);
  const leftDraggingRef = useRef(false);

  const handleMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      draggingRef.current = true;
      const startX = event.clientX;
      const startWidth = useUiStore.getState().rightPanelWidth;

      const onMouseMove = (moveEvent: MouseEvent): void => {
        if (!draggingRef.current) {
          return;
        }
        // 右栏在屏幕右侧：向左拖（clientX 减小）→ 宽度增大。
        setRightPanelWidth(startWidth + (startX - moveEvent.clientX));
      };
      const onMouseUp = (): void => {
        draggingRef.current = false;
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    },
    [setRightPanelWidth],
  );

  /** 左侧栏拖动条（F-04）：左栏在屏幕左侧 → 向右拖（clientX 增大）→ 宽度增大。 */
  const handleLeftMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      leftDraggingRef.current = true;
      const startX = event.clientX;
      const startWidth = useUiStore.getState().sidebarWidth;

      const onMouseMove = (moveEvent: MouseEvent): void => {
        if (!leftDraggingRef.current) {
          return;
        }
        // clamp（200–420）+ 持久化由 setSidebarWidth 内部完成。
        setSidebarWidth(startWidth + (moveEvent.clientX - startX));
      };
      const onMouseUp = (): void => {
        leftDraggingRef.current = false;
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    },
    [setSidebarWidth],
  );

  // 兜底：组件卸载时解绑全局监听（正常路径由 mouseup 解绑）。
  useEffect(() => {
    return () => {
      draggingRef.current = false;
      leftDraggingRef.current = false;
    };
  }, []);

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-page text-foreground">
      {/* 第 1 行（F-30）：窗口最顶——品牌名 + 文件/编辑/视图/帮助菜单（占据原系统标题栏位置，
          系统窗口按钮由壳侧 titleBarOverlay 叠加在本行右端）。 */}
      <TitleMenuBar />

      {/* 第 2 行（F-30）：左（Rail + 侧栏 + 左拖动条）｜中（内容区顶栏 + 主内容）｜右（右拖动条 + 右栏）。 */}
      <div className="flex min-h-0 flex-1">
        <Rail />
        {showSidebar ? <Sidebar /> : null}
        {showSidebar && sidebarOpen ? (
          <div
            data-testid="left-panel-resizer"
            role="separator"
            aria-orientation="vertical"
            aria-label="拖动调整侧栏宽度"
            onMouseDown={handleLeftMouseDown}
            className="hidden w-1.5 flex-none cursor-col-resize bg-transparent transition-colors hover:bg-accent/30 md:block"
          />
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* 内容区顶栏（F-30）：左=侧栏开关 · 中=会话标题/面包屑 · 右=搜索 + 右栏开关；
              智能页（/agents*）内部整行自隐藏。 */}
          <Topbar />
          <main data-testid="app-main" className="min-h-0 flex-1 overflow-auto">
            <Outlet />
          </main>
        </div>
        {rightPanelOpen ? (
          <div
            data-testid="right-panel-resizer"
            role="separator"
            aria-orientation="vertical"
            aria-label="拖动调整右侧栏宽度"
            onMouseDown={handleMouseDown}
            className="w-1.5 flex-none cursor-col-resize bg-transparent transition-colors hover:bg-accent/30"
          />
        ) : null}
        <RightPanel />
      </div>

      <Toaster />
    </div>
  );
}
