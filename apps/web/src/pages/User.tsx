import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  Bot,
  Cpu,
  FolderKanban,
  Layers,
  ListChecks,
  Pin,
  PinOff,
  Rocket,
  UserRound,
  Workflow,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { PageContainer } from "@/components/layout/PageContainer";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDevices } from "@/hooks/useAuth";
import { useTranslation } from "@/i18n";
import { formatRelativeTime } from "@/lib/agentDisplay";
import { pageWindow } from "@/lib/pagination";
import { cn } from "@/lib/cn";
import { hasShellAction, invokeShellAction } from "@/lib/shellAction";
import { authService } from "@/services/auth";
import { useAuthStore } from "@/stores/authStore";
import { useUiStore } from "@/stores/uiStore";
import type { DeviceResponse } from "@/types";

/** 工作台快捷入口（补 WS-L 记录的入口缺口：models/tools/projects/workspace 等）。 */
interface WorkbenchEntry {
  /** 普通入口的目标路由（动作入口可省略）。 */
  to?: string;
  /** 动作入口标识（B-09：模型 → 设置·模型列表，不再跳 `/models`）。 */
  action?: "open-models-settings";
  /** 入口名称 i18n key（`workbench.entry.<key>.label`）。 */
  labelKey: string;
  /** 入口描述 i18n key（`workbench.entry.<key>.description`）。 */
  descriptionKey: string;
  icon: LucideIcon;
  /**
   * 关联的左侧栏模块 key（V0.4.6 · B-25）：
   * 路由型可选模块 → 卡片右上角渲染**图钉**（上栏 / 下栏）；
   * 固定项（`agents`）→ 渲染只读「固定」徽标；`models`（动作入口）无关联。
   */
  railKey?: string;
  /** 该模块在左侧栏**恒为固定项**（不可关闭）→ 渲染只读徽标而非图钉。 */
  railFixed?: boolean;
}

const WORKBENCH_ENTRIES: readonly WorkbenchEntry[] = [
  {
    to: "/workspace",
    labelKey: "workbench.entry.workspace.label",
    descriptionKey: "workbench.entry.workspace.description",
    // B-25 修：与左侧栏一致，改用 `Layers`（原 `LayoutGrid` 与工作台图标雷同）。
    icon: Layers,
    railKey: "workspace",
  },
  {
    to: "/agents",
    labelKey: "workbench.entry.agents.label",
    descriptionKey: "workbench.entry.agents.description",
    icon: Bot,
    railKey: "agents",
    railFixed: true,
  },
  {
    action: "open-models-settings",
    labelKey: "workbench.entry.models.label",
    descriptionKey: "workbench.entry.models.description",
    icon: Cpu,
  },
  {
    to: "/tools",
    labelKey: "workbench.entry.tools.label",
    descriptionKey: "workbench.entry.tools.description",
    icon: Wrench,
    railKey: "tools",
  },
  {
    to: "/projects",
    labelKey: "workbench.entry.projects.label",
    descriptionKey: "workbench.entry.projects.description",
    icon: FolderKanban,
    railKey: "projects",
  },
  {
    to: "/tasks",
    labelKey: "workbench.entry.tasks.label",
    descriptionKey: "workbench.entry.tasks.description",
    icon: ListChecks,
    railKey: "tasks",
  },
  {
    // 审批中心（`/approvals`）—— 与「任务中心」同为**待办**语义，故紧随其后；
    // 默认不上栏（不在 `uiStore.DEFAULT_RAIL_MODULES`），图钉可显式上栏。
    to: "/approvals",
    labelKey: "workbench.entry.approvals.label",
    descriptionKey: "workbench.entry.approvals.description",
    icon: BadgeCheck,
    railKey: "approvals",
  },
  {
    to: "/studio/workflows",
    labelKey: "workbench.entry.workflows.label",
    descriptionKey: "workbench.entry.workflows.description",
    icon: Workflow,
    railKey: "workflows",
  },
  {
    to: "/remote-tasks",
    labelKey: "workbench.entry.remoteTasks.label",
    descriptionKey: "workbench.entry.remoteTasks.description",
    icon: Rocket,
    railKey: "remote-tasks",
  },
];

