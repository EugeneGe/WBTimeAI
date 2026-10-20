import { PanelRightClose, Plus, X } from "lucide-react";
import { useEffect } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { useUiStore } from "@/stores/uiStore";
import { cn } from "@/lib/cn";

/**
 * 右侧栏（RightPanel）：标签页式预览面板（D-UI 体验优化波 · WS-L / DU-12）。
 *
 * - 由顶栏右侧栏开关开合（`uiStore.rightPanelOpen`）；
 * - 宽度可拖 240–600（`uiStore.rightPanelWidth`，持久化；V0.4.4 Bug5）、多标签；
 *   `Esc` 或再点开关关闭；
 * - 数据读 `uiStore.previewTabs / activePreviewId / closePreviewTab / setActivePreviewId`（WS-F 冻结名）；
 * - 无标签时呈现空态占位。
 */
export function RightPanel() {
  const open = useUiStore((state) => state.rightPanelOpen);
  const width = useUiStore((state) => state.rightPanelWidth);
  const tabs = useUiStore((state) => state.previewTabs);
  const activeId = useUiStore((state) => state.activePreviewId);
  const setActivePreviewId = useUiStore((state) => state.setActivePreviewId);
  const closePreviewTab = useUiStore((state) => state.closePreviewTab);
  const toggleRightPanel = useUiStore((state) => state.toggleRightPanel);

  // Esc 关闭右侧栏。
  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        toggleRightPanel();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, toggleRightPanel]);

  if (!open) {
    return null;
  }

  const active = tabs.find((tab) => tab.id === activeId) ?? tabs[0] ?? null;

  return (
    <aside
      data-testid="right-panel"
      aria-label="预览面板"
      /* Bug5：宽度由 uiStore.rightPanelWidth 驱动（可拖宽 240–600，持久化）。 */
      style={{ width: `${width}px` }}
      className="flex flex-none flex-col overflow-hidden border-l border-border bg-card text-xs"
    >
      {/* 标签栏 */}
      <div
        data-testid="right-panel-tabs"
        role="tablist"
        className="flex flex-none items-center gap-1.5 border-b border-border px-2.5 py-2"
      >
        {tabs.map((tab) => {
          const isActive = active?.id === tab.id;
          return (
            <span
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              tabIndex={isActive ? 0 : -1}
              data-testid={`right-panel-tab-${tab.id}`}
              onClick={() => setActivePreviewId(tab.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setActivePreviewId(tab.id);
                }
              }}
              className={cn(
                "flex max-w-[180px] cursor-pointer items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-[11px] text-foreground",
                isActive ? "border-accent" : "border-border",
              )}
            >
              <span className="truncate">{tab.title}</span>
              <button
                type="button"
                aria-label={`关闭 ${tab.title}`}
                data-testid={`right-panel-tab-close-${tab.id}`}
                onClick={(event) => {
                  event.stopPropagation();
                  closePreviewTab(tab.id);
                }}
                className="flex h-4 w-4 flex-none items-center justify-center rounded text-muted-foreground hover:bg-accent/15 hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          );
        })}
        <button
          type="button"
          aria-label="新建预览标签"
          data-testid="right-panel-tab-add"
          className="flex h-6 w-6 flex-none items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent/15 hover:text-foreground"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>

        {/* F-25.3（V0.4.5 B5）：收起开关搬家至标签栏行最右端（`rightPanelOpen` 时 Topbar 不再渲染开关）。 */}
        <span className="flex-1" />
        <button
          type="button"
          aria-label="收起右侧栏"
          title="收起右侧栏"
          data-testid="right-panel-collapse"
          onClick={toggleRightPanel}
          className="flex h-6 w-6 flex-none items-center justify-center rounded-md text-muted-foreground hover:bg-accent/15 hover:text-foreground"
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
      </div>

      {/* 预览主体 */}
      <div data-testid="right-panel-body" className="flex-1 overflow-auto p-3">
        {active ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-medium text-foreground">{active.title}</span>
              <span className="flex-none text-[11px] text-muted-foreground">预览</span>
            </div>
            <div className="flex gap-2 text-[11px] text-muted-foreground">
              <span>Markdown 预览</span>
              <span>·</span>
              <span>打开浏览器 ›</span>
              <span>查看工作空间 ›</span>
            </div>
            {/* 预览内容占位（真实产物渲染由后续波次接入）。 */}
            <div className="flex flex-col gap-2 pt-1">
              <Skeleton className="h-2.5 w-2/5" />
              <Skeleton className="h-2.5 w-[90%]" />
              <Skeleton className="h-2.5 w-[90%]" />
              <Skeleton className="h-2.5 w-3/5" />
            </div>
          </div>
        ) : (
          <div
            data-testid="right-panel-empty"
            className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground"
          >
            <p className="text-xs">暂无预览</p>
            <p className="text-[11px]">点击对话中的文件或日志条目，在右侧标签页中预览</p>
          </div>
        )}
      </div>
    </aside>
  );
}
