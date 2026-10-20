import type { LucideIcon } from "lucide-react";
import {
  BadgeCheck,
  Bell,
  BookOpen,
  Bot,
  Boxes,
  Brain,
  Building2,
  FlaskConical,
  FolderKanban,
  Home,
  LayoutDashboard,
  Layers,
  ListChecks,
  Rocket,
  Workflow as WorkflowIcon,
  Wrench,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { UserMenu } from "@/components/layout/UserMenu";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useApprovals } from "@/hooks/useApprovals";
import { useTranslation } from "@/i18n";
import { formatRelativeTime, type TranslateFn } from "@/lib/agentDisplay";
import { useUiStore } from "@/stores/uiStore";
import { cn } from "@/lib/cn";

/** 导航项分组（V0.4.6 · B-25）。 */
export type RailItemGroup = "fixed" | "optional";

/**
 * 一级导航项（D-UI 体验优化波 · WS-L / DU-2；V0.4.6 B-25 引入 `group`）。
 */
export interface RailItem {
  /** 稳定 key（用于 `data-testid` 与可选模块开关）。 */
  key: string;
  /** 目标路由。 */
  to: string;
  /** 无障碍与 tooltip 文案的 **i18n key**（V0.4.5 B3 · F-12；如 `nav.agents`）。 */
  labelKey: string;
  /** lucide 图标。 */
  icon: LucideIcon;
  /** 是否精确匹配（`end`）。`workbench` 用 `true` 精确匹配 `/workbench`；`home` 用 `false` 使 `/chat?c=` 前缀亦高亮（F-21）。 */
  end?: boolean;
  /**
   * 是否启用（默认 `true`）。
   *
   * `enabled === false` 表示**预留槽位**：社区版不渲染（无图标），仅保留配置条目，
   * 待对应版本启用时置 `true`（或移除该字段）即可上线（U-9）。
   */
  enabled?: boolean;
  /**
   * 是否渲染于**顶部品牌位**（V0.4.5 B3 · F-15）。
   *
   * `brand === true` 的条目（`home`）落在 Rail 顶部品牌方块处（`data-testid="rail-home"`，
   * 沿用 V0.4.5 B1·F-01 冻结事实源），其余条目渲染为常规一级导航图标（`rail-nav-<key>`）。
   */
  brand?: boolean;
  /**
   * 分组（V0.4.6 · B-25）：
   *
   * - `fixed`：**恒在**左侧栏、不可关闭（主界面 / 智能·专家与智能体 / 知识库 / 工作台）；
   * - `optional`：**社区版可选模块**，由工作台（`pages/User.tsx`）的「左侧栏模块」
   *   开关决定是否上栏；勾选后渲染在**工作台之上**。
   */
  group: RailItemGroup;
}

/**
 * **固定项 4 项**（恒在左侧栏，顺序即渲染顺序：主界面 → 智能·专家与智能体 → 知识库 → 工作台）。
 *
 * ⚠️ 渲染顺序另由 `Rail` 组件拼装（工作台恒为**最后一个导航项**，故此处虽列于末位，
 * 实际渲染位置由 {@link WORKBENCH_ITEM} 落在可选模块之后）。
 */
// eslint-disable-next-line react-refresh/only-export-components
export const FIXED_RAIL_ITEMS: readonly RailItem[] = [
  // ① 主界面（顶部品牌位；F-01 冻结 `rail-home`；F-21 改指 `/chat`，`end:false` 兼容 `/chat?c=`）。
  {
    key: "home",
    to: "/chat",
    labelKey: "nav.home",
    icon: Home,
    end: false,
    brand: true,
    group: "fixed",
  },
  // ② 智能 · 专家与智能体（内置 + 自定义）。
  { key: "agents", to: "/agents", labelKey: "nav.agents", icon: Bot, group: "fixed" },
  // ③ 知识库。
  {
    key: "knowledge",
    to: "/studio/knowledge",
    labelKey: "nav.knowledge",
    icon: BookOpen,
    group: "fixed",
  },
  // ④ 工作台（B-02：`to:"/workbench"`，`end:true` 精确匹配；原 `to:"/"` 让位给 `/chat` 落地页）。
  {
    key: "workbench",
    to: "/workbench",
    labelKey: "nav.workbench",
    icon: LayoutDashboard,
    end: true,
    group: "fixed",
  },
];