/** 设备会话状态筛选档（`all` / `active` / `revoked`；活跃 = `revoked_at == null`）。 */
type DeviceStatusFilter = "all" | "active" | "revoked";

/** 设备状态分段定义（顺序冻结：全部 / 活跃 / 已撤销）。 */
const DEVICE_FILTERS: readonly DeviceStatusFilter[] = ["all", "active", "revoked"];

/** 前端分页档（后端无分页参数，不新增接口；默认 10）。 */
const PAGE_SIZES: readonly number[] = [10, 20, 50];

/** 设备状态徽标配色（内联 span：活跃绿系 / 已撤销灰系，不改 `ui/badge`）。 */
const DEVICE_STATUS_CLASS: Readonly<Record<"active" | "revoked", string>> = {
  active: "border-[#C9DFD2] bg-[#F0F7F3] text-[#4A7C63]",
  revoked: "border-border bg-muted text-muted-foreground",
};

/** 设备列展示文案（`device` 优先 → `user_agent` 截断 40 字符 → `—`）。 */
function deviceLabel(device: DeviceResponse): string {
  const named = device.device?.trim();
  if (named) {
    return named;
  }
  const ua = device.user_agent?.trim();
  if (ua) {
    return ua.length > 40 ? `${ua.slice(0, 40)}` : ua;
  }
  return "—";
}

/** 设备列悬浮全文（`device` 优先 → `user_agent` 全文 → 空串）。 */
function deviceFullLabel(device: DeviceResponse): string {
  return device.device?.trim() || device.user_agent?.trim() || "";
}

/**
 * 工作台页（路由 `/workbench`；D-UI 体验优化波 · WS-P1 / #3；默认档）。
 *
 * - **B-02（V0.4.6 BugFix）**：本页自**根路径 `/`** 迁至 `/workbench`。
 * - **B-17（V0.4.6）**：「本人信息」卡整卡移除（收口到 设置·个人）；页头补副标题与
 *   「个人设置」次级入口（壳内 `open-settings profile` / 纯 Web 就地弹窗，与 models
 *   弹窗为两个独立受控 state）；设备会话补状态分段（计数按全量）+ 前端分页 +
 *   `user_agent` 兜底 + 登录时间相对化（`formatRelativeTime`，>30 天显示日期）。
 * - 「退出全部」（`logoutAll`）逻辑不动。
 */
