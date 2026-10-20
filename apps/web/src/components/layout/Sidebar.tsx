import { Check, Folder, MoreHorizontal, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { ConversationSearchPopover } from "@/components/layout/ConversationSearchPopover";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useConversations } from "@/hooks/useConversations";
import { useProjects } from "@/hooks/useProjects";
import { useWorkspaces, useCreateWorkspace } from "@/hooks/useWorkspaces";
import { useTranslation } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

/** 「最近」筛选三态（D-UI 体验优化波 · DU-2）。 */
type RecentFilter = "all" | "projects" | "chats";

/**
 * 筛选下拉三态（B-01：`label` 改为 i18n key，渲染时经 `t()` 取词）。
 *
 * 「项目」复用 `sidebar.projects`（与分组标题同词），故不另设 key。
 */
const FILTER_OPTIONS: readonly { value: RecentFilter; labelKey: string }[] = [
  { value: "all", labelKey: "sidebar.filter.all" },
  { value: "projects", labelKey: "sidebar.projects" },
  { value: "chats", labelKey: "sidebar.filter.chats" },
];

/** 侧栏可复用的行样式。 */
const ROW_CLASS =
  "flex w-full items-center gap-2 truncate rounded-md px-2 py-1.5 text-left text-xs text-foreground transition-colors hover:bg-accent/15 hover:text-foreground";

/**
 * 分组侧栏（Sidebar）：**新聊天 / 项目 / 最近** 三段式（D-UI 体验优化波 · WS-L / DU-2）。
 *
 * - 新聊天 → `/chat`；
 * - 项目：读既有 `useProjects`（只读）；
 * - 最近：读既有 `useConversations`（只读），头部 ⋯ 菜单三态筛选（全部 · 项目 · 仅聊天）；
 * - 折叠态接 `uiStore.sidebarOpen`；`<nav>` ARIA；
 * - ≥md 常驻；<md 转抽屉（由顶栏「侧栏开关」唤出）；
 * - **F-02（V0.4.5 B1）**：头部右侧入口改为「搜索」→ `ConversationSearchPopover`
 *   （全局对话跳转；与 Topbar 内联「页面过滤」搜索并存）；
 * - **F-04（V0.4.5 B1）**：宽度接 `uiStore.sidebarWidth`（可拖宽 200–420，持久化）；
 * - **F-10（V0.4.5 B3）**：「新聊天」入口**仅主界面（`/chat`）显示**，其它路由隐藏。
 * - **F-29（V0.4.5 B5）**：品牌名上移至**整宽顶栏**，侧栏头部不再重复渲染
 *   （仅保留「搜索」入口）；`<md` 抽屉态起于顶栏下沿（`top-[42px]`）。
 * - **B-01（V0.4.6 BugFix）**：分组标题 / 「新聊天」/ 筛选三态 / 空态文案改走
 *   i18n（`sidebar.*`），语言切换即时重渲染。
 */
