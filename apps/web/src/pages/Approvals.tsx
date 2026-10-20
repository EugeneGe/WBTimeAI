import { AlertCircle, Check, Inbox, RefreshCw, X } from "lucide-react";
import { useState } from "react";

import { InlineEmpty } from "@/components/common/InlineEmpty";
import { PageContainer } from "@/components/layout/PageContainer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useApproval,
  useApprovals,
  useApproveApproval,
  useRejectApproval,
} from "@/hooks/useApprovals";
import { useTranslation } from "@/i18n";
import { formatRelativeTime, type TranslateFn } from "@/lib/agentDisplay";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { ApprovalResponse } from "@/types";

/**
 * Approvals（审批中心；W10 / T2-49 契约的前端接入）。
 *
 * 两列结构：
 * - **左列**（约 320px，{@link LIST_WIDTH_CLASS}）：待办列表（`GET /approvals`，**仅 `PENDING`**），
 *   每项展示主体类型中文名 + 请求人 + 相对时间 + 过期提示；选中项以**金色竖条**标记；
 * - **右列**：详情（`GET /approvals/{id}`）——请求人 / 提交时间 / 过期时间 / `payload` 折叠 JSON 预览
 *   + 「通过」「驳回」（**驳回二次确认**）。
 *
 * 🔴 决议端点**无请求体**（决议人取当前登录用户）；409（已决议）/ 404（不存在）等错误
 *    一律展示后端 `message`（`toApiError(error).message`）。
 * 🔴 **不加 `RequirePermission`**：后端 `/approvals` 端点仅要求登录（`CurrentUser`），
 *    前端无 `approval:*` 权限码。
 */

/** 左列固定宽度（约 320px；小屏纵向堆叠）。 */
const LIST_WIDTH_CLASS = "w-full shrink-0 lg:w-[320px]";

/** 两位补零。 */
function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** 绝对时间格式化：`YYYY-MM-DD HH:mm`（**本地时区**；空值 / 非法值 → `—`）。 */
function formatTimestamp(value?: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return (
    `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ` +
    `${pad2(date.getHours())}:${pad2(date.getMinutes())}`
  );
}

