import { ScrollText } from "lucide-react";
import { useState } from "react";

import { InlineEmpty } from "@/components/common/InlineEmpty";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuditLogs } from "@/hooks/useAuditLogs";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import type { AuditLogResponse } from "@/types";

/** 每页条数（后端缺省 50、单次上限 200；此处取较小页长便于流水阅读）。 */
const PAGE_SIZE = 20;

/** 「SUCCESS」结果徽标样式（绿）。 */
const SUCCESS_TAG_CLASS =
  "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
/** 「FAILURE」结果徽标样式（红）。 */
const FAILURE_TAG_CLASS = "border-destructive/40 bg-destructive/10 text-destructive";
/** 其他结果（如 `PARTIAL` / `DENIED`）的**中性**徽标样式。 */
const NEUTRAL_TAG_CLASS = "border-border bg-muted text-muted-foreground";

/**
 * 把后端 ISO8601 时间戳压成 `YYYY-MM-DD HH:mm:ss`（**不依赖运行环境 locale**，
 * 保证单测断言稳定）；缺失 → 「—」。
 */
function formatTimestamp(value: string | null): string {
  if (value === null || value === "") {
    return "—";
  }
  return value.replace("T", " ").replace(/\.\d+/, "").slice(0, 19);
}

/** 组装资源列（`resource_type · resource_id`；两者皆空 → 「—」）。 */
function formatResource(record: AuditLogResponse): string {
  const parts = [record.resource_type, record.resource_id].filter(
    (part): part is string => part !== null && part !== "",
  );
  return parts.length === 0 ? "—" : parts.join(" · ");
}

/**
 * 设置 · 系统分区内的「审计」区块（V0.4.6 收口 · M07-01 第 12 条）。
 *
 * **只读流水**（时间 / 主体 / 动作 / 资源 / 结果），数据源 `GET /audit`（只需登录）。
 *
 * ✅ **后端已修复（V0.4.6 缺陷 L-1）**：过滤与分页**整体下推**到仓储
 *    （`routers/v1/audit.py` → `AuditRepository.list_page`，SQL `WHERE` + `LIMIT` / `OFFSET`），
 *    `offset` 只消费一次，命中的中间页记录**可达**，过滤条件作用于**全量**记录。
 *    （修复前为「按 `limit = offset + limit` 拉取 → 内存过滤 → `[offset : offset + limit]`
 *    切片」，`offset` 被消费两次，窗口外命中记录永久不可达。）
 * 🔴 **错误态区分 401 / 403**：401 = 登录失效（后端会先尝试刷新 token）；403 = 无权限。
 * 🔴 **分页选择**：采用「上一页 / 下一页」（`offset` 步进，每页 20 条），而非「加载更多」。
 *    选分页的理由是 `offset` 语义确定、页边界显式；**不是**因为加载更多会跳号
 *    （两种方式都只产出正确前缀，实测均不跳号、不重复、不乱序）。
 *
 * `data-testid`：`settings-audit` / `-note` / `-loading` / `-empty` / `-error` / `-table` /
 * `-row-<id>` / `-outcome-<id>` / `-filter-action` / `-filter-user` / `-filter-apply` /
 * `-filter-reset` / `-prev` / `-next` / `-page`。
 */
