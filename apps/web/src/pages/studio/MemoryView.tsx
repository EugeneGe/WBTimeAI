import { useMemo, useState } from "react";

import { EmptyState } from "@/components/common/EmptyState";
import { PageContainer } from "@/components/layout/PageContainer";
import { Badge } from "@/components/ui/badge";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDeleteMemory, useMemories } from "@/hooks/useMemory";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { MemoryResponse } from "@/types";

/** 作用域类型选项（`all` 哨兵 ↔ 空串「全部」；radix `SelectItem` 值不可为空）。 */
const SCOPE_TYPES: ReadonlyArray<{ value: string; label?: string; labelKey?: string }> = [
  { value: "all", labelKey: "studio.memory.scope.all" },
  { value: "user", label: "user" },
  { value: "agent", label: "agent" },
  { value: "project", label: "project" },
  { value: "workspace", label: "workspace" },
  { value: "conversation", label: "conversation" },
];

/** 记忆类别选项（`all` 哨兵 ↔ 空串「全部」）。 */
const KINDS: ReadonlyArray<{ value: string; label?: string; labelKey?: string }> = [
  { value: "all", labelKey: "studio.memory.scope.all" },
  { value: "SHORT_TERM", label: "SHORT_TERM" },
  { value: "LONG_TERM", label: "LONG_TERM" },
  { value: "PROJECT", label: "PROJECT" },
  { value: "AGENT", label: "AGENT" },
  { value: "USER", label: "USER" },
];

/** 重要度分档样式（≥0.8 成功 / 0.5–0.8 中性 / <0.5 警示；设计屏 15）。 */
function importanceClass(value: number): string {
  if (value >= 0.8) {
    return "border-transparent bg-success/15 text-success";
  }
  if (value >= 0.5) {
    return "border-transparent bg-muted text-muted-foreground";
  }
  return "border-transparent bg-warning/15 text-warning";
}

/** 反馈语气：`info` 中性（不开红字）/ `error` 错误（红字）。 */
type FeedbackTone = "info" | "error";

/** 反馈内容（文案 + 语气）。 */
interface FeedbackState {
  /** 展示文案。 */
  text: string;
  /** 语气（404 走 `info`，其余错误走 `error`）。 */
  tone: FeedbackTone;
}

/** 占位存储期下 404 的**中性**提示键（不视为故障）。 */
const PLACEHOLDER_NOT_FOUND_KEY = "studio.memory.notFound";

/**
 * Memory 视图（W6 / T2-35；设计 §2.7 / 裁定 §2.4 F-d / F-h；D-UI 体验优化波 · WS-P3b；M06-03）。
 *
 * - 宽档；按 `scope_type` / `scope_id` / `kind` **浏览**记忆（select 采用 `ui/select` 原语）；
 * - 逐条**删除**（`DELETE /memory/{id}`；**先二次确认**，正文「删除后不可恢复」）；
 * - 展示**来源 Run**（`source_run_id`）；重要度分档配色；
 * - 空态 `EmptyState` + 「占位存储期」追加说明；加载 `Skeleton`；错误由全局 ErrorBoundary 兜底。
 *
 * 🔴 SQLite 后端下检索退化为最近 / 关键词排序（无向量）——页内给出提示。
 * 🔴 删除失败按状态码分流：404 → 中性文案（非 `text-destructive`）；其余 → 红字原文。
 */