/** 主体类型 → 中文名（未知类型回落原文，原文亦空 → 「其他」）。 */
function subjectTypeLabel(t: TranslateFn, subjectType: string): string {
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

/** 状态 → 中文名（未知状态回落原文）。 */
function statusLabel(t: TranslateFn, status: string): string {
  switch (status) {
    case "PENDING":
      return t("approvals.status.PENDING");
    case "APPROVED":
      return t("approvals.status.APPROVED");
    case "REJECTED":
      return t("approvals.status.REJECTED");
    case "EXPIRED":
      return t("approvals.status.EXPIRED");
    default:
      return status;
  }
}

/** 状态胶囊配色（语义四色；未知状态走中性灰）。 */
function statusBadgeClass(status: string): string {
  switch (status) {
    case "PENDING":
      return "bg-warning/10 text-warning";
    case "APPROVED":
      return "bg-success/10 text-success";
    case "REJECTED":
    case "EXPIRED":
      return "bg-destructive/10 text-destructive";
    default:
      return "bg-secondary text-muted-foreground";
  }
}

/** 判定过期时刻是否已过（无值 / 非法值 → 未过期）。 */
function isExpired(expiresAt?: string | null): boolean {
  if (!expiresAt) {
    return false;
  }
  const date = new Date(expiresAt);
  if (Number.isNaN(date.getTime())) {
    return false;
  }
  return date.getTime() < Date.now();
}

/** 请求人展示名（缺失 → 「未知用户」）。 */
function requesterLabel(t: TranslateFn, approval: ApprovalResponse): string {
  const requester = approval.requested_by;
  return requester && requester.length > 0 ? requester : t("approvals.unknownUser");
}

/** 错误面板（就地实现；结构与 `components/agents/TabPanels.tsx` 的错误态一致）。 */
function ApprovalErrorPanel({
  testId,
  retryTestId,
  error,
  onRetry,
}: {
  testId: string;
  retryTestId: string;
  error: unknown;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border bg-card px-6 py-10 text-center"
      data-testid={testId}
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
        <AlertCircle aria-hidden className="h-5 w-5" />
      </span>
      <h2 className="text-sm font-semibold text-foreground">{t("approvals.error.loadFailed")}</h2>
      <p className="max-w-md text-xs text-muted-foreground">{toApiError(error).message}</p>
      <button
        type="button"
        data-testid={retryTestId}
        onClick={onRetry}
        className="mt-1 h-8 rounded-lg border border-input bg-background px-3 text-xs text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("approvals.error.retry")}
      </button>
    </div>
  );
}

/** 列表骨架（左列三行占位）。 */
function ApprovalListSkeleton() {
  return (
    <div className="space-y-2" data-testid="approvals-list-skeleton">
      {Array.from({ length: 3 }).map((_, index) => (
        <Skeleton key={index} className="h-14 w-full rounded-lg" />
      ))}
    </div>
  );
}

/** 详情骨架（键值 + 载荷 + 动作区占位）。 */
function ApprovalDetailSkeleton() {
  return (
    <div className="space-y-2" data-testid="approvals-detail-skeleton">
      <Skeleton className="h-5 w-40" />
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

/**
 * 审批详情面板（右列）。
 *
 * @param props.approvalId 当前选中的审批 id（`null` → 未选中，渲染占位）。
 */
function ApprovalDetail({ approvalId }: { approvalId: string | null }) {
  const { t } = useTranslation();
  const detailQuery = useApproval(approvalId);
  const approveApproval = useApproveApproval();
  const rejectApproval = useRejectApproval();
  const [rejectOpen, setRejectOpen] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const approval = detailQuery.data;

  if (approvalId === null) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-card/40 px-4 py-10">
        <InlineEmpty
          testId="approvals-detail-placeholder"
          icon={Inbox}
          title={t("approvals.detail.placeholder.title")}
          description={t("approvals.detail.placeholder.description")}
        />
      </div>
    );
  }

  if (detailQuery.isLoading) {
    return <ApprovalDetailSkeleton />;
  }

  if (detailQuery.error !== null && detailQuery.error !== undefined) {
    return (
      <ApprovalErrorPanel
        testId="approvals-detail-error"
        retryTestId="approvals-detail-retry"
        error={detailQuery.error}
        onRetry={() => void detailQuery.refetch()}
      />
    );
  }

  if (!approval) {
    return <ApprovalDetailSkeleton />;
  }

  // 详情端点**无状态过滤**（`GET /approvals/{id}` 可返回任意状态）：
  // - `PENDING` → 可决议；
  // - `APPROVED` / `REJECTED` → **只读态**（隐藏决议按钮，展示决议人 / 决议时间）；
  // - `EXPIRED` → 终态（展示「已过期」，决议按钮禁用以示不可再转移）。
  const isPending = approval.status === "PENDING";
  const isDecided = approval.status === "APPROVED" || approval.status === "REJECTED";
  const isStatusExpired = approval.status === "EXPIRED";
  const busy = approveApproval.isPending || rejectApproval.isPending;

  /** 决议通过（无请求体；失败展示后端 message 并刷新详情）。 */
  const handleApprove = (): void => {
    setFeedback(null);
    approveApproval.mutate(approval.id, {
      onSuccess: (updated) => {
        setFeedback(t("approvals.feedback.approved", { status: statusLabel(t, updated.status) }));
      },
      onError: (error) => {
        setFeedback(toApiError(error).message);
        // 409（已决议）等冲突：本地状态已过期 → 拉一次详情对齐后端真相。
        void detailQuery.refetch();
      },
    });
  };

  /** 确认驳回（二次确认后调用；失败展示后端 message 并刷新详情）。 */
  const handleReject = (): void => {
    setFeedback(null);
    rejectApproval.mutate(approval.id, {
      onSuccess: (updated) => {
        setRejectOpen(false);
        setFeedback(t("approvals.feedback.rejected", { status: statusLabel(t, updated.status) }));
      },
      onError: (error) => {
        setRejectOpen(false);
        setFeedback(toApiError(error).message);
        void detailQuery.refetch();
      },
    });
  };

  return (
    <div className="rounded-xl border border-border bg-card" data-testid="approvals-detail">
      <div className="flex items-center gap-2 border-b border-border px-4 pb-2 pt-4">
        <h2 className="text-sm font-semibold text-foreground">{t("approvals.detail.title")}</h2>
        <span
          className={cn(
            "flex-none rounded-full px-2 py-0.5 text-[11px]",
            statusBadgeClass(approval.status),
          )}
          data-testid="approval-status"
        >
          {statusLabel(t, approval.status)}
        </span>
        <span
          className="min-w-0 truncate font-mono text-[10px] text-muted-foreground"
          title={approval.id}
        >
          {approval.id}
        </span>
      </div>

      <div className="space-y-3 px-4 pb-4 pt-3">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-[11px] text-muted-foreground">
              {t("approvals.detail.subjectType")}
            </dt>
            <dd className="text-xs text-foreground" data-testid="approval-subject-type">
              {subjectTypeLabel(t, approval.subject_type)}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted-foreground">{t("approvals.detail.requester")}</dt>
            <dd className="truncate text-xs text-foreground" data-testid="approval-requester">
              {requesterLabel(t, approval)}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted-foreground">
              {t("approvals.detail.submittedAt")}
            </dt>
            <dd className="text-xs text-foreground" data-testid="approval-created-at">
              {formatTimestamp(approval.created_at)}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted-foreground">{t("approvals.detail.expiresAt")}</dt>
            <dd className="text-xs text-foreground" data-testid="approval-expires-at">
              {formatTimestamp(approval.expires_at)}
            </dd>
          </div>
          <div className="col-span-2">
            <dt className="text-[11px] text-muted-foreground">
              {t("approvals.detail.subjectRef")}
            </dt>
            <dd
              className="truncate font-mono text-[11px] text-foreground"
              data-testid="approval-subject-ref"
            >
              {approval.subject_ref.length > 0 ? approval.subject_ref : "—"}
            </dd>
          </div>
        </dl>

        <details
          className="rounded-lg border border-border bg-muted/30 px-3 py-2"
          data-testid="approval-payload"
        >
          <summary className="cursor-pointer text-[11px] font-medium text-foreground">
            {t("approvals.detail.payload")}
          </summary>
          <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-[1.6] text-muted-foreground">
            {Object.keys(approval.payload ?? {}).length > 0
              ? JSON.stringify(approval.payload, null, 2)
              : t("approvals.detail.payloadEmpty")}
          </pre>
        </details>

        {feedback ? (
          <p className="text-[11px] text-muted-foreground" data-testid="approval-feedback">
            {feedback}
          </p>
        ) : null}

        {isDecided ? (
          // 已决议（APPROVED / REJECTED）→ **只读态**：不渲染决议按钮。
          <div
            className="rounded-lg border border-border bg-muted/30 px-3 py-2"
            data-testid="approval-readonly"
          >
            <p className="text-[11px] text-muted-foreground">{t("approvals.detail.readonly")}</p>
            <dl className="mt-1.5 grid grid-cols-2 gap-3">
              <div>
                <dt className="text-[11px] text-muted-foreground">
                  {t("approvals.detail.decidedBy")}
                </dt>
                <dd className="truncate text-xs text-foreground" data-testid="approval-decided-by">
                  {approval.decided_by && approval.decided_by.length > 0
                    ? approval.decided_by
                    : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] text-muted-foreground">
                  {t("approvals.detail.decidedAt")}
                </dt>
                <dd className="text-xs text-foreground" data-testid="approval-decided-at">
                  {formatTimestamp(approval.decided_at)}
                </dd>
              </div>
            </dl>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="default"
              data-testid="approval-approve"
              disabled={!isPending || busy}
              onClick={handleApprove}
            >
              <Check aria-hidden className="mr-1 h-3.5 w-3.5" />
              {t("approvals.approve")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              data-testid="approval-reject"
              disabled={!isPending || busy}
              onClick={() => setRejectOpen(true)}
            >
              <X aria-hidden className="mr-1 h-3.5 w-3.5" />
              {t("approvals.reject")}
            </Button>
            {isStatusExpired ? (
              <span className="text-[11px] text-destructive" data-testid="approval-expired-hint">
                {t("approvals.detail.expiredHint")}
              </span>
            ) : null}
          </div>
        )}
      </div>

      {/* 驳回二次确认（本仓无 AlertDialog 原语 → 复用 Dialog，仿 `KbDeleteDialog`）。 */}
      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent data-testid="approval-reject-dialog">
          <DialogHeader>
            <DialogTitle>{t("approvals.reject.title")}</DialogTitle>
            <DialogDescription>
              {t("approvals.reject.confirm", {
                type: subjectTypeLabel(t, approval.subject_type),
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              data-testid="approval-reject-cancel"
              onClick={() => setRejectOpen(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              data-testid="approval-reject-confirm"
              onClick={handleReject}
              disabled={rejectApproval.isPending}
            >
              {t("approvals.reject.submit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/**
 * 审批中心页面（具名导出；路由经 `router.tsx` 懒加载挂载到 `/approvals`）。
 *
 * @returns 页头（标题 + 待办计数 + 刷新）+ 左列待办列表 + 右列详情。
 */
export function Approvals() {
  const { t } = useTranslation();
  const listQuery = useApprovals();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const approvals = listQuery.data ?? [];
  const count = approvals.length;
  // 未显式选择时默认落在第一条（列表刷新后自动跟随，避免出现「有列表无详情」的悬空态）。
  const activeId = selectedId ?? (count > 0 ? approvals[0].id : null);

  return (
    <PageContainer width="content">
      <div className="space-y-3" data-testid="approvals-page">
        {/* ===== 页头：标题 + 待办计数 + 刷新 ===== */}
        <div className="flex items-start gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground">{t("approvals.title")}</h1>
            <p className="mt-1 text-xs text-muted-foreground" data-testid="approvals-subtitle">
              {t("approvals.subtitle", { count })}
            </p>
          </div>
          <div className="ml-auto flex flex-none items-center gap-2 pt-0.5">
            <button
              type="button"
              data-testid="approvals-refresh"
              aria-label={t("approvals.refresh")}
              title={t("approvals.refresh")}
              onClick={() => void listQuery.refetch()}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-input bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <RefreshCw aria-hidden className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* ===== 两列：左待办列表 / 右详情 ===== */}
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start">
          <Card className={LIST_WIDTH_CLASS}>
            <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 px-4 pb-2 pt-4">
              <CardTitle className="text-sm font-semibold text-foreground">
                {t("approvals.list.title")}
              </CardTitle>
              <span className="text-[11px] text-muted-foreground" data-testid="approvals-count">
                {t("approvals.list.count", { count })}
              </span>
            </CardHeader>
            <CardContent className="px-2 pb-3 pt-0">
              {listQuery.isLoading ? (
                <ApprovalListSkeleton />
              ) : listQuery.error !== null && listQuery.error !== undefined ? (
                <ApprovalErrorPanel
                  testId="approvals-list-error"
                  retryTestId="approvals-retry"
                  error={listQuery.error}
                  onRetry={() => void listQuery.refetch()}
                />
              ) : count === 0 ? (
                <InlineEmpty
                  testId="approvals-empty"
                  icon={Inbox}
                  title={t("approvals.list.empty.title")}
                  description={t("approvals.list.empty.description")}
                />
              ) : (
                <ul className="space-y-0.5" data-testid="approvals-list">
                  {approvals.map((approval) => {
                    const active = approval.id === activeId;
                    return (
                      <li key={approval.id}>
                        <button
                          type="button"
                          data-testid={`approval-item-${approval.id}`}
                          aria-current={active ? "true" : undefined}
                          onClick={() => setSelectedId(approval.id)}
                          className={cn(
                            "relative flex w-full flex-col gap-1 rounded-lg px-3 py-2 text-left transition-colors",
                            active ? "bg-accent/10" : "hover:bg-accent/10",
                          )}
                        >
                          {/* 选中项金色竖条（与 Rail 一级项同视觉语言）。 */}
                          {active ? (
                            <span
                              aria-hidden
                              className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-accent"
                            />
                          ) : null}
                          <span className="flex items-center gap-1.5">
                            <span className="truncate text-xs font-medium text-foreground">
                              {subjectTypeLabel(t, approval.subject_type)}
                            </span>
                            {isExpired(approval.expires_at) ? (
                              <span className="flex-none rounded-full bg-destructive/10 px-1.5 py-0.5 text-[10px] text-destructive">
                                {t("approvals.expired")}
                              </span>
                            ) : null}
                          </span>
                          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                            <span className="truncate">{requesterLabel(t, approval)}</span>
                            <span aria-hidden>·</span>
                            <span className="flex-none">
                              {formatRelativeTime(approval.created_at, t) ?? "—"}
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardContent>
          </Card>

          <div className="min-w-0 flex-1">
            {/*
             * 🔴 `key` 必须绑 `approvalId`：`ApprovalDetail` 内部持有 `feedback`（决议结果提示）
             *    与 `rejectOpen`（确认弹窗）等**按记录隔离**的局部状态。不加 `key` 时 React 会
             *    复用同一实例——切换条目后上一条的「已通过 / 已驳回」提示会串到新记录上，
             *    让用户误以为当前这条已被自己决议（P2-1）。切换即重挂载，状态随记录归零。
             */}
            <ApprovalDetail key={activeId ?? "__none__"} approvalId={activeId} />
          </div>
        </div>
      </div>
    </PageContainer>
  );
}