/**
 * **可选模块 10 项**（社区版模块；顺序 = 注册表顺序，**勿改序**）。
 *
 * 默认仅 `tasks` / `workflows` 上栏（见 `uiStore.DEFAULT_RAIL_MODULES`），其余由用户
 * 在工作台勾选；勾选后渲染在**工作台之上**。`evaluation` / `memory` 为 Studio 子路由，
 * `studio` 用 `end: true` 精确匹配，避免 `/studio/*` 子路由同时点亮两个图标。
 *
 * ⚠️ **顺序契约**：本数组顺序必须与 `uiStore.OPTIONAL_RAIL_KEYS` **完全一致**
 * （后者是 `normalizeRailModules` 的排序依据，落盘顺序以它为准）。
 */
// eslint-disable-next-line react-refresh/only-export-components
export const OPTIONAL_RAIL_ITEMS: readonly RailItem[] = [
  { key: "tasks", to: "/tasks", labelKey: "nav.tasks", icon: ListChecks, group: "optional" },
  {
    key: "approvals",
    to: "/approvals",
    labelKey: "nav.approvals",
    // 图标选择：审批中心是「待办审批的收件箱」语义 —— `BadgeCheck`（徽章 + 对勾，
    // 传达「已核可」）既有别于 `ListChecks`（纯清单 + 对勾，语义偏「任务清单」），
    // 其圆形徽章轮廓也与 Rail 内其余图标（方块 / 书本 / 机器人 / 立方体）**剪影可辨**。
    icon: BadgeCheck,
    group: "optional",
  },
  {
    key: "workflows",
    to: "/studio/workflows",
    labelKey: "nav.workflows",
    icon: WorkflowIcon,
    group: "optional",
  },
  {
    key: "projects",
    to: "/projects",
    labelKey: "nav.projects",
    icon: FolderKanban,
    group: "optional",
  },
  {
    key: "workspace",
    to: "/workspace",
    labelKey: "nav.workspace",
    // B-25 修：原 `LayoutGrid` 与工作台 `LayoutDashboard` 视觉雷同 → 改用 `Layers`。
    icon: Layers,
    group: "optional",
  },
  {
    key: "remote-tasks",
    to: "/remote-tasks",
    labelKey: "nav.remoteTasks",
    icon: Rocket,
    group: "optional",
  },
  { key: "tools", to: "/tools", labelKey: "nav.tools", icon: Wrench, group: "optional" },
  {
    key: "studio",
    to: "/studio",
    labelKey: "nav.studio",
    icon: Boxes,
    end: true,
    group: "optional",
  },
  {
    key: "evaluation",
    to: "/studio/evaluation",
    labelKey: "nav.evaluation",
    icon: FlaskConical,
    group: "optional",
  },
  { key: "memory", to: "/studio/memory", labelKey: "nav.memory", icon: Brain, group: "optional" },
];

/**
 * 一级导航**全量注册表**（固定项 + 可选模块 + 预留槽位）。
 *
 * ⚠️ `enabled === false` 的条目（`enterprise`）**仅保留配置**、渲染层过滤（社区版不显示），
 * 供 V0.5 W3 企业设置页接入时启用（见 `docs/施工方案/V0.5/00-开工前架构裁定.md` `DD-7` / `U-9`）。
 *
 * 导出供隐藏态测试断言「预留槽位仍在」（U-9）。
 */
// eslint-disable-next-line react-refresh/only-export-components
export const RAIL_ITEMS: readonly RailItem[] = [
  ...FIXED_RAIL_ITEMS,
  ...OPTIONAL_RAIL_ITEMS,
  // U-9 预留（V0.5 W3 企业设置页接入；社区版 enabled=false 不渲染）。路径对齐 DD-7：落 pages/enterprise/*。
  {
    key: "enterprise",
    to: "/enterprise",
    labelKey: "nav.enterprise",
    icon: Building2,
    enabled: false,
    group: "optional",
  },
];

/** 顶部品牌位条目（`brand === true`；缺省回落首个条目）。 */
const BRAND_ITEM: RailItem = RAIL_ITEMS.find((item) => item.brand === true) ?? RAIL_ITEMS[0];

/** 品牌位之下的固定导航项（`agents` / `knowledge`；排除品牌位与末位工作台）。 */
const FIXED_NAV_ITEMS: readonly RailItem[] = FIXED_RAIL_ITEMS.filter(
  (item) => item.brand !== true && item.key !== "workbench",
);

