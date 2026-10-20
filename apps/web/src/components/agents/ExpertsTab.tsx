import { LayoutGrid, List, Plus, Search, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AgentStatusBadge, ExpertCard } from "@/components/agents/ExpertCard";
import { TabErrorPanel, TabHintBar, TabSkeleton } from "@/components/agents/TabPanels";
import { Input } from "@/components/ui/input";
import { useAgents } from "@/hooks/useAgents";
import { useTranslation } from "@/i18n";
import {
  AGENT_TYPE_OPTIONS,
  agentDisplayStatus,
  agentStatusLabel,
  agentTypeLabel,
  formatAgentUpdatedAt,
  sortAgents,
  type AgentSortMode,
} from "@/lib/agentDisplay";
import { cn } from "@/lib/cn";
import type { AgentResponse } from "@/types";

/** 状态筛选档位（全部 / 已发布 / 草稿；已归档仅出现在「全部」）。 */
type StatusFilter = "all" | "published" | "draft";

/** 视图模式。 */
type ViewMode = "grid" | "list";

/** 「新建专家」虚线卡 testid。 */
const NEW_CARD_TESTID = "agents-new-card";

/** {@link ExpertsTab} 属性。 */
export interface ExpertsTabProps {
  /** 创建入口（页头主按钮 / 空态 CTA / 虚线卡共用）。 */
  onCreate?: () => void;
}

/**
 * 专家 Tab（V0.4.6 · D-UI 优化波 · D1–D6 重写）。
 *
 * 结构：工具栏（搜索 / 状态分段 / 类型下拉 / 排序 / 视图切换）→ 分区头 → 卡片网格或列表
 * → 底部能力说明。**只保留真实字段驱动的控件**（`status` / `type` / `name` / `description` /
 * `updated_at`），无「专家 · 专家团」分段、无分类 chips、无版本号列。
 *
 * 四种非正常态：加载（6 张骨架卡）/ 接口错误（`isError` 优先于空态，可重试）/ 真空态（三步 +
 * 主 CTA）/ 筛选后为空（清除筛选）。
 *
 * `data-testid`：`agents-search-experts` / `agents-search-clear` / `agents-status-<all|published|draft>`
 * / `agents-type-filter` / `agents-sort` / `agents-view-<grid|list>` / `agents-my-experts` /
 * `agents-experts-grid` / `agents-experts-list` / `agent-card-<id>` / `agents-new-card` /
 * `agents-experts-empty` / `agents-empty-create` / `agents-experts-no-match` /
 * `agents-clear-filters` / `agents-experts-error` / `agents-retry`。
 */