export function AuditSection() {
  const { t } = useTranslation();

  const [actionInput, setActionInput] = useState("");
  const [userInput, setUserInput] = useState("");
  const [applied, setApplied] = useState<{ action: string; user_id: string }>({
    action: "",
    user_id: "",
  });
  const [page, setPage] = useState(0);

  const logs = useAuditLogs({
    action: applied.action,
    user_id: applied.user_id,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const items = logs.data ?? [];
  const error = logs.error === null ? null : toApiError(logs.error);
  const errorKey =
    error === null
      ? null
      : error.status === 401
        ? "settings.audit.error.unauthorized"
        : error.status === 403
          ? "settings.audit.error.forbidden"
          : "settings.audit.error.generic";

  /** 应用过滤条件（重置回第一页）。 */
  const applyFilter = (): void => {
    setApplied({ action: actionInput.trim(), user_id: userInput.trim() });
    setPage(0);
  };

  /** 清空过滤条件（重置回第一页）。 */
  const resetFilter = (): void => {
    setActionInput("");
    setUserInput("");
    setApplied({ action: "", user_id: "" });
    setPage(0);
  };

  return (
    <section
      aria-label={t("settings.audit.title")}
      data-testid="settings-audit"
      className="space-y-3 border-t border-border pt-5"
    >
      <div className="space-y-1">
        <h4 className="text-sm font-semibold text-foreground">{t("settings.audit.title")}</h4>
        {/* 数据范围提示：过滤 + 分页均为**全量**记录下的服务端条件（L-1 已修复窗口截断）。 */}
        <p
          data-testid="settings-audit-note"
          className="text-[11px] leading-[1.5] text-muted-foreground"
        >
          {t("settings.audit.note")}
        </p>
      </div>

      {/* 过滤条：只做后端支持的 `action` + `user_id` 两项（精确匹配）。 */}
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[140px] space-y-1">
          <label
            htmlFor="settings-audit-filter-action"
            className="text-[11px] text-muted-foreground"
          >
            {t("settings.audit.filter.action")}
          </label>
          <Input
            id="settings-audit-filter-action"
            data-testid="settings-audit-filter-action"
            value={actionInput}
            className="h-8 text-xs"
            autoComplete="off"
            onChange={(event) => setActionInput(event.target.value)}
          />
        </div>
        <div className="flex-1 min-w-[140px] space-y-1">
          <label htmlFor="settings-audit-filter-user" className="text-[11px] text-muted-foreground">
            {t("settings.audit.filter.user")}
          </label>
          <Input
            id="settings-audit-filter-user"
            data-testid="settings-audit-filter-user"
            value={userInput}
            className="h-8 text-xs"
            autoComplete="off"
            onChange={(event) => setUserInput(event.target.value)}
          />
        </div>
        <Button
          type="button"
          size="sm"
          data-testid="settings-audit-filter-apply"
          onClick={applyFilter}
        >
          {t("settings.audit.filter.apply")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          data-testid="settings-audit-filter-reset"
          onClick={resetFilter}
        >
          {t("settings.audit.filter.reset")}
        </Button>
      </div>

      {logs.isPending ? (
        <div data-testid="settings-audit-loading" className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : logs.isError ? (
        <div
          data-testid="settings-audit-error"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2.5"
        >
          <span className="text-xs text-destructive">
            {t(errorKey ?? "settings.audit.error.generic")}
            {error !== null && error.status !== 401 && error.status !== 403
              ? ` (${error.message})`
              : ""}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="settings-audit-retry"
            onClick={() => {
              void logs.refetch();
            }}
          >
            {t("common.retry")}
          </Button>
        </div>
      ) : items.length === 0 ? (
        <InlineEmpty
          icon={ScrollText}
          title={t("settings.audit.empty.title")}
          description={t("settings.audit.empty.description")}
          testId="settings-audit-empty"
        />
      ) : (
        <Table data-testid="settings-audit-table">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[140px]">{t("settings.audit.col.time")}</TableHead>
              <TableHead>{t("settings.audit.col.subject")}</TableHead>
              <TableHead>{t("settings.audit.col.action")}</TableHead>
              <TableHead>{t("settings.audit.col.resource")}</TableHead>
              <TableHead className="w-[92px]">{t("settings.audit.col.outcome")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((record) => {
              const isSuccess = record.outcome === "SUCCESS";
              const isFailure = record.outcome === "FAILURE";
              return (
                <TableRow key={record.id} data-testid={`settings-audit-row-${record.id}`}>
                  <TableCell className="whitespace-nowrap font-mono text-[11px] text-muted-foreground">
                    {formatTimestamp(record.created_at)}
                  </TableCell>
                  <TableCell className="text-xs">
                    {record.agent_id !== null && record.agent_id !== "" ? (
                      <span data-testid={`settings-audit-subject-${record.id}`}>
                        <span className="text-muted-foreground">
                          {t("settings.audit.subject.agent")} ·{" "}
                        </span>
                        <span className="font-mono text-foreground">{record.agent_id}</span>
                      </span>
                    ) : record.user_id !== null && record.user_id !== "" ? (
                      <span
                        data-testid={`settings-audit-subject-${record.id}`}
                        className="font-mono text-foreground"
                      >
                        {record.user_id}
                      </span>
                    ) : (
                      <span
                        data-testid={`settings-audit-subject-${record.id}`}
                        className="text-muted-foreground"
                      >
                        —
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-foreground">{record.action || "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatResource(record)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      data-testid={`settings-audit-outcome-${record.id}`}
                      variant="outline"
                      className={
                        isSuccess
                          ? SUCCESS_TAG_CLASS
                          : isFailure
                            ? FAILURE_TAG_CLASS
                            : NEUTRAL_TAG_CLASS
                      }
                    >
                      {record.outcome}
                    </Badge>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      {/* 分页：`offset` 步进（上一页 / 下一页）。 */}
      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          data-testid="settings-audit-prev"
          disabled={page === 0 || logs.isFetching}
          onClick={() => setPage((current) => Math.max(0, current - 1))}
        >
          {t("settings.audit.prev")}
        </Button>
        <span data-testid="settings-audit-page" className="text-[11px] text-muted-foreground">
          {t("settings.audit.page", { page: page + 1 })}
        </span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          data-testid="settings-audit-next"
          disabled={items.length < PAGE_SIZE || logs.isFetching}
          onClick={() => setPage((current) => current + 1)}
        >
          {t("settings.audit.next")}
        </Button>
      </div>
    </section>
  );
}