export function Sidebar() {
  const { t } = useTranslation();
  const sidebarOpen = useUiStore((state) => state.sidebarOpen);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);
  const sidebarWidth = useUiStore((state) => state.sidebarWidth);
  const [filter, setFilter] = useState<RecentFilter>("all");

  // F-10（V0.4.5 B3）：「新聊天」入口**仅主界面（`/chat`）显示**，其它页面（任务中心 /
  // 知识库 / 工作台 / agents 等）隐藏。判定 = 当前 `pathname.startsWith("/chat")`。
  const { pathname } = useLocation();
  const showNewChat = pathname.startsWith("/chat");

  // F-02：侧栏头部「搜索」弹层开合（本地态；弹层组件内为受控 radix Popover）。
  const [searchOpen, setSearchOpen] = useState(false);

  // Bug7：「新建工作空间」弹窗态。
  const [createOpen, setCreateOpen] = useState(false);
  const [wsName, setWsName] = useState("");
  const [wsPath, setWsPath] = useState("");
  const [wsFeedback, setWsFeedback] = useState<string | null>(null);
  const createWorkspace = useCreateWorkspace();

  // Bug7：桌面壳内可用「选择目录」IPC；纯 Web 部署降级为手动输入路径。
  const desktopApi = typeof window !== "undefined" ? window.wbtimeAiDesktop : undefined;
  const canPickDirectory = typeof desktopApi?.pickDirectory === "function";

  const handlePickDirectory = async (): Promise<void> => {
    if (!desktopApi?.pickDirectory) {
      return;
    }
    try {
      const dir = await desktopApi.pickDirectory();
      if (dir) {
        setWsPath(dir);
        setWsFeedback(null);
      }
    } catch (error) {
      setWsFeedback(toApiError(error).message);
    }
  };

  const handleCreateWorkspace = (): void => {
    if (!wsName.trim()) {
      setWsFeedback("请输入工作空间名称");
      return;
    }
    setWsFeedback(null);
    createWorkspace.mutate(
      {
        name: wsName.trim(),
        // Bug7：所选目录路径透传（后端存储语义另行评审，不阻塞）。
        settings: wsPath.trim() ? { path: wsPath.trim() } : undefined,
      },
      {
        onSuccess: () => {
          setCreateOpen(false);
          setWsName("");
          setWsPath("");
          setWsFeedback(null);
        },
        onError: (error) => setWsFeedback(toApiError(error).message),
      },
    );
  };

  const { data: workspaces } = useWorkspaces();
  const workspaceId = workspaces?.[0]?.id ?? null;
  const { data: projects } = useProjects(workspaceId);
  const { data: conversations } = useConversations();

  if (!sidebarOpen) {
    return null;
  }

  const projectList = projects ?? [];
  const conversationList = conversations ?? [];

  // 「全部」：聊天在前、项目在后，合计上限 10 条；「项目」/「仅聊天」只呈现对应来源。
  const recentChatItems = (filter === "all" || filter === "chats" ? conversationList : []).map(
    (c) => ({ kind: "chat" as const, id: c.id, label: c.title || "未命名会话" }),
  );
  const recentProjectItems = (filter === "all" || filter === "projects" ? projectList : []).map(
    (p) => ({ kind: "project" as const, id: p.id, label: p.name || "未命名项目" }),
  );
  const recentItems = [...recentChatItems, ...recentProjectItems].slice(0, 10);

  return (
    <>
      {/* <md：遮罩（点击关闭抽屉）。F-29：起于整宽顶栏下沿（`top-[42px]`），顶栏保持可点。 */}
      <div
        aria-hidden
        onClick={toggleSidebar}
        className="fixed bottom-0 left-0 right-0 top-[42px] z-30 bg-foreground/25 md:hidden"
      />
      <nav
        data-testid="sidebar"
        aria-label="项目与会话"
        /* F-04：宽度由 uiStore.sidebarWidth 驱动（可拖宽 200–420，持久化）。 */
        style={{ width: `${sidebarWidth}px` }}
        className="fixed bottom-0 left-[46px] top-[42px] z-40 flex flex-none flex-col gap-1 overflow-y-auto border-r border-border bg-muted px-3 py-3 text-xs md:static md:z-auto"
      >
        {/* 头部（F-29）：品牌名已上移至**整宽顶栏**首行，此处不再重复渲染
            （避免同屏两个品牌名）。保留既有「搜索」入口（右对齐），
            移除文案后以 `justify-end` 维持原有行高与右侧留白，布局不塌陷。 */}
        <div className="mb-1 flex items-center justify-end px-1">
          <ConversationSearchPopover open={searchOpen} onOpenChange={setSearchOpen} />
        </div>

        {/* 新聊天（F-10：仅主界面 `/chat` 显示；其它页面隐藏）。 */}
        {showNewChat ? (
          <Link
            to="/chat"
            data-testid="sidebar-new-chat"
            className="flex w-full items-center gap-2 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 dark:bg-accent dark:text-primary dark:hover:bg-accent/90"
          >
            <Pencil className="h-3.5 w-3.5" />
            {t("sidebar.newChat")}
          </Link>
        ) : null}

        {/* 项目（文件夹；Bug7：加号 → 「新建工作空间」弹窗）。 */}
        <div data-testid="sidebar-projects" className="mt-2 flex flex-col gap-0.5">
          <div className="flex items-center justify-between px-2 py-1">
            <span className="font-medium text-muted-foreground">{t("sidebar.projects")}</span>
            <button
              type="button"
              data-testid="sidebar-project-create"
              aria-label="新建工作空间"
              onClick={() => {
                setWsFeedback(null);
                setCreateOpen(true);
              }}
              className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          {projectList.length === 0 ? (
            <p className="px-2 py-1 text-muted-foreground/70">{t("sidebar.projects.empty")}</p>
          ) : (
            projectList.map((project) => (
              <Link
                key={project.id}
                to="/projects"
                data-testid={`sidebar-project-${project.id}`}
                className={ROW_CLASS}
              >
                <Folder className="h-3.5 w-3.5 flex-none text-muted-foreground" />
                <span className="truncate">{project.name || "未命名项目"}</span>
              </Link>
            ))
          )}
        </div>

        {/* 最近（⋯ 三态筛选） */}
        <div data-testid="sidebar-recent" className="mt-2 flex flex-col gap-0.5">
          <div className="flex items-center justify-between px-2 py-1">
            <span className="font-medium text-muted-foreground">{t("sidebar.recent")}</span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  data-testid="sidebar-filter"
                  aria-label="筛选最近"
                  className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
                >
                  <MoreHorizontal className="h-3.5 w-3.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" side="right" sideOffset={6} className="w-32">
                {FILTER_OPTIONS.map((option) => (
                  <DropdownMenuItem
                    key={option.value}
                    data-testid={`sidebar-filter-${option.value}`}
                    aria-checked={filter === option.value}
                    className={cn(
                      "justify-between text-xs",
                      filter === option.value && "font-medium text-primary dark:text-accent",
                    )}
                    onSelect={() => setFilter(option.value)}
                  >
                    {t(option.labelKey)}
                    {filter === option.value ? <Check className="h-3.5 w-3.5" /> : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {recentItems.length === 0 ? (
            <p className="px-2 py-1 text-muted-foreground/70">{t("sidebar.recent.empty")}</p>
          ) : (
            recentItems.map((item) => (
              <Link
                key={`${item.kind}-${item.id}`}
                to={item.kind === "chat" ? `/chat?c=${item.id}` : "/projects"}
                data-testid={`sidebar-recent-${item.kind}-${item.id}`}
                className={ROW_CLASS}
              >
                <span className="truncate">{item.label}</span>
              </Link>
            ))
          )}
        </div>
      </nav>

      {/* Bug7：新建工作空间弹窗（桌面壳内「选择目录」走 IPC；纯 Web 手动输入路径）。 */}
      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) {
            setWsFeedback(null);
          }
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>新建工作空间</DialogTitle>
            <DialogDescription>创建一个新的工作空间，可选关联本地目录。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="sidebar-ws-name">工作空间名称</Label>
              <Input
                id="sidebar-ws-name"
                data-testid="sidebar-ws-name"
                value={wsName}
                placeholder="必填"
                onChange={(event) => setWsName(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sidebar-ws-path">本地目录（可选）</Label>
              <div className="flex gap-2">
                <Input
                  id="sidebar-ws-path"
                  data-testid="sidebar-ws-path"
                  value={wsPath}
                  placeholder={canPickDirectory ? "点「选择目录」或手动输入" : "手动输入本地路径"}
                  onChange={(event) => setWsPath(event.target.value)}
                />
                {canPickDirectory ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid="sidebar-ws-pick"
                    onClick={() => void handlePickDirectory()}
                  >
                    选择目录
                  </Button>
                ) : null}
              </div>
              {!canPickDirectory ? (
                <p className="text-xs text-muted-foreground">
                  纯浏览器部署无目录选择能力，请手动输入路径。
                </p>
              ) : null}
            </div>
            {wsFeedback ? (
              <p className="text-sm text-destructive" data-testid="sidebar-ws-feedback">
                {wsFeedback}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button
              size="sm"
              data-testid="sidebar-ws-submit"
              disabled={createWorkspace.isPending}
              onClick={handleCreateWorkspace}
            >
              {createWorkspace.isPending ? "创建中…" : "创建"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