export function ExpertsTab({ onCreate }: ExpertsTabProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading, isError, error, refetch } = useAgents();

  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [sortMode, setSortMode] = useState<AgentSortMode>("updated");
  const [view, setView] = useState<ViewMode>("grid");

  /** 全量列表（未筛选；用于状态分段计数与「真空态」判定）。 */
  const agents = useMemo<AgentResponse[]>(() => data ?? [], [data]);

  /** 状态计数（按**未经筛选的全量**算）。 */
  const counts = useMemo(
    () => ({
      all: agents.length,
      published: agents.filter((agent) => agent.status === "ACTIVE").length,
      draft: agents.filter((agent) => agent.status === "DRAFT").length,
    }),
    [agents],
  );

  /** 搜索 + 状态 + 类型 + 排序（全部纯前端）。 */
  const visibleAgents = useMemo<AgentResponse[]>(() => {
    const keyword = query.trim().toLowerCase();
    let list = agents;

    if (keyword) {
      list = list.filter(
        (agent) =>
          agent.name.toLowerCase().includes(keyword) ||
          (agent.description ?? "").toLowerCase().includes(keyword),
      );
    }
    if (statusFilter === "published") {
      list = list.filter((agent) => agent.status === "ACTIVE");
    } else if (statusFilter === "draft") {
      list = list.filter((agent) => agent.status === "DRAFT");
    }
    if (typeFilter !== "all") {
      list = list.filter((agent) => agent.type === typeFilter);
    }
    return sortAgents(list, sortMode);
  }, [agents, query, statusFilter, typeFilter, sortMode]);

  /** 当前筛选结果中的待发布数（分区头小结用）。 */
  const draftCount = useMemo(
    () => visibleAgents.filter((agent) => agent.status === "DRAFT").length,
    [visibleAgents],
  );

  /** 是否有任何筛选条件（决定「清除筛选」是否出现）。 */
  const hasFilters = query.trim().length > 0 || statusFilter !== "all" || typeFilter !== "all";

  /** 重置全部筛选（不动排序与视图）。 */
  const clearFilters = (): void => {
    setQuery("");
    setStatusFilter("all");
    setTypeFilter("all");
  };

  /** 状态分段定义（顺序冻结：全部 / 已发布 / 草稿）。 */
  const statusOptions: readonly { value: StatusFilter; labelKey: string; count: number }[] = [
    { value: "all", labelKey: "agents.status.all", count: counts.all },
    { value: "published", labelKey: "agents.status.published", count: counts.published },
    { value: "draft", labelKey: "agents.status.draft", count: counts.draft },
  ];

  const isEmpty = !isLoading && !isError && agents.length === 0;
  const isNoMatch = !isLoading && !isError && agents.length > 0 && visibleAgents.length === 0;
  /** 工具栏仅在「有数据可筛」时出现：加载 / 错误 / 真空态不展示假 0 计数与无效筛选。 */
  const showToolbar = !isLoading && !isError && agents.length > 0;

  return (
    <div className="space-y-3">
      {/* ===== 工具栏（专家 Tab 专属） ===== */}
      {showToolbar ? (
        <div className="flex flex-wrap items-center gap-2" data-testid="agents-experts-toolbar">
          {/* 搜索：匹配 name + description（大小写不敏感） */}
          <div className="relative w-[340px] max-w-full">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              data-testid="agents-search-experts"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("agents.search.experts")}
              aria-label={t("agents.search.experts")}
              className="h-8 pl-8 pr-8 text-xs"
            />
            {query ? (
              <button
                type="button"
                data-testid="agents-search-clear"
                aria-label={t("agents.search.clear")}
                onClick={() => setQuery("")}
                className="absolute right-2 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X aria-hidden className="h-3 w-3" />
              </button>
            ) : null}
          </div>

          {/* 状态分段（真实字段 status） */}
          <div
            role="tablist"
            aria-label={t("agents.status.filterLabel")}
            className="inline-flex h-8 items-center gap-0.5 rounded-lg bg-muted p-0.5"
          >
            {statusOptions.map((option) => {
              const active = statusFilter === option.value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  data-testid={`agents-status-${option.value}`}
                  onClick={() => setStatusFilter(option.value)}
                  className={cn(
                    "flex h-7 items-center rounded-md px-2.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active
                      ? "bg-background font-semibold text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t(option.labelKey)}
                  <span className="ml-1.5 text-[10px] font-medium tabular-nums opacity-70">
                    {option.count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* 类型下拉（真实字段 type；原生 select 保证键盘与 jsdom 可用） */}
          <select
            data-testid="agents-type-filter"
            aria-label={t("agents.type.label")}
            value={typeFilter}
            onChange={(event) => setTypeFilter(event.target.value)}
            className="h-8 rounded-lg border border-input bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="all">{t("agents.type.all")}</option>
            {AGENT_TYPE_OPTIONS.map((type) => (
              <option key={type} value={type}>
                {agentTypeLabel(type, t)}
              </option>
            ))}
          </select>

          {/* 右侧：排序 + 视图切换 */}
          <div className="ml-auto flex items-center gap-2">
            <select
              data-testid="agents-sort"
              aria-label={t("agents.sort.label")}
              value={sortMode}
              onChange={(event) => setSortMode(event.target.value === "name" ? "name" : "updated")}
              className="h-8 rounded-lg border border-input bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="updated">{t("agents.sort.updated")}</option>
              <option value="name">{t("agents.sort.name")}</option>
            </select>

            <div
              role="group"
              aria-label={t("agents.view.label")}
              className="inline-flex h-8 items-center overflow-hidden rounded-lg border border-input"
            >
              <button
                type="button"
                data-testid="agents-view-grid"
                aria-label={t("agents.view.grid")}
                aria-pressed={view === "grid"}
                onClick={() => setView("grid")}
                className={cn(
                  "flex h-full w-8 items-center justify-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  view === "grid"
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <LayoutGrid aria-hidden className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                data-testid="agents-view-list"
                aria-label={t("agents.view.list")}
                aria-pressed={view === "list"}
                onClick={() => setView("list")}
                className={cn(
                  "flex h-full w-8 items-center justify-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  view === "list"
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <List aria-hidden className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* ===== 加载 / 错误 / 真空态 ===== */}
      {isLoading ? (
        <TabSkeleton testId="agents-experts-loading" height={156} />
      ) : isError ? (
        <TabErrorPanel
          testId="agents-experts-error"
          retryTestId="agents-retry"
          error={error}
          onRetry={() => {
            void refetch();
          }}
        />
      ) : isEmpty ? (
        <div className="flex items-center justify-center px-2 py-8">
          <div
            className="w-full max-w-[560px] rounded-2xl border border-dashed border-border bg-card px-7 py-6 text-center"
            data-testid="agents-experts-empty"
          >
            <span className="mx-auto mb-2.5 flex h-11 w-11 items-center justify-center rounded-xl bg-muted text-primary">
              <Sparkles aria-hidden className="h-5 w-5" />
            </span>
            <h2 className="text-sm font-semibold text-foreground">
              {t("agents.experts.emptyTitle")}
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {t("agents.experts.emptyDesc")}
            </p>
            <div className="my-3.5 grid grid-cols-1 gap-2 text-left sm:grid-cols-3">
              {(["1", "2", "3"] as const).map((step) => (
                <div key={step} className="rounded-lg border border-border bg-muted/40 px-2.5 py-2">
                  <em className="block text-[10px] font-bold not-italic tracking-wider text-primary">
                    STEP 0{step}
                  </em>
                  <b className="mt-px block text-xs font-semibold text-foreground">
                    {t(`agents.experts.emptyStep${step}`)}
                  </b>
                  <span className="mt-px block text-[11px] leading-relaxed text-muted-foreground">
                    {t(`agents.experts.emptyStep${step}Desc`)}
                  </span>
                </div>
              ))}
            </div>
            <button
              type="button"
              data-testid="agents-empty-create"
              onClick={onCreate}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Plus aria-hidden className="h-3.5 w-3.5" />
              {t("agents.experts.emptyCta")}
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* ===== 分区头 ===== */}
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-foreground" data-testid="agents-my-experts">
              {t("agents.experts.myExperts")}
            </h2>
            <span className="text-[11px] text-muted-foreground">
              {draftCount > 0
                ? t("agents.experts.summaryWithDraft", {
                    count: visibleAgents.length,
                    draftCount,
                  })
                : t("agents.experts.summary", { count: visibleAgents.length })}
            </span>
          </div>

          {/* ===== 筛选后为空 ===== */}
          {isNoMatch ? (
            <div
              className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border bg-card px-6 py-10 text-center"
              data-testid="agents-experts-no-match"
            >
              <p className="text-sm text-foreground">{t("agents.experts.noMatch")}</p>
              {hasFilters ? (
                <button
                  type="button"
                  data-testid="agents-clear-filters"
                  onClick={clearFilters}
                  className="h-8 rounded-lg border border-input bg-background px-3 text-xs text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("agents.experts.clearFilters")}
                </button>
              ) : null}
            </div>
          ) : view === "grid" ? (
            /* ===== 卡片视图 ===== */
            <div
              className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
              data-testid="agents-experts-grid"
            >
              {visibleAgents.map((agent) => (
                <ExpertCard key={agent.id} agent={agent} />
              ))}

              {/* 新建专家虚线卡（点击 = 创建向导） */}
              <button
                type="button"
                data-testid={NEW_CARD_TESTID}
                onClick={onCreate}
                className="flex min-h-[156px] flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-input bg-muted/20 text-muted-foreground transition-colors hover:border-primary/40 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="mb-0.5 flex h-7 w-7 items-center justify-center rounded-[9px] border border-dashed border-current">
                  <Plus aria-hidden className="h-3.5 w-3.5" />
                </span>
                <b className="text-xs font-medium text-foreground">{t("agents.experts.newCard")}</b>
                <span className="text-[11px] text-muted-foreground">
                  {t("agents.experts.newCardHint")}
                </span>
              </button>
            </div>
          ) : (
            /* ===== 列表视图（无版本号列：AgentResponse 无该字段） ===== */
            <div className="overflow-hidden rounded-xl border border-border bg-card">
              <table
                className="w-full border-collapse"
                data-testid="agents-experts-list"
                aria-label={t("agents.experts.myExperts")}
              >
                <thead>
                  <tr className="bg-muted/40 text-[11px] text-muted-foreground">
                    <th className="px-3 py-2 text-left font-medium">{t("agents.table.name")}</th>
                    <th className="w-[16%] px-3 py-2 text-left font-medium">
                      {t("agents.table.type")}
                    </th>
                    <th className="w-[14%] px-3 py-2 text-left font-medium">
                      {t("agents.table.status")}
                    </th>
                    <th className="w-[16%] px-3 py-2 text-left font-medium">
                      {t("agents.table.updated")}
                    </th>
                    <th className="w-[14%] px-3 py-2 text-right font-medium">
                      {t("agents.table.actions")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleAgents.map((agent) => {
                    const display = agentDisplayStatus(agent.status);
                    const updatedAt = formatAgentUpdatedAt(agent, t);
                    return (
                      <tr
                        key={agent.id}
                        data-testid={`agent-row-${agent.id}`}
                        tabIndex={0}
                        onClick={() => navigate(`/agents/${agent.id}`)}
                        onKeyDown={(event) => {
                          // 键盘冲突守卫：焦点在行内操作按钮时，Enter 归按钮，行不抢。
                          if (event.target !== event.currentTarget) {
                            return;
                          }
                          if (event.key === "Enter") {
                            navigate(`/agents/${agent.id}`);
                          }
                        }}
                        className="cursor-pointer border-t border-border transition-colors hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                      >
                        <td className="px-3 py-2.5">
                          <div className="flex min-w-0 items-center gap-2">
                            <span
                              aria-hidden
                              className="flex h-7 w-7 flex-none items-center justify-center rounded-lg bg-primary text-[11px] text-primary-foreground"
                            >
                              {agent.name.slice(0, 1).toUpperCase()}
                            </span>
                            <div className="min-w-0">
                              <div className="truncate text-xs font-semibold text-foreground">
                                {agent.name}
                              </div>
                              <div className="truncate text-[11px] text-muted-foreground">
                                {agent.description?.trim()
                                  ? agent.description
                                  : t("agents.experts.noDescription")}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-2.5 text-xs text-foreground">
                          {agentTypeLabel(agent.type, t)}
                        </td>
                        <td className="px-3 py-2.5">
                          <AgentStatusBadge status={agent.status} />
                        </td>
                        <td className="px-3 py-2.5 text-xs text-muted-foreground">
                          {updatedAt ?? "—"}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          {display === "published" ? (
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                navigate(`/chat?agent=${agent.id}`);
                              }}
                              className="whitespace-nowrap rounded text-xs font-medium text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {t("agents.card.openChat")}
                            </button>
                          ) : display === "draft" ? (
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                navigate(`/agents/${agent.id}`);
                              }}
                              className="whitespace-nowrap rounded text-xs font-medium text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {t("agents.card.completePublish")}
                            </button>
                          ) : (
                            <span className="whitespace-nowrap text-xs text-muted-foreground">
                              {display === "archived"
                                ? t("agents.card.archivedOnly")
                                : agentStatusLabel(agent.status, t)}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* ===== 底部能力说明 ===== */}
          <TabHintBar text={t("agents.experts.hint")} />
        </>
      )}
    </div>
  );
}
