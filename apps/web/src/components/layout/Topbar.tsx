import { ChevronDown, ChevronUp, PanelLeft, PanelRight, Pencil, Search, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

import { Input } from "@/components/ui/input";
import { useConversations, useRenameConversation } from "@/hooks/useConversations";
import { useTranslation } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";

/**
 * 内容区顶栏（Topbar）：侧栏开关 / 会话标题 / 页面内联搜索 / 右侧栏开关。
 *
 * V0.4.5 B5 · F-30（顶栏两层化）后本组件**退回内容区**形态：
 * - **品牌名 + 文件/编辑/视图/帮助 菜单已搬到 {@link import("@/components/layout/TitleMenuBar").TitleMenuBar}**
 *   （窗口最顶行，占据原系统标题栏位置），此处不再渲染；
 * - 左端 `[侧栏开关]`（仅主界面 `/chat`）、中段动态会话标题、
 *   右端 `[页面内联搜索] [右栏开关]`（右栏开关仅 `/chat` 且右栏未打开时）；
 * - **智能页（`/agents*`）整行不渲染**（空行无意义，F-27.1b 口径延续）；
 * - 高度 `h-[42px]`，与 `TitleMenuBar` 等高，两层视觉一致。
 *
 * 保留（V0.4.5 B3 · F-09）：
 * - `/chat` 动态会话标题（有会话才显标题）+ hover 编辑（`chat-title-edit`）；
 * - 搜索默认隐藏、点击展开（`topbar-search-toggle`），`Cmd/Ctrl + K` 聚焦。
 *
 * **B-19c（V0.4.6）**：非 `/chat` 路由的面包屑整体退场（含 `breadcrumb.*` i18n 键
 * 与 `buildBreadcrumb` 配套）；其余分支零改动。
 *
 * **不新增边框线**（沿用 B3·F-09「展开态去横线」口径）。
 */
export function Topbar() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const [searchParams] = useSearchParams();

  const sidebarOpen = useUiStore((state) => state.sidebarOpen);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);
  const rightPanelOpen = useUiStore((state) => state.rightPanelOpen);
  const toggleRightPanel = useUiStore((state) => state.toggleRightPanel);
  const pageSearch = useUiStore((state) => state.pageSearch);
  const setPageSearch = useUiStore((state) => state.setPageSearch);

  const searchInputRef = useRef<HTMLInputElement>(null);
  // 搜索框默认收起（仅放大镜常驻）；点击放大镜或 `Cmd/Ctrl+K` 展开。
  const [searchExpanded, setSearchExpanded] = useState(false);
  // F-20.4：结果导航游标（骨架；结果定位/滚动由页面消费，本波仅轻量实现，无虚拟滚动，A-B4-3）。
  const [searchCursor, setSearchCursor] = useState(0);
  // F-20.4：结果总数占位——本波未接入页面结果源（A-B4-3 骨架），占位 0。
  const searchTotal = 0;
  const searchNoResults = searchTotal === 0;

  const isChat = pathname === "/chat" || pathname.startsWith("/chat/");
  // F-27.1b（V0.4.5 B5）：智能页顶栏裁减判定。
  const isAgents = pathname === "/agents" || pathname.startsWith("/agents/");

  // 会话标题（F-09）：仅 `/chat` 且带 `?c=<id>` 时派生；标题空 → 回落 id。
  const conversationId = searchParams.get("c");
  const { data: conversations } = useConversations();
  const activeConversation = conversationId
    ? conversations?.find((conversation) => conversation.id === conversationId)
    : undefined;
  const chatTitle = conversationId ? activeConversation?.title?.trim() || conversationId : "";

  // 就地重命名（F-09 编辑标题，持久化 = `PUT /conversations/{id}`）。
  const renameConversation = useRenameConversation();
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");

  const startEdit = (): void => {
    setDraftTitle(activeConversation?.title ?? "");
    setEditing(true);
  };

  const commitEdit = (): void => {
    if (!conversationId) {
      setEditing(false);
      return;
    }
    const nextTitle = draftTitle.trim();
    setEditing(false);
    if (nextTitle.length === 0 || nextTitle === chatTitle) {
      return;
    }
    renameConversation.mutate({ id: conversationId, title: nextTitle });
  };

  const onEditKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitEdit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      setEditing(false);
    }
  };

  // Cmd/Ctrl + K → 展开并聚焦内联搜索框（页面未启用时无目标，忽略）。
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent): void => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (pageSearch.enabled) {
          setSearchExpanded(true);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [pageSearch.enabled]);

  // 展开后自动聚焦输入框。
  useEffect(() => {
    if (searchExpanded) {
      searchInputRef.current?.focus();
    }
  }, [searchExpanded]);

  // 页面未启用搜索时收起展开态（切换路由时复位）。
  useEffect(() => {
    if (!pageSearch.enabled) {
      setSearchExpanded(false);
    }
  }, [pageSearch.enabled]);

  // F-30：智能页（`/agents*`）内容区顶栏**整行不渲染**——无面包屑、无开关，
  // 保留空行只会浪费 42px 高度；其余路由（`/chat` 及其它页）正常渲染。
  if (isAgents) {
    return null;
  }

  return (
    <header
      data-testid="topbar"
      className="flex h-[42px] w-full flex-none items-center gap-2 bg-background px-3 text-xs text-muted-foreground"
    >
      {/* F-30：侧栏开关左置内容区首位——仅主界面 `/chat` 渲染。 */}
      {isChat ? (
        <button
          type="button"
          data-testid="topbar-sidebar-toggle"
          aria-label={t("topbar.sidebar.toggle")}
          aria-pressed={sidebarOpen}
          onClick={toggleSidebar}
          className="flex h-6 w-6 flex-none items-center justify-center rounded-md text-muted-foreground hover:bg-accent/15 hover:text-foreground"
        >
          <PanelLeft className="h-4 w-4" />
        </button>
      ) : null}

      {/* 会话标题（B-19c：非 /chat 面包屑退场，此行仅 /chat 承载动态标题）。 */}
      {isChat ? (
        // /chat：动态会话标题（无会话 → 不渲染文字）；标题旁 hover 显编辑按钮。
        <nav aria-label={t("chat.title")} className="flex min-w-0 items-center gap-1.5">
          {chatTitle ? (
            editing ? (
              <Input
                data-testid="chat-title-input"
                autoFocus
                value={draftTitle}
                aria-label={t("chat.title.edit.placeholder")}
                placeholder={t("chat.title.edit.placeholder")}
                onChange={(event) => setDraftTitle(event.target.value)}
                onKeyDown={onEditKeyDown}
                onBlur={commitEdit}
                className="h-6 w-[240px] text-xs text-foreground"
              />
            ) : (
              <span className="group flex min-w-0 items-center gap-1">
                <span className="truncate font-medium text-foreground">{chatTitle}</span>
                <button
                  type="button"
                  data-testid="chat-title-edit"
                  aria-label={t("chat.title.edit")}
                  title={t("chat.title.edit")}
                  onClick={startEdit}
                  className="flex h-5 w-5 flex-none items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-accent/15 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              </span>
            )
          ) : null}
        </nav>
      ) : null}

      {/* 撑开左侧 → 右侧按钮组统一右置（F-09 按钮右置）。 */}
      <div className="flex-1" />

      {/* 页面搜索（F-09）：图标常驻（**展开时隐藏**，B-12），点击展开；展开态为**胶囊** + 上/下结果导航 + 关闭 × + 计数（F-20.4）。 */}
      {pageSearch.enabled ? (
        <>
          {searchExpanded ? (
            <div
              data-testid="topbar-search-bar"
              className="flex h-7 items-center gap-0.5 rounded-full bg-muted pl-2.5 pr-1"
            >
              <Search className="h-3.5 w-3.5 flex-none text-muted-foreground" />
              <Input
                ref={searchInputRef}
                data-testid="topbar-search-input"
                value={pageSearch.query}
                placeholder={pageSearch.placeholder || t("topbar.search.placeholder")}
                onChange={(event) => {
                  setPageSearch({ query: event.target.value });
                  setSearchCursor(0);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    setSearchExpanded(false);
                  }
                }}
                className="h-5 w-[160px] border-0 bg-transparent px-1.5 text-xs shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
              />
              {/* 结果计数（F-20.4 / A-B4-3 骨架；无结果 → noResults）。 */}
              <span
                data-testid="topbar-search-count"
                className="flex-none whitespace-nowrap px-1 text-[11px] tabular-nums text-muted-foreground/70"
              >
                {searchNoResults
                  ? t("topbar.search.noResults")
                  : t("topbar.search.resultCount", {
                      current: searchCursor + 1,
                      total: searchTotal,
                    })}
              </span>
              <button
                type="button"
                data-testid="topbar-search-prev"
                aria-label={t("topbar.search.previous")}
                title={t("topbar.search.previous")}
                onClick={() => {
                  if (searchNoResults) {
                    return;
                  }
                  setSearchCursor((cursor) => Math.max(0, cursor - 1));
                }}
                className="flex h-5 w-5 flex-none items-center justify-center rounded-full text-muted-foreground hover:bg-accent/15 hover:text-foreground"
              >
                <ChevronUp className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                data-testid="topbar-search-next"
                aria-label={t("topbar.search.next")}
                title={t("topbar.search.next")}
                onClick={() => {
                  if (searchNoResults) {
                    return;
                  }
                  setSearchCursor((cursor) => Math.min(Math.max(searchTotal - 1, 0), cursor + 1));
                }}
                className="flex h-5 w-5 flex-none items-center justify-center rounded-full text-muted-foreground hover:bg-accent/15 hover:text-foreground"
              >
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                data-testid="topbar-search-close"
                aria-label={t("topbar.search.close")}
                title={t("topbar.search.close")}
                onClick={() => setSearchExpanded(false)}
                className="flex h-5 w-5 flex-none items-center justify-center rounded-full text-muted-foreground hover:bg-accent/15 hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : null}
          {/* B-12：展开态隐藏切换按钮（输入框内已有放大镜，避免重复）；关闭后恢复。 */}
          {!searchExpanded ? (
            <button
              type="button"
              data-testid="topbar-search-toggle"
              aria-label={t("topbar.search.open")}
              aria-expanded={searchExpanded}
              onClick={() => setSearchExpanded((previous) => !previous)}
              className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent/10 hover:text-foreground"
            >
              <Search className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </>
      ) : null}

      {/* F-25.3（V0.4.5 B5）：右栏开关两态——`rightPanelOpen === true` 时开关搬家到
          RightPanel 标签栏，此处不渲染；且仅主界面 `/chat` 显示（智能页裁减）。 */}
      {isChat && !rightPanelOpen ? (
        <button
          type="button"
          data-testid="topbar-right-panel-toggle"
          aria-label={t("topbar.rightPanel.toggle")}
          onClick={toggleRightPanel}
          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent/15 hover:text-foreground"
        >
          <PanelRight className="h-4 w-4" />
        </button>
      ) : null}
    </header>
  );
}