/** 末位固定项：工作台（**恒为最后一个导航项**）。 */
const WORKBENCH_ITEM: RailItem =
  FIXED_RAIL_ITEMS.find((item) => item.key === "workbench") ??
  RAIL_ITEMS.find((item) => item.key === "workbench") ??
  RAIL_ITEMS[0];

/**
 * 判定路径是否命中某导航项（B-09）。
 *
 * 🔴 **不能把函数形式的 `className` 传给 `TooltipTrigger asChild` 包裹的 `NavLink`**：
 * Radix `Slot` 合并 props 时对 `className` 做 `[slot, child].join(" ")`，会把函数
 * `toString()` 成源码字符串写进 `class`——导致 active 分支永远不会作为真实类名生效
 * （`/workbench` 下「工作台」按钮无高亮）。故在此**自行计算** active，再传普通字符串。
 */
function isPathActive(pathname: string, to: string, end?: boolean): boolean {
  if (end) {
    return pathname === to;
  }
  return pathname === to || pathname.startsWith(to.endsWith("/") ? to : `${to}/`);
}

/** 提醒条目最多展示条数（弹层固定 360px 高，超出即滚动，故与列表长度解耦）。 */
const BELL_ITEM_LIMIT = 5;

/**
 * 提醒条目主体类型 → 展示名（复用审批域 i18n key；未知类型回落原文）。
 *
 * @param t 翻译函数。
 * @param subjectType 主体类型（`tool` / `mcp` / `workflow_node`）。
 * @returns 已翻译的主体类型名。
 */
function bellSubjectLabel(t: TranslateFn, subjectType: string): string {
  switch (subjectType) {
    case "tool":
      return t("approvals.subjectType.tool");
    case "mcp":
      return t("approvals.subjectType.mcp");
    case "workflow_node":
      return t("approvals.subjectType.workflow_node");
    default:
      return subjectType.length > 0 ? subjectType : t("approvals.subjectType.unknown");
  }
}

/**
 * 左侧图标栏（Rail）：主页入口 + 固定项 + 可选模块 + 底部（提醒铃 → 头像）。
 *
 * V0.4.6 · B-25 重构后的**冻结渲染顺序**：
 * `home(品牌位)` → `agents` → `knowledge` → 已启用的可选模块（按注册表序）→ `workbench`
 * → 弹性留白 → 铃铛 → 头像。
 *
 * - 顶部品牌位 = **主界面入口**（`rail-home`，NavLink `to="/chat"` + lucide `Home`；F-01 / F-15 / F-21）；
 * - 固定 4 项恒在（{@link FIXED_RAIL_ITEMS}），不可关闭；
 * - 可选模块由 `uiStore.railModules` 过滤（工作台「左侧栏模块」开关驱动）；
 * - 激活态：序金（`accent`）指示条 + 图标高亮 + **背景高亮**（F-22.2）；
 * - 悬停：`@/components/ui/tooltip` 提示（文案走 i18n，V0.4.5 B3 · F-12）；
 * - 图标区 `overflow-y-auto`（`min-h-0`）→ 项多时可滚；铃铛 / 头像固定底部不参与滚动。
 */