export function User() {
  const { t } = useTranslation();
  const { data: devices, isLoading: devicesLoading } = useDevices();
  const clearSession = useAuthStore((state) => state.clearSession);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  // B-09：模型入口改为打开「设置·模型」列表（不再跳 /models）。
  const [settingsOpen, setSettingsOpen] = useState(false);
  // B-17：「个人设置」入口 → 设置·个人（与 models 弹窗并存，各一个受控 state）。
  const [profileOpen, setProfileOpen] = useState(false);
  // B-17：设备会话状态筛选 + 前端分页（筛选 / pageSize 变化均回到第 1 页）。
  const [statusFilter, setStatusFilter] = useState<DeviceStatusFilter>("all");
  const [pageSize, setPageSize] = useState<number>(10);
  const [page, setPage] = useState<number>(1);
  // B-25：左侧栏可选模块（图钉与「左侧栏模块」开关共用同一份 store 状态）。
  const railModules = useUiStore((state) => state.railModules);
  const toggleRailModule = useUiStore((state) => state.toggleRailModule);

  /** 打开设置·模型：壳内开独立设置窗；纯 Web 就地打开设置弹窗并定位到模型分区。 */
  const openModelsSettings = (): void => {
    if (hasShellAction()) {
      invokeShellAction({ action: "open-settings", section: "models" });
      return;
    }
    setSettingsOpen(true);
  };

  /** 打开设置·个人：壳内开独立设置窗；纯 Web 就地打开设置弹窗并定位到个人分区。 */
  const openProfileSettings = (): void => {
    if (hasShellAction()) {
      invokeShellAction({ action: "open-settings", section: "profile" });
      return;
    }
    setProfileOpen(true);
  };

  const logoutAll = useMutation({
    mutationFn: () => authService.logoutAll(),
    onSettled: () => {
      clearSession();
      queryClient.clear();
      navigate("/login");
    },
  });

  const deviceList = devices ?? [];
  const activeCount = deviceList.filter((device) => !device.revoked_at).length;
  const revokedCount = deviceList.length - activeCount;
  const filteredDevices =
    statusFilter === "all"
      ? deviceList
      : deviceList.filter((device) =>
          statusFilter === "active" ? !device.revoked_at : Boolean(device.revoked_at),
        );
  const totalPages = Math.max(1, Math.ceil(filteredDevices.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageDevices = filteredDevices.slice((safePage - 1) * pageSize, safePage * pageSize);

  /** 切换状态分段（回到第 1 页）。 */
  const changeFilter = (next: DeviceStatusFilter): void => {
    setStatusFilter(next);
    setPage(1);
  };

  /** 切换每页条数（回到第 1 页）。 */
  const changePageSize = (next: number): void => {
    setPageSize(next);
    setPage(1);
  };

  return (
    <PageContainer width="default">
      <div className="space-y-6">
        {/* 页头：标题 + 副标题 + 右侧「个人设置」次级入口（B-17 补偿本人信息卡移除）。 */}
        <section className="space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <h1 className="text-lg font-semibold text-foreground">{t("workbench.title")}</h1>
              <p className="text-sm text-muted-foreground">{t("workbench.subtitle")}</p>
              {/* B-25：副标题补一句图钉图例（说明图钉 = 固定到左侧栏、显示在工作台之上）。 */}
              <p
                data-testid="workbench-subtitle-rail-hint"
                className="text-xs text-muted-foreground"
              >
                {t("workbench.subtitleRailHint")}
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              data-testid="workbench-open-profile"
              onClick={openProfileSettings}
            >
              <UserRound aria-hidden className="h-3.5 w-3.5" />
              {t("workbench.action.openProfile")}
            </Button>
          </div>
          {/* P2-1：卡片总数 9（含审批中心）→ `lg` 用 **3 列**（3×3 满格，无异形孤卡）。
              4 列时 9 项会落成 4+4+1（尾行 1 张 + 右侧 3/4 空白），且容器 `default` 档
              1152px 减去内边距与 gap 后单卡仅约 271px，英文描述（如 "Pending approvals and
              decisions"）已贴到 `truncate` 临界；3 列单卡约 365px，描述**显著缓解**
              （内容区 1152px 时文本区约 285px；但 1024–1200px 视口下仍可能截，非绝对保证）。
              `grid-cols-1` / `sm:grid-cols-2` 不动（sm 两列下 9 为奇数，尾行 1 张属固有，
              两列更窄的断点用 3 列会挤压卡片，故不处理）。 */}
          <div
            className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
            data-testid="workbench-entries"
          >
            {WORKBENCH_ENTRIES.map((entry) => {
              const testId = entry.action
                ? `workbench-entry-${entry.action}`
                : `workbench-entry-${(entry.to ?? "").replace(/\//g, "-")}`;
              const content = (
                <>
                  <span className="flex h-9 w-9 flex-none items-center justify-center rounded-lg bg-primary text-primary-foreground">
                    <entry.icon className="h-[18px] w-[18px]" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-foreground">
                      {t(entry.labelKey)}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {t(entry.descriptionKey)}
                    </span>
                  </span>
                </>
              );
              const itemClass =
                "group flex h-full w-full items-start gap-3 rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-accent hover:bg-accent/5";

              // B-09：「模型」为动作入口（打开设置·模型）；其余仍为路由入口。
              const card =
                entry.action === "open-models-settings" ? (
                  <button
                    type="button"
                    data-testid={testId}
                    onClick={openModelsSettings}
                    className={itemClass}
                  >
                    {content}
                  </button>
                ) : (
                  <Link to={entry.to as string} data-testid={testId} className={itemClass}>
                    {content}
                  </Link>
                );

              // B-25：右上角角标 —— 固定项只读「固定」徽标；路由型可选模块可切换图钉；
              // models（动作入口）无角标。角标是卡片 Link 的**兄弟节点**（绝对定位，
              // 不嵌在 <a> 内，避免 button-in-anchor 的非法结构）。
              const pinned = entry.railKey !== undefined && railModules.includes(entry.railKey);
              let corner: ReactNode = null;
              if (entry.railKey !== undefined && entry.railFixed === true) {
                corner = (
                  <span
                    data-testid={`workbench-fixed-${entry.railKey}`}
                    className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md border border-[#EFE0BC] bg-[#FDF8EC] px-1.5 py-0.5 text-[10px] font-medium leading-4 text-[#8A6322]"
                  >
                    <Pin aria-hidden className="h-2.5 w-2.5" />
                    {t("workbench.rail.fixed")}
                  </span>
                );
              } else if (entry.railKey !== undefined) {
                const railKey = entry.railKey;
                // 无障碍：aria-label 需带**模块名**，否则多个图钉按钮对读屏同名不可区分。
                const moduleName = t(entry.labelKey);
                const pinLabel = pinned
                  ? t("workbench.rail.unpinModule", { name: moduleName })
                  : t("workbench.rail.pinModule", { name: moduleName });
                corner = (
                  <button
                    type="button"
                    data-testid={`workbench-pin-${railKey}`}
                    aria-pressed={pinned}
                    aria-label={pinLabel}
                    title={pinned ? t("workbench.rail.unpin") : t("workbench.rail.pin")}
                    onClick={(event) => {
                      // 阻断卡片 Link 的默认跳转与冒泡（图钉只切左侧栏，不导航）。
                      event.preventDefault();
                      event.stopPropagation();
                      toggleRailModule(railKey);
                    }}
                    className={cn(
                      "absolute right-2 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-md border transition-colors",
                      pinned
                        ? "border-[#EFE0BC] bg-[#FDF8EC] text-[#8A6322]"
                        : "border-border text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {pinned ? (
                      <PinOff aria-hidden className="h-3.5 w-3.5" />
                    ) : (
                      <Pin aria-hidden className="h-3.5 w-3.5" />
                    )}
                  </button>
                );
              }

              return (
                <div key={entry.action ?? entry.to} className="relative">
                  {card}
                  {corner}
                </div>
              );
            })}
          </div>
        </section>

        {/* B-25：左侧栏模块的上下栏**唯一入口 = 模块卡右上角图钉**（不再重复一块开关卡）。 */}

        <Card>
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
            <CardTitle>{t("workbench.section.devices")}</CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              {/* 状态分段：role=tab + aria-selected；计数按**全量**（非当前筛选）。 */}
              <div
                className="flex items-center gap-1 rounded-lg bg-muted p-0.5"
                role="group"
                aria-label={t("workbench.devices.filterLabel")}
              >
                {DEVICE_FILTERS.map((key) => {
                  const count =
                    key === "all"
                      ? deviceList.length
                      : key === "active"
                        ? activeCount
                        : revokedCount;
                  const labelKey =
                    key === "all"
                      ? "workbench.devices.all"
                      : key === "active"
                        ? "workbench.devices.active"
                        : "workbench.devices.revoked";
                  return (
                    <button
                      key={key}
                      type="button"
                      role="tab"
                      aria-selected={statusFilter === key}
                      data-testid={`devices-status-${key}`}
                      onClick={() => changeFilter(key)}
                      className={cn(
                        "flex h-7 items-center rounded-md px-2.5 text-xs transition-colors",
                        statusFilter === key
                          ? "bg-background font-semibold text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {t(labelKey, { count })}
                    </button>
                  );
                })}
              </div>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => logoutAll.mutate()}
                disabled={logoutAll.isPending || deviceList.length === 0}
              >
                {t("workbench.action.logoutAll")}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {devicesLoading ? (
              <div className="space-y-2" data-testid="devices-skeleton">
                {Array.from({ length: 5 }).map((_, index) => (
                  <Skeleton key={index} className="h-9 w-full" />
                ))}
              </div>
            ) : deviceList.length === 0 ? (
              <EmptyState
                title={t("workbench.empty.devices.title")}
                description={t("workbench.empty.devices.description")}
                chips={[]}
              />
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("workbench.table.device")}</TableHead>
                      <TableHead>{t("workbench.table.ip")}</TableHead>
                      <TableHead>{t("workbench.table.createdAt")}</TableHead>
                      <TableHead>{t("workbench.table.status")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredDevices.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={4} className="py-8 text-center">
                          <p className="text-sm text-foreground">
                            {t("workbench.devices.noMatch")}
                          </p>
                          <Button
                            variant="outline"
                            size="sm"
                            data-testid="devices-clear-filters"
                            className="mt-2"
                            onClick={() => changeFilter("all")}
                          >
                            {t("workbench.devices.clearFilters")}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ) : (
                      pageDevices.map((device) => {
                        const active = !device.revoked_at;
                        return (
                          <TableRow key={device.id}>
                            <TableCell
                              className="max-w-[260px] truncate"
                              title={deviceFullLabel(device)}
                            >
                              {deviceLabel(device)}
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                              {device.ip_address ?? "—"}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {formatRelativeTime(device.created_at, t) ?? "—"}
                            </TableCell>
                            <TableCell>
                              <span
                                className={cn(
                                  "inline-flex whitespace-nowrap rounded-full border px-1.5 py-px text-[10px] font-medium leading-4",
                                  DEVICE_STATUS_CLASS[active ? "active" : "revoked"],
                                )}
                              >
                                {active
                                  ? t("workbench.status.active")
                                  : t("workbench.status.revoked")}
                              </span>
                            </TableCell>
                          </TableRow>
                        );
                      })
                    )}
                  </TableBody>
                </Table>

                {/* 前端分页条：summary + pageSize select + ‹ 页码 ›。 */}
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span data-testid="devices-page-summary">
                    {t("workbench.devices.pageSummary", {
                      count: filteredDevices.length,
                      page: safePage,
                      pages: totalPages,
                    })}
                  </span>
                  <div className="ml-auto flex items-center gap-1">
                    <select
                      data-testid="devices-page-size"
                      aria-label={t("workbench.devices.pageSizeLabel")}
                      value={pageSize}
                      onChange={(event) => changePageSize(Number(event.target.value))}
                      className="h-7 rounded-lg border border-input bg-background px-1.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {PAGE_SIZES.map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      data-testid="devices-prev"
                      aria-label={safePage - 1 >= 1 ? String(safePage - 1) : undefined}
                      disabled={safePage <= 1}
                      onClick={() => setPage(safePage - 1)}
                      className={cn(
                        "flex h-7 min-w-7 items-center justify-center rounded-md border border-border bg-background text-xs",
                        safePage <= 1
                          ? "opacity-50"
                          : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )}
                    >
                      ‹
                    </button>
                    {pageWindow(safePage, totalPages).map((entry, index) =>
                      entry === "ellipsis" ? (
                        // 省略号占位（不可点；窗口化断口）。
                        <span
                          key={`ellipsis-${index}`}
                          aria-hidden
                          className="flex h-7 min-w-4 items-center justify-center text-xs text-muted-foreground"
                        >
                          …
                        </span>
                      ) : (
                        <button
                          key={entry}
                          type="button"
                          data-testid={`devices-page-${entry}`}
                          aria-current={entry === safePage ? "page" : undefined}
                          onClick={() => setPage(entry)}
                          className={cn(
                            "flex h-7 min-w-7 items-center justify-center rounded-md border px-1.5 text-xs transition-colors",
                            entry === safePage
                              ? "border-primary bg-primary font-semibold text-primary-foreground"
                              : "border-border bg-background text-muted-foreground hover:bg-accent hover:text-foreground",
                          )}
                        >
                          {entry}
                        </button>
                      ),
                    )}
                    <button
                      type="button"
                      data-testid="devices-next"
                      aria-label={safePage + 1 <= totalPages ? String(safePage + 1) : undefined}
                      disabled={safePage >= totalPages}
                      onClick={() => setPage(safePage + 1)}
                      className={cn(
                        "flex h-7 min-w-7 items-center justify-center rounded-md border border-border bg-background text-xs",
                        safePage >= totalPages
                          ? "opacity-50"
                          : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )}
                    >
                      ›
                    </button>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* B-09：「模型」入口 → 设置·模型列表（纯 Web 就地弹窗；壳内为独立设置窗）。 */}
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} initialSection="models" />
      {/* B-17：页头「个人设置」→ 设置·个人（与 models 弹窗并存）。 */}
      <SettingsDialog open={profileOpen} onOpenChange={setProfileOpen} initialSection="profile" />
    </PageContainer>
  );
}