export function MemoryView() {
  const { t } = useTranslation();
  const [scopeType, setScopeType] = useState<string>("");
  const [scopeId, setScopeId] = useState<string>("");
  const [kind, setKind] = useState<string>("");
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  /** 待确认删除的记忆（`null` = 未打开确认弹窗）。 */
  const [pendingDelete, setPendingDelete] = useState<MemoryResponse | null>(null);

  const params = useMemo(
    () => ({
      scope_type: scopeType || null,
      scope_id: scopeId || null,
      kind: kind || null,
    }),
    [scopeType, scopeId, kind],
  );

  const { data: memories, isLoading } = useMemories(params);
  const deleteMemory = useDeleteMemory();

  /** 点击「删除」→ 仅打开二次确认（不提交）。 */
  const handleDelete = (memory: MemoryResponse): void => {
    setPendingDelete(memory);
  };

  /** 确认删除（弹窗内「删除」）→ 真正提交。 */
  const handleConfirmDelete = (): void => {
    const memory = pendingDelete;
    if (!memory) {
      return;
    }
    deleteMemory.mutate(memory.id, {
      onSuccess: () => {
        setFeedback({ text: t("studio.memory.deleted"), tone: "info" });
      },
      onError: (error) => {
        const apiError = toApiError(error);
        setFeedback(
          apiError.status === 404
            ? { text: t(PLACEHOLDER_NOT_FOUND_KEY), tone: "info" }
            : { text: apiError.message, tone: "error" },
        );
      },
      onSettled: () => {
        setPendingDelete(null);
      },
    });
  };

  return (
    <PageContainer width="wide">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-title font-medium text-primary">Memory</h1>
          {feedback ? (
            <span
              className={cn(
                "text-xs",
                feedback.tone === "error" ? "text-destructive" : "text-muted-foreground",
              )}
              data-testid="memory-feedback"
            >
              {feedback.text}
            </span>
          ) : null}
        </div>

        <Card>
          <CardHeader>
            <CardTitle>{t("studio.memory.filter.title")}</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="memory-scope-type">{t("studio.memory.filter.scopeType")}</Label>
              <Select
                value={scopeType || "all"}
                onValueChange={(next) => setScopeType(next === "all" ? "" : next)}
              >
                <SelectTrigger id="memory-scope-type" data-testid="memory-scope-type">
                  <SelectValue placeholder={t("studio.memory.scope.all")} />
                </SelectTrigger>
                <SelectContent>
                  {SCOPE_TYPES.map((item) => (
                    <SelectItem
                      key={item.value}
                      value={item.value}
                      data-testid={`memory-scope-type-${item.value}`}
                    >
                      {"labelKey" in item && item.labelKey ? t(item.labelKey) : item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="memory-scope-id">{t("studio.memory.filter.scopeId")}</Label>
              <Input
                id="memory-scope-id"
                data-testid="memory-scope-id"
                value={scopeId}
                onChange={(event) => setScopeId(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="memory-kind">{t("studio.memory.filter.kind")}</Label>
              <Select
                value={kind || "all"}
                onValueChange={(next) => setKind(next === "all" ? "" : next)}
              >
                <SelectTrigger id="memory-kind" data-testid="memory-kind">
                  <SelectValue placeholder={t("studio.memory.scope.all")} />
                </SelectTrigger>
                <SelectContent>
                  {KINDS.map((item) => (
                    <SelectItem
                      key={item.value}
                      value={item.value}
                      data-testid={`memory-kind-${item.value}`}
                    >
                      {"labelKey" in item && item.labelKey ? t(item.labelKey) : item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("studio.memory.list.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-xs text-muted-foreground" data-testid="memory-backend-hint">
              {t("studio.memory.list.backendHint")}
            </p>
            {isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-3/4" />
              </div>
            ) : (memories ?? []).length === 0 ? (
              <div data-testid="memory-empty">
                <EmptyState
                  title={t("studio.memory.empty.title")}
                  description={t("studio.memory.empty.description")}
                />
                {/* M06-03：占位存储期预期说明（第三句）。 */}
                <p
                  className="mt-2 text-center text-xs text-muted-foreground"
                  data-testid="memory-empty-hint"
                >
                  {t("studio.memory.empty.hint")}
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("studio.memory.col.kind")}</TableHead>
                    <TableHead>{t("studio.memory.col.scope")}</TableHead>
                    <TableHead>{t("studio.memory.col.visibility")}</TableHead>
                    <TableHead>{t("studio.memory.col.content")}</TableHead>
                    <TableHead>{t("studio.memory.col.importance")}</TableHead>
                    <TableHead>{t("studio.memory.col.sourceRun")}</TableHead>
                    <TableHead className="text-right">{t("common.actions")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(memories ?? []).map((memory) => (
                    <TableRow key={memory.id} data-testid={`memory-row-${memory.id}`}>
                      <TableCell>
                        <Badge variant="outline">{memory.kind}</Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {memory.scope_type}
                        {memory.scope_id ? `:${memory.scope_id}` : ""}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{memory.visibility}</Badge>
                      </TableCell>
                      <TableCell className="max-w-xs truncate">{memory.content}</TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={importanceClass(memory.importance)}
                          data-testid={`memory-importance-${memory.id}`}
                        >
                          {memory.importance.toFixed(2)}
                        </Badge>
                      </TableCell>
                      <TableCell
                        className="font-mono text-xs text-muted-foreground"
                        data-testid={`memory-source-${memory.id}`}
                      >
                        {memory.source_run_id || "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          data-testid={`memory-delete-${memory.id}`}
                          disabled={deleteMemory.isPending}
                          onClick={() => handleDelete(memory)}
                        >
                          {t("common.delete")}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* 删除二次确认（M06-03）：默认焦点落「取消」，提交中禁用「删除」。 */}
        <Dialog
          open={pendingDelete !== null}
          onOpenChange={(open) => {
            if (!open) {
              setPendingDelete(null);
            }
          }}
        >
          <DialogContent data-testid="memory-delete-dialog" className="max-w-md">
            <DialogHeader>
              <DialogTitle>{t("studio.memory.delete.title")}</DialogTitle>
              <DialogDescription>{t("studio.memory.delete.description")}</DialogDescription>
            </DialogHeader>
            {pendingDelete ? (
              <p
                className="truncate text-xs text-muted-foreground"
                data-testid="memory-delete-target"
              >
                {pendingDelete.content}
              </p>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                size="sm"
                autoFocus
                data-testid="memory-delete-cancel"
                onClick={() => setPendingDelete(null)}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                data-testid="memory-delete-confirm"
                disabled={deleteMemory.isPending}
                onClick={handleConfirmDelete}
              >
                {t("common.delete")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </PageContainer>
  );
}