export function Rail() {
  // V0.4.5 B3 · F-12：导航文案走 i18n（语言切换即时重渲染）。
  const { t } = useTranslation();
  // Bug8：提醒未读数驱动铃铛红点（默认 0 → 无红点）。
  const unreadCount = useUiStore((state) => state.unreadCount);
  // B-25：已启用的可选模块（工作台勾选后即时重渲染）。
  const railModules = useUiStore((state) => state.railModules);
  // W10 / T2-49：真实待办来源（`GET /approvals`，仅 `PENDING`）→ 同步进 `unreadCount`。
  const setUnreadCount = useUiStore((state) => state.setUnreadCount);
  // B-09：active 态改由路径自算（原因见 {@link isPathActive}）。
  const { pathname } = useLocation();
  const navigate = useNavigate();
  // B-27：弹层开关改为受控（点击条目跳转前需主动关闭）。
  const [bellOpen, setBellOpen] = useState(false);
  const homeActive = isPathActive(pathname, BRAND_ITEM.to, BRAND_ITEM.end);

  // 真实待办：数据缺失（加载中 / 未登录 / 出错）→ 空数组，不阻塞外壳渲染。
  const approvalsQuery = useApprovals();
  const pendingApprovals = approvalsQuery.data ?? [];
  const pendingCount = pendingApprovals.length;
  const bellItems = pendingApprovals.slice(0, BELL_ITEM_LIMIT);

  // 红点仍由 `uiStore.unreadCount` 驱动（不删 store 字段，避免连锁改动）：
  // Rail 内把**真实待办数**同步进去，`setUnreadCount` 幂等（同值不触发额外渲染）。
  useEffect(() => {
    setUnreadCount(pendingCount);
  }, [pendingCount, setUnreadCount]);

  // B-25：已勾选的可选模块（按注册表序，不受勾选先后影响）。
  const enabledOptionalItems = OPTIONAL_RAIL_ITEMS.filter(
    (item) => item.enabled !== false && railModules.includes(item.key),
  );

  /**
   * 渲染单个常规导航项（图标 + tooltip + active 指示条）。
   *
   * @param item 导航项。
   * @returns 带 tooltip 的 NavLink 节点。
   */
  const renderNavItem = (item: RailItem) => {
    const active = isPathActive(pathname, item.to, item.end);
    return (
      <Tooltip key={item.key}>
        <TooltipTrigger asChild>
          <NavLink
            to={item.to}
            end={item.end}
            aria-label={t(item.labelKey)}
            data-testid={`rail-nav-${item.key}`}
            className={cn(
              "relative flex h-9 w-9 flex-none items-center justify-center rounded-md text-primary-foreground/60 transition-colors hover:bg-primary-foreground/10 hover:text-primary-foreground dark:text-muted-foreground dark:hover:bg-muted dark:hover:text-foreground",
              // F-22.2（V0.4.5 B4）：active 态**增加背景高亮**（浅 `bg-primary-foreground/10` /
              // 暗 `bg-muted`），与左侧金黄指示条（下方 span）**并存**。
              // F-27.1a（V0.4.5 B5）：浅色 active 背景增强 `/10` → `/20`（暗色不变）。
              // B-09：普通字符串（勿用函数，Radix Slot 会 stringify）。
              active &&
                "bg-primary-foreground/20 text-accent hover:bg-primary-foreground/20 hover:text-accent dark:bg-muted dark:text-accent dark:hover:bg-muted dark:hover:text-accent",
            )}
          >
            {active ? (
              <span
                aria-hidden
                className="absolute -left-[3px] top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-accent"
              />
            ) : null}
            <item.icon className="h-[18px] w-[18px]" />
          </NavLink>
        </TooltipTrigger>
        <TooltipContent side="right">{t(item.labelKey)}</TooltipContent>
      </Tooltip>
    );
  };

  return (
    <TooltipProvider delayDuration={250}>
      <nav
        data-testid="rail-nav"
        aria-label={t("rail.primaryNav")}
        className="flex h-full w-[46px] flex-none flex-col items-center gap-1 bg-primary py-3 dark:bg-page"
      >
        {/* 图标区（品牌位 / 固定项 / 可选模块 / 末位工作台）：项多时可独立滚动，
            铃铛与头像留在底部固定不滚（`min-h-0` 是 flex 子项可收缩的前提）。 */}
        <div className="flex min-h-0 flex-1 flex-col items-center gap-1 overflow-y-auto">
          {/* 品牌位 → 主界面入口（V0.4.5 B1·F-01 / B3·F-15 / B4·F-21）：可点 NavLink 直达主界面
              （`/chat`，`end:false` 使 `/chat?c=` 前缀亦高亮）。**B-12：去掉常驻金底方块**——
              与其余一级项同一套视觉：默认透明，激活时半透明背景 + 序金竖条；图标 lucide `Home`。 */}
          <Tooltip>
            <TooltipTrigger asChild>
              <NavLink
                to={BRAND_ITEM.to}
                end={BRAND_ITEM.end}
                aria-label={t(BRAND_ITEM.labelKey)}
                data-testid="rail-home"
                className={cn(
                  "relative mb-3 flex h-6 w-6 flex-none items-center justify-center rounded-[7px] text-primary-foreground/60 transition-colors hover:bg-primary-foreground/10 hover:text-primary-foreground dark:text-muted-foreground dark:hover:bg-muted dark:hover:text-foreground",
                  homeActive &&
                    "bg-primary-foreground/20 text-accent hover:bg-primary-foreground/20 hover:text-accent dark:bg-muted dark:text-accent dark:hover:bg-muted dark:hover:text-accent",
                )}
              >
                {homeActive ? (
                  <span
                    aria-hidden
                    className="absolute -left-[3px] top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-accent"
                  />
                ) : null}
                <Home className="h-3.5 w-3.5" />
              </NavLink>
            </TooltipTrigger>
            <TooltipContent side="right">{t(BRAND_ITEM.labelKey)}</TooltipContent>
          </Tooltip>

          {/* 固定项：智能·专家与智能体 / 知识库（恒在，不可关闭）。 */}
          {FIXED_NAV_ITEMS.map(renderNavItem)}

          {/* 可选模块（已启用的社区版模块；按注册表序，渲染在工作台之上）。 */}
          {enabledOptionalItems.map(renderNavItem)}

          {/* 末位固定项：工作台（**恒为最后一个导航项**，V0.4.6 B-25 冻结）。 */}
          {renderNavItem(WORKBENCH_ITEM)}
        </div>

        {/* 最底部：提醒铃（B-27：点击直接开**固定宽高的弹窗**，不再是窄气泡；
            W10 / T2-49：内容改为真实待办审批（`GET /approvals`），红点由真实待办数同步的
            `uiStore.unreadCount` 驱动；D-10：本段文案**全量 i18n 化**）。 */}
        <Dialog open={bellOpen} onOpenChange={setBellOpen}>
          <Tooltip>
            <TooltipTrigger asChild>
              <DialogTrigger asChild>
                <button
                  type="button"
                  data-testid="rail-bell"
                  aria-label={t("rail.bell.label")}
                  className="relative flex h-9 w-9 flex-none items-center justify-center rounded-md text-primary-foreground/60 transition-colors hover:bg-primary-foreground/10 hover:text-primary-foreground dark:text-muted-foreground dark:hover:bg-muted dark:hover:text-foreground"
                >
                  <Bell className="h-[18px] w-[18px]" />
                  {unreadCount > 0 ? (
                    <span
                      aria-hidden
                      data-testid="rail-bell-badge"
                      className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full border border-primary bg-accent dark:border-page"
                    />
                  ) : null}
                </button>
              </DialogTrigger>
            </TooltipTrigger>
            <TooltipContent side="right">{t("rail.bell.tooltip")}</TooltipContent>
          </Tooltip>
          {/* 固定宽高 440×360：头 / 可滚内容 / 尾（关闭）三段；Esc、遮罩、X 均可关闭。 */}
          <DialogContent
            data-testid="rail-notifications"
            className="flex h-[360px] w-[440px] max-w-[calc(100vw-2rem)] flex-col gap-0 p-0"
          >
            <DialogHeader className="flex-none border-b border-border px-4 py-3">
              <DialogTitle className="text-sm font-medium text-foreground">
                {t("rail.bell.title")}
              </DialogTitle>
            </DialogHeader>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {approvalsQuery.isLoading ? (
                <p
                  className="text-xs text-muted-foreground"
                  data-testid="rail-notifications-loading"
                >
                  {t("rail.bell.loading")}
                </p>
              ) : bellItems.length === 0 ? (
                <p className="text-xs text-muted-foreground" data-testid="rail-notifications-empty">
                  {t("rail.bell.empty")}
                </p>
              ) : (
                <ul className="space-y-0.5" data-testid="rail-notifications-list">
                  {bellItems.map((approval) => (
                    <li key={approval.id}>
                      <button
                        type="button"
                        data-testid={`rail-notification-${approval.id}`}
                        onClick={() => {
                          setBellOpen(false);
                          navigate("/approvals");
                        }}
                        className="flex w-full flex-col gap-0.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-accent/10"
                      >
                        <span className="truncate text-xs font-medium text-foreground">
                          {bellSubjectLabel(t, approval.subject_type)}
                        </span>
                        <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                          <span className="truncate">
                            {approval.requested_by && approval.requested_by.length > 0
                              ? approval.requested_by
                              : t("approvals.unknownUser")}
                          </span>
                          <span aria-hidden>·</span>
                          <span className="flex-none">
                            {formatRelativeTime(approval.created_at, t) ?? "—"}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <DialogFooter className="flex-none border-t border-border px-4 py-2.5">
              <DialogClose asChild>
                <Button variant="outline" size="sm" data-testid="rail-notifications-close">
                  {t("rail.bell.close")}
                </Button>
              </DialogClose>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 最底部：头像（点击开用户菜单）在下。 */}
        <UserMenu />
      </nav>
    </TooltipProvider>
  );
}
