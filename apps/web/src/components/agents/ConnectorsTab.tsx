import { Network, Plug, Search, X } from "lucide-react";
import { useMemo, useState } from "react";

import { ConnectorCard } from "@/components/agents/ConnectorCard";
import { McpServersDialog } from "@/components/agents/McpServersDialog";
import {
  TabEmptyPanel,
  TabErrorPanel,
  TabHintBar,
  TabNoMatchPanel,
  TabSkeleton,
} from "@/components/agents/TabPanels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMcpServers } from "@/hooks/useMcp";
import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";
import type { MCPServerResponse } from "@/types";

/** 状态筛选档位（全部 / 已启用 / 未启用；已启用 = `status === "ACTIVE"`）。 */
type ConnectorStatusFilter = "all" | "enabled" | "disabled";

/** {@link ConnectorsTab} 属性。 */
export interface ConnectorsTabProps {
  /** 「MCP 服务管理」弹窗开合（**受控**：状态提升到 `Agents` 宿主，页头主按钮共用）。 */
  manageOpen: boolean;
  /** 开合回调。 */
  onManageOpenChange: (open: boolean) => void;
}

/**
 * 连接器 Tab（V0.4.6 B-15 · 三 Tab 统一改版；骨架对齐专家 Tab）。
 *
 * 结构：工具栏（全宽搜索 + 传输下拉 + 状态分段 + 自定义连接器）→「我的连接器」卡片网格
 * （尾部追加 MCP Hub 虚线展示卡）→ 底部说明条。四态与专家 Tab 同口径：6 卡骨架 / 错误面板 /
 * 真空态（CTA=MCP 服务管理）/ 筛选空。
 *
 * - 数据经 `useMcpServers`（**只读**）；连接器卡**只读**（无启停 / 删除 / 测试连接）；
 * - 搜索（`name + endpoint + command`）/ 传输 / 状态筛选**纯前端**；
 * - 「自定义连接器」无后端能力 → **disabled + title 提示**（不再是可点死按钮）。
 *
 * `data-testid`：`agents-search-connectors` / `agents-connectors-search-clear` /
 * `agents-connectors-transport-filter` / `agents-connector-status-<all|enabled|disabled>` /
 * `agents-connectors-add-custom`（disabled）/ `agents-connector-card-<id>`（沿用）/
 * `agents-connectors-hub-card` / `agents-connectors-empty`（沿用）/ `agents-connectors-empty-create` /
 * `agents-connectors-no-match` / `agents-connectors-clear-filters` / `agents-connectors-error` /
 * `agents-connectors-retry` / `agents-connectors-manage-mcp`（**移至宿主页头**）/ `agents-mcp-*`（弹窗沿用）。
 */
export function ConnectorsTab({ manageOpen, onManageOpenChange }: ConnectorsTabProps) {
  const { t } = useTranslation();
  const { data, isLoading, isError, error, refetch } = useMcpServers();
  const [query, setQuery] = useState("");
  const [transportFilter, setTransportFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<ConnectorStatusFilter>("all");

  /** 全量列表（未筛选；用于状态分段计数与真空态判定）。 */
  const connectors = useMemo<MCPServerResponse[]>(() => data ?? [], [data]);

  /** 传输选项（数据 `transport` 去重，原样显示）。 */
  const transports = useMemo(() => {
    const set = new Set<string>();
    for (const connector of connectors) {
      set.add(connector.transport);
    }
    return [...set].sort((left, right) => left.localeCompare(right));
  }, [connectors]);

  /** 状态计数（按**未经筛选的全量**算）。 */
  const counts = useMemo(
    () => ({
      all: connectors.length,
      enabled: connectors.filter((connector) => connector.status === "ACTIVE").length,
      disabled: connectors.filter((connector) => connector.status !== "ACTIVE").length,
    }),
    [connectors],
  );

  /** 搜索 + 传输 + 状态筛选（纯前端）。 */
  const filtered = useMemo<MCPServerResponse[]>(() => {
    const keyword = query.trim().toLowerCase();
    let list = connectors;

    if (keyword) {
      list = list.filter(
        (connector) =>
          connector.name.toLowerCase().includes(keyword) ||
          (connector.endpoint ?? "").toLowerCase().includes(keyword) ||
          (connector.command ?? "").toLowerCase().includes(keyword),
      );
    }
    if (transportFilter !== "all") {
      list = list.filter((connector) => connector.transport === transportFilter);
    }
    if (statusFilter === "enabled") {
      list = list.filter((connector) => connector.status === "ACTIVE");
    } else if (statusFilter === "disabled") {
      list = list.filter((connector) => connector.status !== "ACTIVE");
    }
    return list;
  }, [connectors, query, transportFilter, statusFilter]);

  /** 重置全部筛选。 */
  const clearFilters = (): void => {
    setQuery("");
    setTransportFilter("all");
    setStatusFilter("all");
  };

  /** 状态分段定义（顺序冻结：全部 / 已启用 / 未启用）。 */
  const statusOptions: readonly {
    value: ConnectorStatusFilter;
    labelKey: string;
    count: number;
  }[] = [
    { value: "all", labelKey: "agents.connectors.statusAll", count: counts.all },
    { value: "enabled", labelKey: "agents.connectors.statusEnabled", count: counts.enabled },
    { value: "disabled", labelKey: "agents.connectors.statusDisabled", count: counts.disabled },
  ];

  const isEmpty = !isLoading && !isError && connectors.length === 0;
  const isNoMatch = !isLoading && !isError && connectors.length > 0 && filtered.length === 0;
  /** 工具栏仅在「有数据可筛」时渲染（同专家口径）。 */
  const showToolbar = !isLoading && !isError && connectors.length > 0;

  return (
    <div className="space-y-3">
      {/* ===== 工具栏 ===== */}
      {showToolbar ? (
        <div className="flex flex-wrap items-center gap-2" data-testid="agents-connectors-toolbar">
          {/* 全宽搜索：匹配 name + endpoint + command */}
          <div className="relative min-w-[300px] flex-1">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              data-testid="agents-search-connectors"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("agents.search.connectors")}
              aria-label={t("agents.search.connectors")}
              className="h-8 pl-8 pr-8 text-xs"
            />
            {query ? (
              <button
                type="button"
                data-testid="agents-connectors-search-clear"
                aria-label={t("agents.search.clear")}
                onClick={() => setQuery("")}
                className="absolute right-2 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X aria-hidden className="h-3 w-3" />
              </button>
            ) : null}
          </div>

          {/* 传输下拉（真实字段 transport，选项随数据去重） */}
          <select
            data-testid="agents-connectors-transport-filter"
            aria-label={t("agents.connectors.transportFilter")}
            value={transportFilter}
            onChange={(event) => setTransportFilter(event.target.value)}
            className="h-8 rounded-lg border border-input bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="all">{t("agents.connectors.transportAll")}</option>
            {transports.map((transport) => (
              <option key={transport} value={transport}>
                {transport}
              </option>
            ))}
          </select>

          {/* 状态分段（真实字段 status） */}
          <div
            role="tablist"
            aria-label={t("agents.connectors.statusFilterLabel")}
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
                  data-testid={`agents-connector-status-${option.value}`}
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

          {/* 右侧：自定义连接器（无后端能力 → disabled + title 提示） */}
          <div className="ml-auto">
            <Button
              type="button"
              size="sm"
              variant="outline"
              data-testid="agents-connectors-add-custom"
              disabled
              title={t("agents.connectors.addCustomPending")}
              className="h-8 px-2.5 text-xs"
            >
              <Plug aria-hidden className="h-3.5 w-3.5" />
              {t("agents.connectors.addCustom")}
            </Button>
          </div>
        </div>
      ) : null}

      {/* ===== 载入 / 错误 / 真空态 ===== */}
      {isLoading ? (
        <TabSkeleton testId="agents-connectors-loading" height={132} />
      ) : isError ? (
        <TabErrorPanel
          testId="agents-connectors-error"
          retryTestId="agents-connectors-retry"
          error={error}
          onRetry={() => {
            void refetch();
          }}
        />
      ) : isEmpty ? (
        <TabEmptyPanel
          testId="agents-connectors-empty"
          icon={<Network aria-hidden className="h-5 w-5" />}
          title={t("agents.connectors.emptyTitle")}
          description={t("agents.subtitleConnectors")}
          ctaLabel={t("agents.mcp.title")}
          ctaTestId="agents-connectors-empty-create"
          onCta={() => onManageOpenChange(true)}
        />
      ) : isNoMatch ? (
        <TabNoMatchPanel
          testId="agents-connectors-no-match"
          message={t("agents.connectors.noMatch")}
          clearTestId="agents-connectors-clear-filters"
          onClear={clearFilters}
        />
      ) : (
        <>
          {/* ===== 分区头 ===== */}
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-foreground">
              {t("agents.connectors.myConnectors")}
            </h2>
            <span className="text-[11px] text-muted-foreground">
              {t("agents.connectors.summary", {
                count: filtered.length,
                enabled: filtered.filter((connector) => connector.status === "ACTIVE").length,
              })}
            </span>
          </div>

          {/* ===== 卡片网格（尾部追加 MCP Hub 虚线展示卡） ===== */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((connector) => (
              <ConnectorCard key={connector.id} connector={connector} />
            ))}

            <div
              data-testid="agents-connectors-hub-card"
              className="flex min-h-[132px] cursor-default flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-input bg-muted/20 px-4 py-5 text-center text-muted-foreground"
            >
              <span className="mb-0.5 flex h-7 w-7 items-center justify-center rounded-[9px] border border-dashed border-current">
                <Plug aria-hidden className="h-3.5 w-3.5" />
              </span>
              <b className="text-xs font-medium text-foreground">
                {t("agents.connectors.hubCardTitle")}
              </b>
              <span className="text-[11px]">{t("agents.connectors.hubCardDesc")}</span>
            </div>
          </div>

          {/* ===== 底部说明条 ===== */}
          <TabHintBar text={t("agents.connectors.hint")} />
        </>
      )}

      {/* ===== MCP 服务管理弹窗（受控：宿主页头主按钮 / 空态 CTA 均可打开） ===== */}
      <McpServersDialog open={manageOpen} onOpenChange={onManageOpenChange} />
    </div>
  );
}
