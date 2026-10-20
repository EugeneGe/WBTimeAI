import { useQueryClient } from "@tanstack/react-query";
import { FolderKanban, GitBranch, Plus, RefreshCw, Rocket } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { InlineEmpty } from "@/components/common/InlineEmpty";
import { RequirePermission } from "@/components/guards/RequirePermission";
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
import { useAgentVersions, useAgents } from "@/hooks/useAgents";
import { useCreateProject, useProjects } from "@/hooks/useProjects";
import {
  useApplyChange,
  useCancelRemoteTask,
  useCloneProject,
  useProjectGitRefs,
  useProjectStatus,
  usePushChange,
  useRemoteArtifacts,
  useRemoteAttempts,
  useRemoteDiff,
  useRemoteEvents,
  useRemoteLogs,
  useRemoteTask,
  useSubmitRemoteTask,
} from "@/hooks/useRemoteTasks";
import { useWorkflowVersions, useWorkflows } from "@/hooks/useWorkflow";
import { useWorkspaces } from "@/hooks/useWorkspaces";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { queryKeys } from "@/lib/query";
import { remoteTaskService } from "@/services/remoteTask";
import type {
  RemoteTaskSubmitRequest,
  TaskAttemptResponse,
  WorkflowResponse,
  WorkflowVersionResponse,
  WorkspaceResponse,
} from "@/types";

/**
 * RemoteTasks（R4 / T2-62；U-P2-41 / #41 / D17–D18；V0.4.6 **B-24 重排**）——远程工作台。
 *
 * 版式：**页头** → **工作区上下文条** → **左 380 提交 / 右 1fr 运行视图（Tabs）**。
 * ① 页头：H1 + 副标题（流程指引）+ 刷新 + 「前往工作区」；
 * ② 上下文条：工作区 `Select` + 项目数（只读缓存）+ 新建项目（Dialog）+ 项目状态/克隆锚点；
 * ③ 左列：提交卡（固定 Agent / Workflow 版本）+ 项目状态与克隆卡；
 * ④ 右列：运行视图五段 Tabs（状态 / 尝试 / 日志 / 事件 / 差异·产物）。
 *
 * 🔴 **冻结路径**：Apply / Push 经 `remoteTaskService.apply|push`（`/tasks/{id}/apply` · `/push`），
 *    **禁止** `/diff/apply`。
 * 🔴 **敏感值纪律**：本页**不**渲染宿主路径 / Token / 凭证；仅展示不透明 `checkout_ref` 与提交哈希。
 * 🔴 **降级**：Diff 读取以 `available` 标志降级（200）；Artifact 下载 / Apply / Push 未装配 → **503**
 *    （`DEPENDENCY_MISSING`）；两种降级均渲染降级文案（**不**伪造）。
 * 🔴 **五段面板全部挂载**，非激活面板用 `hidden` 属性隐藏（**不**条件渲染）——
 *    既有用例直接 `findByTestId` 取 attempts / logs / events / diff / artifacts / apply / push。
 * 🔴 `remote-change-feedback`（Apply / Push 反馈）位于 **Tabs 之上**，切 Tab 不丢失。
 */

/** 提取可展示错误消息（兼容已归一化 / 未归一化错误）。 */
function resolveErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.length > 0) {
      return message;
    }
  }
  return toApiError(error).message;
}

/** 任务状态徽章配色。 */
function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "SUCCESS") {
    return "default";
  }
  if (status === "FAILED") {
    return "destructive";
  }
  return "secondary";
}

/** 取 ID 短码（卡头 `task_xxxxxx`）。 */
function shortCode(id: string): string {
  return id.length <= 6 ? id : id.slice(-6);
}

/** 运行视图分段键（顺序冻结：状态 → 尝试 → 日志 → 事件 → 差异·产物）。 */
type WorkbenchTab = "status" | "attempts" | "logs" | "events" | "changes";

/** 分段定义（`testId` 口径：`remote-tab-<key>` / 面板 `remote-panel-<key>`）。
 *
 * 🔴 模块顶层**不**取 `t`：此处只存 key，文案在组件内经 `t(labelKey)` 解析。
 */
const WORKBENCH_TABS: readonly { key: WorkbenchTab; labelKey: string }[] = [
  { key: "status", labelKey: "remoteTasks.tabs.status" },
  { key: "attempts", labelKey: "remoteTasks.tabs.attempts" },
  { key: "logs", labelKey: "remoteTasks.tabs.logs" },
  { key: "events", labelKey: "remoteTasks.tabs.events" },
  { key: "changes", labelKey: "remoteTasks.tabs.changes" },
];

/** 小号「次级」按钮样式（页头 / 上下文条 / 空态动作）。 */
const GHOST_ACTION_CLASS =
  "inline-flex h-7 items-center gap-1 rounded-lg border border-input bg-background px-2.5 text-[11px] text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50";

/** 页头 / 上下文条图标按钮样式。 */
const ICON_BUTTON_CLASS =
  "flex h-8 w-8 items-center justify-center rounded-lg border border-input bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** 滑动卡（本页统一「薄头」样式：13px 标题 + 紧凑内边距）。 */
const CARD_SHELL_CLASS = "rounded-xl border border-border bg-card";

/** Artifact 单行下载态（`pending` 在途 / `failed` 失败；成功则整行无态）。 */
type ArtifactDownloadState = "pending" | "failed";

/** 空数组常量（稳定引用，避免 `useEffect` 依赖每次渲染变化）。 */
const NO_WORKSPACES: WorkspaceResponse[] = [];

/**
 * 运行视图：五段 Tabs（状态 / Attempt / 日志 / 事件 / Diff + Artifact + 变更操作）。
 *
 * 卡头 = `task_<短码>` + 状态徽标 + 取消；`remote-change-feedback` 常驻 Tabs 之上。
 */
function TaskWorkbench({ taskId }: { taskId: string }) {
  const { t } = useTranslation();
  const taskQuery = useRemoteTask(taskId);
  const attemptsQuery = useRemoteAttempts(taskId);
  const logsQuery = useRemoteLogs(taskId);
  const [cursor, setCursor] = useState<string | null>(null);
  const eventsQuery = useRemoteEvents(taskId, cursor);
  const [selectedAttempt, setSelectedAttempt] = useState<number | null>(null);
  const diffQuery = useRemoteDiff(taskId, selectedAttempt);
  const artifactsQuery = useRemoteArtifacts(taskId, selectedAttempt);
  const applyChange = useApplyChange(taskId);
  const pushChange = usePushChange(taskId);
  const cancelTask = useCancelRemoteTask(taskId);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [targetRef, setTargetRef] = useState("");
  const [tab, setTab] = useState<WorkbenchTab>("status");
  /** Artifact 逐行下载态（键 = Artifact 名；**行级**隔离，互不影响）。 */
  const [artifactDownload, setArtifactDownload] = useState<Record<string, ArtifactDownloadState>>(
    {},
  );

  // 切换 Attempt（= 换了 Artifact 集合）→ 清空下载态，使「下载失败」的行可重新尝试。
  useEffect(() => {
    setArtifactDownload({});
  }, [selectedAttempt]);

  const snapshot = taskQuery.data;
  const attempts: TaskAttemptResponse[] = attemptsQuery.data ?? [];
  const events = eventsQuery.data?.events ?? [];
  const logs = logsQuery.data ?? [];

  /** Apply / Push 的 payload（`target_ref` 空 → 由后端取默认分支）。 */
  const changePayload = useMemo(
    () => (targetRef.trim() ? { target_ref: targetRef.trim() } : {}),
    [targetRef],
  );

  /**
   * Artifact **逐行下载**（M04-04）。
   *
   * 流程：`GET /tasks/{id}/artifacts/{name}`（**逐项重新鉴权**，`attempt` 有选中值才带上）
   * → Blob → `URL.createObjectURL` → 临时 `<a download>` 触发浏览器保存 → `revokeObjectURL`。
   *
   * 🔴 ObjectURL 在 `finally` 中释放：`createObjectURL` 之后的任一 DOM 语句抛错
   *    （append / click / remove）也**不会**泄漏。
   * 🔴 失败**不**弹全局错误：仅行内 11px「下载失败」文案 + 按钮**可再次点击**重试
   *    （重试前先清空该行状态）；成功则整行恢复无态。
   */
  const handleDownloadArtifact = (name: string): void => {
    // 重试语义：先删除该行既有状态（含 `failed`），再置 `pending`。
    setArtifactDownload((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
    setArtifactDownload((prev) => ({ ...prev, [name]: "pending" }));

    remoteTaskService
      .downloadArtifact(taskId, name, { attempt: selectedAttempt })
      .then((blob: Blob) => {
        const objectUrl = URL.createObjectURL(blob);
        try {
          const anchor = document.createElement("a");
          anchor.href = objectUrl;
          anchor.download = name;
          anchor.rel = "noopener";
          document.body.appendChild(anchor);
          anchor.click();
          document.body.removeChild(anchor);
        } finally {
          URL.revokeObjectURL(objectUrl);
        }
        setArtifactDownload((prev) => {
          const next = { ...prev };
          delete next[name];
          return next;
        });
      })
      .catch(() => {
        setArtifactDownload((prev) => ({ ...prev, [name]: "failed" }));
      });
  };

  return (
    <div className="space-y-2.5" data-testid="remote-task-detail">
      {/* Apply / Push 反馈：常驻 Tabs 之上，不随分段隐藏。 */}
      {feedback ? (
        <p
          className="rounded-md bg-secondary px-2.5 py-1 text-[11px] text-foreground"
          data-testid="remote-change-feedback"
          role="status"
        >
          {feedback}
        </p>
      ) : null}

      <div className={CARD_SHELL_CLASS}>
        {/* 卡头：task 短码 + 状态徽标 + 取消 */}
        <div className="flex items-center gap-2 border-b border-border px-3.5 py-2">
          <span
            className="font-mono text-[11px] text-muted-foreground"
            data-testid="remote-task-code"
          >
            task_{shortCode(taskId)}
          </span>
          <Badge variant={statusVariant(snapshot?.status ?? "")} data-testid="remote-task-status">
            {snapshot?.status ?? "—"}
          </Badge>
          <div className="ml-auto">
            <RequirePermission
              code="task:cancel"
              fallback={
                <span className="text-[10px] text-muted-foreground">
                  {t("remoteTasks.workbench.cancelDenied")}
                </span>
              }
            >
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-2 text-[11px]"
                data-testid="remote-cancel-button"
                disabled={cancelTask.isPending}
                onClick={() =>
                  cancelTask.mutate(undefined, {
                    onSuccess: (updated) =>
                      setFeedback(
                        t("remoteTasks.workbench.cancelRequested", { status: updated.status }),
                      ),
                    onError: (error) => setFeedback(resolveErrorMessage(error)),
                  })
                }
              >
                {t("remoteTasks.workbench.cancel")}
              </Button>
            </RequirePermission>
          </div>
        </div>

        <div className="space-y-2.5 p-3.5">
          {/* 分段条 */}
          <div
            className="flex gap-0.5 border-b border-border"
            role="tablist"
            aria-label={t("remoteTasks.workbench.tabsLabel")}
          >
            {WORKBENCH_TABS.map((item) => {
              const active = tab === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  data-testid={`remote-tab-${item.key}`}
                  onClick={() => setTab(item.key)}
                  className={cn(
                    "border-b-2 px-2.5 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active
                      ? "border-[#F5B941] font-medium text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t(item.labelKey)}
                </button>
              );
            })}
          </div>

          {/* ① 状态 */}
          <div hidden={tab !== "status"} data-testid="remote-panel-status">
            <div className="space-y-2.5">
              {!snapshot ? (
                <div className="space-y-2" data-testid="remote-status-loading">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-6 w-full" />
                </div>
              ) : (
                <dl className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                  <div>
                    <dt className="text-[10px] text-muted-foreground">
                      {t("remoteTasks.tabs.status")}
                    </dt>
                    <dd className="mt-0.5 text-[11px] text-foreground">{snapshot.status}</dd>
                  </div>
                  <div>
                    <dt className="text-[10px] text-muted-foreground">
                      {t("remoteTasks.status.attemptCount")}
                    </dt>
                    <dd className="mt-0.5 text-[11px] text-foreground">{snapshot.attempt_count}</dd>
                  </div>
                  <div>
                    <dt className="text-[10px] text-muted-foreground">checkout_ref</dt>
                    <dd
                      className="mt-0.5 font-mono text-[10px] text-foreground"
                      data-testid="remote-task-checkout-ref"
                    >
                      {snapshot.checkout_ref ?? "—"}
                    </dd>
                  </div>
                </dl>
              )}

              <div className="space-y-1">
                <Label htmlFor="remote-target-ref" className="text-[11px] text-muted-foreground">
                  {t("remoteTasks.status.targetRef")}
                </Label>
                <Input
                  id="remote-target-ref"
                  data-testid="remote-target-ref-input"
                  className="h-8 w-full max-w-[280px] text-xs"
                  placeholder={t("remoteTasks.status.targetRefPlaceholder")}
                  value={targetRef}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setTargetRef(event.target.value)
                  }
                />
              </div>
            </div>
          </div>

          {/* ② 尝试 */}
          <div hidden={tab !== "attempts"} data-testid="remote-panel-attempts">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("remoteTasks.tabs.attempts")}</TableHead>
                  <TableHead>{t("remoteTasks.field.status")}</TableHead>
                  <TableHead>{t("remoteTasks.field.durationMs")}</TableHead>
                  <TableHead className="text-right">{t("remoteTasks.field.review")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {attempts.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="text-xs text-muted-foreground"
                      data-testid="remote-attempts-empty"
                    >
                      {t("remoteTasks.attempts.empty")}
                    </TableCell>
                  </TableRow>
                ) : (
                  attempts.map((attempt) => (
                    <TableRow
                      key={attempt.attempt}
                      data-testid={`remote-attempt-row-${attempt.attempt}`}
                    >
                      <TableCell className="text-xs">{attempt.attempt}</TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(attempt.status)}>{attempt.status}</Badge>
                      </TableCell>
                      <TableCell className="text-xs">{attempt.duration_ms ?? "N/A"}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[11px]"
                          data-testid={`remote-attempt-select-${attempt.attempt}`}
                          onClick={() => setSelectedAttempt(attempt.attempt)}
                        >
                          {t("remoteTasks.field.review")}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* ③ 日志 */}
          <div hidden={tab !== "logs"} data-testid="remote-panel-logs">
            <div data-testid="remote-logs">
              {logs.length === 0 ? (
                <p className="text-xs text-muted-foreground" data-testid="remote-logs-empty">
                  {t("remoteTasks.logs.empty")}
                </p>
              ) : (
                <ul className="space-y-1 text-[11px]">
                  {logs.map((line) => (
                    <li key={line.seq} className="font-mono" data-testid={`remote-log-${line.seq}`}>
                      [{line.level}] {line.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* ④ 事件（断点续读） */}
          <div hidden={tab !== "events"} data-testid="remote-panel-events">
            <div className="space-y-2.5">
              <div data-testid="remote-events">
                {events.length === 0 ? (
                  <p className="text-xs text-muted-foreground" data-testid="remote-events-empty">
                    {t("remoteTasks.events.empty")}
                  </p>
                ) : (
                  <ul className="space-y-1 text-[11px]">
                    {events.map((event) => (
                      <li
                        key={event.seq}
                        className="font-mono"
                        data-testid={`remote-event-${event.seq}`}
                      >
                        #{event.seq} {event.type}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {eventsQuery.isError ? (
                <p className="text-[11px] text-destructive" data-testid="remote-events-error">
                  {resolveErrorMessage(eventsQuery.error)}
                </p>
              ) : null}
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-[11px]"
                data-testid="remote-events-resume"
                disabled={eventsQuery.isFetching}
                onClick={() => {
                  const next = eventsQuery.data?.next_cursor;
                  setCursor(next && next.length > 0 ? next : null);
                }}
              >
                {t("remoteTasks.events.resume")}
              </Button>
            </div>
          </div>

          {/* ⑤ 差异·产物（含 Apply / Push） */}
          <div hidden={tab !== "changes"} data-testid="remote-panel-changes">
            <div className="space-y-2.5">
              <div data-testid="remote-diff">
                <div className="mb-1 text-[11px] font-medium text-primary">Diff</div>
                {diffQuery.isError || diffQuery.data?.available === false ? (
                  <p className="text-xs text-muted-foreground" data-testid="remote-diff-degraded">
                    {t("remoteTasks.diff.degraded")}
                  </p>
                ) : diffQuery.data && diffQuery.data.files.length > 0 ? (
                  <ul className="space-y-1 text-xs">
                    {diffQuery.data.files.map((file) => (
                      <li
                        key={file.path}
                        className="font-mono text-[11px]"
                        data-testid={`remote-diff-file-${file.path}`}
                      >
                        <Badge variant="outline">{file.change_type}</Badge> {file.path}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground" data-testid="remote-diff-empty">
                    {diffQuery.isLoading
                      ? t("remoteTasks.diff.loading")
                      : t("remoteTasks.diff.empty")}
                  </p>
                )}
              </div>

              <div data-testid="remote-artifacts">
                <div className="mb-1 text-[11px] font-medium text-primary">Artifact</div>
                {artifactsQuery.isError ? (
                  <p
                    className="text-xs text-muted-foreground"
                    data-testid="remote-artifacts-degraded"
                  >
                    {t("remoteTasks.artifacts.degraded")}
                  </p>
                ) : (artifactsQuery.data ?? []).length > 0 ? (
                  <ul className="space-y-1 text-xs">
                    {(artifactsQuery.data ?? []).map((artifact) => {
                      const downloadState = artifactDownload[artifact.name];
                      return (
                        <li
                          key={artifact.name}
                          className="flex items-center justify-between gap-2 font-mono text-[11px]"
                          data-testid={`remote-artifact-${artifact.name}`}
                        >
                          <span className="truncate">{artifact.name}</span>
                          <span className="flex shrink-0 items-center gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-[11px]"
                              data-testid={`remote-artifact-download-${artifact.name}`}
                              disabled={downloadState === "pending"}
                              onClick={() => handleDownloadArtifact(artifact.name)}
                            >
                              {t("remoteTasks.artifacts.download")}
                            </Button>
                            {downloadState === "failed" ? (
                              <span
                                className="text-[11px] text-muted-foreground"
                                data-testid={`remote-artifact-download-error-${artifact.name}`}
                              >
                                {t("remoteTasks.artifacts.downloadFailed")}
                              </span>
                            ) : null}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground" data-testid="remote-artifacts-empty">
                    {t("remoteTasks.artifacts.empty")}
                  </p>
                )}
              </div>

              {/* 显式变更：Apply（不 Push）与独立 Push */}
              <div className="flex flex-wrap items-center gap-2 border-t border-border pt-2.5">
                <RequirePermission code="git:apply">
                  <Button
                    size="sm"
                    className="h-7 text-[11px]"
                    data-testid="remote-apply-button"
                    disabled={applyChange.isPending}
                    onClick={() =>
                      applyChange.mutate(changePayload, {
                        onSuccess: (result) =>
                          setFeedback(
                            result.already_applied
                              ? t("remoteTasks.apply.alreadyApplied", {
                                  commit: result.applied_commit ?? "",
                                })
                              : t("remoteTasks.apply.applied", {
                                  targetRef: result.target_ref,
                                  commit: result.applied_commit ?? "",
                                }),
                          ),
                        onError: (error) => setFeedback(resolveErrorMessage(error)),
                      })
                    }
                  >
                    {t("remoteTasks.apply.button")}
                  </Button>
                </RequirePermission>
                <RequirePermission code="git:push">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px]"
                    data-testid="remote-push-button"
                    disabled={pushChange.isPending}
                    onClick={() =>
                      pushChange.mutate(
                        { ...changePayload, remote: "origin" },
                        {
                          onSuccess: (result) =>
                            setFeedback(
                              result.already_up_to_date
                                ? t("remoteTasks.push.upToDate")
                                : t("remoteTasks.push.pushed", { ref: result.ref }),
                            ),
                          onError: (error) => setFeedback(resolveErrorMessage(error)),
                        },
                      )
                    }
                  >
                    {t("remoteTasks.push.button")}
                  </Button>
                </RequirePermission>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 提交表单：固定 Agent / Workflow 版本。
 *
 * `initialProjectId`：由 URL 上下文（`?project=`，来自项目页「在远程工作台打开」）传入；
 * 待该工作区项目列表就绪且**命中**时预选一次（不反向同步 URL）。
 */
function SubmitPanel({
  workspaceId,
  initialProjectId,
  onSubmitted,
}: {
  workspaceId: string;
  initialProjectId?: string | null;
  onSubmitted: (taskId: string) => void;
}) {
  const projectsQuery = useProjects(workspaceId);
  const { t } = useTranslation();
  const agentsQuery = useAgents();
  const workflowsQuery = useWorkflows();
  const submit = useSubmitRemoteTask();
  const [projectId, setProjectId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [workflowId, setWorkflowId] = useState("");
  const [agentVersionId, setAgentVersionId] = useState("");
  const [workflowVersionId, setWorkflowVersionId] = useState("");
  const [baseRef, setBaseRef] = useState("");
  const [requirement, setRequirement] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);

  // 切换工作区 → 清空已选项目（避免把 A 工作区的项目带进 B）。
  useEffect(() => {
    setProjectId("");
  }, [workspaceId]);

  // URL 上下文预选：仅当项目列表就绪且命中该工作区内的项目时设置一次。
  useEffect(() => {
    if (projectId || !initialProjectId) {
      return;
    }
    const projects = projectsQuery.data ?? [];
    if (projects.some((project) => project.id === initialProjectId)) {
      setProjectId(initialProjectId);
    }
  }, [projectId, initialProjectId, projectsQuery.data]);

  const agentVersionsQuery = useAgentVersions(agentId || null);
  const workflowVersionsQuery = useWorkflowVersions(workflowId || null);

  const agentVersions = agentVersionsQuery.data ?? [];
  const workflowVersions: WorkflowVersionResponse[] = workflowVersionsQuery.data ?? [];

  const onSubmit = () => {
    const payload: RemoteTaskSubmitRequest = {
      workspace_id: workspaceId,
      project_id: projectId,
      requirement,
      base_ref: baseRef || null,
    };
    if (agentVersionId) {
      payload.agent_version_id = agentVersionId;
    } else if (workflowVersionId) {
      payload.workflow_version_id = workflowVersionId;
    } else {
      setFeedback(t("remoteTasks.submit.error.versionRequired"));
      return;
    }
    submit.mutate(payload, {
      onSuccess: (result) => {
        setFeedback(t("remoteTasks.submit.submitted", { taskId: result.task_id }));
        onSubmitted(result.task_id);
      },
      onError: (error) => setFeedback(resolveErrorMessage(error)),
    });
  };

  return (
    <Card data-testid="remote-submit-section">
      <CardHeader className="flex-row items-center gap-2 space-y-0 px-3.5 py-2">
        <CardTitle className="text-[13px] font-medium text-primary">
          {t("remoteTasks.submit.title")}
        </CardTitle>
        <span className="text-[10px] text-muted-foreground">
          {t("remoteTasks.submit.subtitle")}
        </span>
      </CardHeader>
      <CardContent className="space-y-2.5 px-3.5 pb-3.5" data-testid="remote-submit-form">
        {feedback ? (
          <p className="text-[11px] text-muted-foreground" data-testid="remote-submit-feedback">
            {feedback}
          </p>
        ) : null}

        <div className="grid grid-cols-1 gap-2.5">
          <div className="space-y-1">
            <Label htmlFor="remote-project" className="text-[11px] text-muted-foreground">
              Project
            </Label>
            <Select value={projectId} onValueChange={setProjectId}>
              <SelectTrigger
                id="remote-project"
                data-testid="remote-project-select"
                className="h-8 text-xs"
              >
                <SelectValue placeholder={t("remoteTasks.submit.projectPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {(projectsQuery.data ?? []).map((project) => (
                  <SelectItem key={project.id} value={project.id}>
                    {project.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="remote-agent" className="text-[11px] text-muted-foreground">
                Agent
              </Label>
              <Select
                value={agentId}
                onValueChange={(next) => {
                  setAgentId(next);
                  setAgentVersionId("");
                  setWorkflowId("");
                  setWorkflowVersionId("");
                }}
              >
                <SelectTrigger
                  id="remote-agent"
                  data-testid="remote-agent-select"
                  className="h-8 text-xs"
                >
                  <SelectValue placeholder={t("remoteTasks.submit.agentPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {(agentsQuery.data ?? []).map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="remote-agent-version" className="text-[11px] text-muted-foreground">
                {t("remoteTasks.submit.agentVersion")}
              </Label>
              <Select value={agentVersionId} disabled={!agentId} onValueChange={setAgentVersionId}>
                <SelectTrigger
                  id="remote-agent-version"
                  data-testid="remote-agent-version-select"
                  className="h-8 text-xs"
                >
                  <SelectValue placeholder={t("remoteTasks.submit.versionPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {agentVersions.map((version) => (
                    <SelectItem key={version.id} value={version.id}>
                      {version.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="remote-workflow" className="text-[11px] text-muted-foreground">
                Workflow
              </Label>
              <Select
                value={workflowId}
                onValueChange={(next) => {
                  setWorkflowId(next);
                  setWorkflowVersionId("");
                  setAgentId("");
                  setAgentVersionId("");
                }}
              >
                <SelectTrigger
                  id="remote-workflow"
                  data-testid="remote-workflow-select"
                  className="h-8 text-xs"
                >
                  <SelectValue placeholder={t("remoteTasks.submit.workflowPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {(workflowsQuery.data ?? []).map((workflow: WorkflowResponse) => (
                    <SelectItem key={workflow.id} value={workflow.id}>
                      {workflow.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label
                htmlFor="remote-workflow-version"
                className="text-[11px] text-muted-foreground"
              >
                {t("remoteTasks.submit.workflowVersion")}
              </Label>
              <Select
                value={workflowVersionId}
                disabled={!workflowId}
                onValueChange={setWorkflowVersionId}
              >
                <SelectTrigger
                  id="remote-workflow-version"
                  data-testid="remote-workflow-version-select"
                  className="h-8 text-xs"
                >
                  <SelectValue placeholder={t("remoteTasks.submit.versionPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {workflowVersions.map((version) => (
                    <SelectItem key={version.id} value={version.id}>
                      {version.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="remote-base-ref" className="text-[11px] text-muted-foreground">
              {t("remoteTasks.submit.baseRef")}
            </Label>
            <Input
              id="remote-base-ref"
              data-testid="remote-base-ref-input"
              className="h-8 font-mono text-xs"
              placeholder="main"
              value={baseRef}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setBaseRef(event.target.value)}
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="remote-requirement" className="text-[11px] text-muted-foreground">
              {t("remoteTasks.submit.requirement")}
            </Label>
            <Input
              id="remote-requirement"
              data-testid="remote-requirement-input"
              className="h-8 text-xs"
              placeholder={t("remoteTasks.submit.requirementPlaceholder")}
              value={requirement}
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                setRequirement(event.target.value)
              }
            />
          </div>
        </div>

        <RequirePermission code="task:submit">
          <Button
            className="h-8 w-full text-xs"
            data-testid="remote-submit-button"
            disabled={submit.isPending || !projectId}
            onClick={onSubmit}
          >
            {t("remoteTasks.submit.title")}
          </Button>
        </RequirePermission>
      </CardContent>
    </Card>
  );
}

/**
 * 项目状态与克隆（M04-04）。
 *
 * ① 项目 Select（本卡独立 `projectId`，未选则**不**发任何请求）；
 * ② `useProjectStatus` → **是否已克隆**（`repo_configured`）/ **默认分支** / **最近克隆任务**
 *    （`clone_task_id`；后端 `ProjectStatusResponse` **无**「最近同步时间」字段，故不自造）；
 * ③ Clone（`202 {task_id}`）→ 文案提示进度见任务中心，pending 时禁用；
 * ④ 分支/标签下拉（`useProjectGitRefs`）→ `refs_available === false` / **503** /
 *    成功但**列表为空** 时 **降级为手填输入框**（不报错），选中/手填的值写入 Clone
 *    payload 的 `base_ref`。
 *
 * 🔴 **敏感值纪律**：本卡**不**展示任何宿主路径 / 凭证。
 */
function ProjectStatusCard({ workspaceId }: { workspaceId: string }) {
  const projectsQuery = useProjects(workspaceId);
  const { t } = useTranslation();
  const [projectId, setProjectId] = useState("");
  const [selectedRef, setSelectedRef] = useState("");
  const [manualRef, setManualRef] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [feedbackIsError, setFeedbackIsError] = useState(false);

  const statusQuery = useProjectStatus(projectId || null);
  const refsQuery = useProjectGitRefs(projectId || null);
  const cloneProject = useCloneProject(projectId || null);

  const status = statusQuery.data;
  const refs = refsQuery.data ?? [];
  /**
   * refs 能力未装配 → 降级手填。三种情形都要降级：
   * ① `refs_available === false`；② 请求 **503**（`isError`）；
   * ③ 请求成功但**列表为空**（`isSuccess && refs.length === 0`）——此时下拉零选项，
   *    若不降级用户**无法**手填分支，Clone 只能用默认分支。
   */
  const refsDegraded =
    refsQuery.isError ||
    status?.refs_available === false ||
    (refsQuery.isSuccess && refs.length === 0);
  /** Clone payload 的 `base_ref`：下拉选中优先，其次手填（空 → `null` 由后端取默认分支）。 */
  const baseRef = (refsDegraded ? manualRef : selectedRef || manualRef).trim();

  const onClone = (): void => {
    if (!projectId) {
      setFeedbackIsError(true);
      setFeedback(t("remoteTasks.projectStatus.error.projectRequired"));
      return;
    }
    cloneProject.mutate(
      { base_ref: baseRef.length > 0 ? baseRef : null },
      {
        onSuccess: (result) => {
          setFeedbackIsError(false);
          setFeedback(t("remoteTasks.projectStatus.cloneSubmitted", { taskId: result.task_id }));
        },
        onError: (error) => {
          setFeedbackIsError(true);
          setFeedback(resolveErrorMessage(error));
        },
      },
    );
  };

  return (
    <Card data-testid="remote-project-status">
      <CardHeader className="flex-row items-center gap-2 space-y-0 px-3.5 py-2">
        <CardTitle className="text-[13px] font-medium text-primary">
          {t("remoteTasks.projectStatus.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2.5 px-3.5 pb-3.5">
        <div className="space-y-1">
          <Label htmlFor="remote-status-project" className="text-[11px] text-muted-foreground">
            Project
          </Label>
          <Select
            value={projectId}
            onValueChange={(next) => {
              setProjectId(next);
              setSelectedRef("");
              setManualRef("");
              setFeedback(null);
              setFeedbackIsError(false);
            }}
          >
            <SelectTrigger
              id="remote-status-project"
              data-testid="remote-project-status-select"
              className="h-8 text-xs"
            >
              <SelectValue placeholder={t("remoteTasks.submit.projectPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {(projectsQuery.data ?? []).map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {!projectId ? (
          <p className="text-xs text-muted-foreground" data-testid="remote-project-status-empty">
            {t("remoteTasks.projectStatus.pickHint")}
          </p>
        ) : (
          <>
            <dl className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
              <div>
                <dt className="text-[10px] text-muted-foreground">
                  {t("remoteTasks.projectStatus.repoLabel")}
                </dt>
                <dd className="mt-0.5 text-[11px]" data-testid="remote-project-repo-state">
                  {!status
                    ? "—"
                    : status.repo_configured
                      ? t("remoteTasks.projectStatus.cloned")
                      : t("remoteTasks.projectStatus.notCloned")}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] text-muted-foreground">
                  {t("remoteTasks.projectStatus.defaultBranch")}
                </dt>
                <dd className="mt-0.5 text-[11px]" data-testid="remote-project-default-branch">
                  {status?.default_branch ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] text-muted-foreground">
                  {t("remoteTasks.projectStatus.cloneTask")}
                </dt>
                <dd
                  className="mt-0.5 font-mono text-[10px]"
                  data-testid="remote-project-clone-task"
                >
                  {status?.clone_task_id ?? "—"}
                </dd>
              </div>
            </dl>

            <div className="space-y-1">
              <Label
                htmlFor="remote-project-base-ref"
                className="text-[11px] text-muted-foreground"
              >
                {t("remoteTasks.projectStatus.refLabel")}
              </Label>
              {refsDegraded ? (
                <Input
                  id="remote-project-base-ref"
                  data-testid="remote-project-ref-input"
                  className="h-8 font-mono text-xs"
                  placeholder={t("remoteTasks.projectStatus.refManualPlaceholder")}
                  value={manualRef}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setManualRef(event.target.value)
                  }
                />
              ) : (
                <Select
                  value={selectedRef}
                  onValueChange={(next) => {
                    setSelectedRef(next);
                    setManualRef("");
                  }}
                >
                  <SelectTrigger
                    id="remote-project-base-ref"
                    data-testid="remote-project-ref-select"
                    className="h-8 text-xs"
                  >
                    <SelectValue
                      placeholder={
                        refsQuery.isLoading
                          ? t("remoteTasks.projectStatus.refsLoading")
                          : t("remoteTasks.projectStatus.refSelectPlaceholder")
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {refs.map((ref) => (
                      <SelectItem key={ref.name} value={ref.name}>
                        {ref.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            <Button
              size="sm"
              className="h-7 text-[11px]"
              data-testid="remote-project-clone-button"
              disabled={cloneProject.isPending}
              onClick={onClone}
            >
              {t("remoteTasks.projectStatus.clone")}
            </Button>
          </>
        )}

        {feedback ? (
          <p
            className={
              feedbackIsError ? "text-[11px] text-destructive" : "text-[11px] text-muted-foreground"
            }
            data-testid="remote-project-clone-feedback"
          >
            {feedback}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * 远程工作台页。
 *
 * 状态：当前工作区 / 当前任务 / 新建项目弹窗与反馈。
 * 布局：页头 → 上下文条 → 左 380 提交 + 项目状态 / 右 1fr 运行视图。
 */
export function RemoteTasks() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const workspacesQuery = useWorkspaces();
  const [searchParams, setSearchParams] = useSearchParams();
  const [workspaceId, setWorkspaceId] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("");
  const [projectFeedback, setProjectFeedback] = useState<string | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const createProject = useCreateProject();
  /** 左列「项目状态与克隆」卡锚点（上下文条按钮滚动定位）。 */
  const statusCardRef = useRef<HTMLDivElement | null>(null);

  const workspaceList = workspacesQuery.data ?? NO_WORKSPACES;
  /** 项目数：与提交卡共用同一 queryKey（**不**新增请求），未加载显示 `—`。 */
  const projectsQuery = useProjects(workspaceId || null);
  const projectCountLabel = projectsQuery.data
    ? t("remoteTasks.projectCount", { count: projectsQuery.data.length })
    : "—";

  /** URL 上下文：项目页「在远程工作台打开」带来的 `?workspace=&project=`。 */
  const queryWorkspaceId = searchParams.get("workspace");
  const queryProjectId = searchParams.get("project");

  // 进入即预选：`?workspace=` 命中已加载工作区时填一次（之后以本地选择为准）。
  useEffect(() => {
    if (workspaceId || !queryWorkspaceId) {
      return;
    }
    if (workspaceList.some((workspace) => workspace.id === queryWorkspaceId)) {
      setWorkspaceId(queryWorkspaceId);
    }
  }, [workspaceId, queryWorkspaceId, workspaceList]);

  /**
   * 手动切换工作区：同步 URL（保留/更新 `workspace`）并**删除 `project`**，
   * 避免把 A 工作区的项目上下文带进 B。
   */
  const handleWorkspaceChange = (next: string): void => {
    setWorkspaceId(next);
    setTaskId(null);
    setProjectFeedback(null);
    const params = new URLSearchParams(searchParams);
    params.delete("project");
    if (next) {
      params.set("workspace", next);
    }
    setSearchParams(params, { replace: true });
  };

  /** 刷新：工作区列表 + 当前工作区项目 + 当前任务的全部派生查询。 */
  const handleRefresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
    if (workspaceId) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(workspaceId) });
    }
    if (taskId) {
      // `["remote-task", id]` 是 snapshot / attempts / logs / events / diff / artifacts 的公共前缀。
      void queryClient.invalidateQueries({ queryKey: queryKeys.remoteTask(taskId) });
    }
  };

  /** 打开新建项目弹窗。 */
  const openCreateProject = (): void => {
    if (!workspaceId) {
      return;
    }
    setProjectName("");
    setRepoUrl("");
    setDefaultBranch("");
    setProjectError(null);
    setCreateOpen(true);
  };

  /** 提交新建项目（失败在弹窗内提示，不关闭）。 */
  const handleCreateProject = (): void => {
    const trimmed = projectName.trim();
    if (!workspaceId) {
      setProjectError(t("remoteTasks.newProject.error.workspaceRequired"));
      return;
    }
    if (!trimmed) {
      setProjectError(t("remoteTasks.newProject.error.nameRequired"));
      return;
    }
    setProjectError(null);
    createProject.mutate(
      {
        name: trimmed,
        workspace_id: workspaceId,
        repo_url: repoUrl.trim() || null,
        default_branch: defaultBranch.trim() || null,
      },
      {
        onSuccess: (project) => {
          setCreateOpen(false);
          setProjectName("");
          setRepoUrl("");
          setDefaultBranch("");
          setProjectFeedback(t("remoteTasks.newProject.created", { name: project.name }));
        },
        onError: (error) => setProjectError(resolveErrorMessage(error)),
      },
    );
  };

  /** 滚动到左列「项目状态与克隆」卡。 */
  const handleJumpToStatus = (): void => {
    statusCardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <PageContainer width="wide">
      <div className="space-y-3" data-testid="remote-tasks">
        {/* ===== 页头 ===== */}
        <div className="flex items-start gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground">{t("remoteTasks.title")}</h1>
            <p className="mt-1 text-xs text-muted-foreground" data-testid="remote-subtitle">
              {t("remoteTasks.subtitle")}
            </p>
          </div>
          <div className="ml-auto flex flex-none items-center gap-2 pt-0.5">
            <button
              type="button"
              data-testid="remote-refresh"
              aria-label={t("remoteTasks.refresh")}
              title={t("remoteTasks.refresh")}
              onClick={handleRefresh}
              className={ICON_BUTTON_CLASS}
            >
              <RefreshCw aria-hidden className="h-4 w-4" />
            </button>
            <Link
              to="/workspace"
              data-testid="remote-goto-workspace"
              className={GHOST_ACTION_CLASS}
            >
              {t("remoteTasks.gotoWorkspace")}
            </Link>
          </div>
        </div>

        {workspacesQuery.isLoading ? (
          <div className={cn(CARD_SHELL_CLASS, "p-3.5")} data-testid="remote-workspaces-loading">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="mt-2 h-8 w-full" />
          </div>
        ) : workspaceList.length === 0 ? (
          /* ===== 空态：无工作区（CTA 可点，非聊天 chips）===== */
          <div className={cn(CARD_SHELL_CLASS, "px-3.5 py-6")}>
            <InlineEmpty
              icon={FolderKanban}
              title={t("remoteTasks.workspaces.empty.title")}
              description={t("remoteTasks.workspaces.empty.description")}
              testId="remote-workspaces-empty"
              action={
                <div className="flex flex-wrap items-center justify-center gap-2">
                  <Link
                    to="/workspace"
                    data-testid="remote-workspaces-empty-cta"
                    className={GHOST_ACTION_CLASS}
                  >
                    {t("remoteTasks.workspaces.empty.cta")}
                  </Link>
                  <button
                    type="button"
                    data-testid="remote-workspaces-empty-refresh"
                    onClick={handleRefresh}
                    className={GHOST_ACTION_CLASS}
                  >
                    {t("remoteTasks.refresh")}
                  </button>
                </div>
              }
            />
          </div>
        ) : (
          <>
            {/* ===== 工作区上下文条 ===== */}
            <div
              className={cn(CARD_SHELL_CLASS, "flex flex-wrap items-center gap-2 px-3 py-2")}
              data-testid="remote-context-bar"
            >
              <span className="text-[11px] text-muted-foreground">
                {t("remoteTasks.workspace.label")}
              </span>
              <div className="w-[220px]">
                <Select value={workspaceId} onValueChange={handleWorkspaceChange}>
                  <SelectTrigger
                    id="remote-workspace"
                    data-testid="remote-workspace-select"
                    className="h-7 text-xs"
                  >
                    <SelectValue placeholder={t("remoteTasks.workspace.placeholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {workspaceList.map((workspace) => (
                      <SelectItem key={workspace.id} value={workspace.id}>
                        {workspace.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <span
                className="text-[11px] text-muted-foreground"
                data-testid="remote-project-count"
              >
                {projectCountLabel}
              </span>
              <div className="ml-auto flex flex-none items-center gap-2">
                <RequirePermission code="project:create" fallback={null}>
                  <button
                    type="button"
                    data-testid="remote-new-project-open"
                    onClick={openCreateProject}
                    disabled={!workspaceId}
                    title={
                      workspaceId ? undefined : t("remoteTasks.newProject.error.workspaceRequired")
                    }

                    className={GHOST_ACTION_CLASS}
                  >
                    <Plus aria-hidden className="h-3 w-3" />
                    {t("remoteTasks.newProject.title")}
                  </button>
                </RequirePermission>
                <button
                  type="button"
                  data-testid="remote-project-status-anchor"
                  onClick={handleJumpToStatus}
                  className={GHOST_ACTION_CLASS}
                >
                  <GitBranch aria-hidden className="h-3 w-3" />
                  {t("remoteTasks.projectStatus.anchor")}
                </button>
              </div>
              {projectFeedback ? (
                <p
                  className="w-full text-[11px] text-[#3C6650]"
                  data-testid="remote-project-feedback"
                >
                  {projectFeedback}
                </p>
              ) : null}
            </div>

            {!workspaceId ? (
              <div className={cn(CARD_SHELL_CLASS, "px-3.5 py-6")}>
                <InlineEmpty
                  icon={FolderKanban}
                  title={t("remoteTasks.workspace.placeholder")}
                  description={t("remoteTasks.workspace.hintDescription")}
                  testId="remote-workspace-hint"
                />
              </div>
            ) : (
              /* ===== 两栏：左提交 + 项目状态 / 右运行视图 ===== */
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-[380px_1fr]">
                <div className="space-y-3">
                  <SubmitPanel
                    workspaceId={workspaceId}
                    initialProjectId={queryProjectId}
                    onSubmitted={(id) => setTaskId(id)}
                  />
                  <div ref={statusCardRef}>
                    <ProjectStatusCard workspaceId={workspaceId} />
                  </div>
                </div>

                <div className="min-w-0">
                  {taskId ? (
                    <TaskWorkbench taskId={taskId} />
                  ) : (
                    <div className={cn(CARD_SHELL_CLASS, "px-3.5 py-10")}>
                      <InlineEmpty
                        icon={Rocket}
                        title={t("remoteTasks.task.empty.title")}
                        description={t("remoteTasks.task.empty.description")}
                        testId="remote-task-empty"
                      />
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        {/* ===== 新建项目弹窗 ===== */}
        <Dialog
          open={createOpen}
          onOpenChange={(open) => {
            setCreateOpen(open);
            if (!open) {
              setProjectError(null);
            }
          }}
        >
          <DialogContent data-testid="remote-new-project-dialog" className="max-w-md">
            <DialogHeader>
              <DialogTitle>{t("remoteTasks.newProject.title")}</DialogTitle>
              <DialogDescription>{t("remoteTasks.newProject.description")}</DialogDescription>
            </DialogHeader>

            <div className="space-y-2.5">
              <div className="space-y-1">
                <Label
                  htmlFor="remote-new-project-name"
                  className="text-[11px] text-muted-foreground"
                >
                  {t("remoteTasks.newProject.name")}
                </Label>
                <Input
                  id="remote-new-project-name"
                  data-testid="remote-new-project-name"
                  className="h-8 text-xs"
                  value={projectName}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setProjectName(event.target.value)
                  }
                />
              </div>
              <div className="space-y-1">
                <Label
                  htmlFor="remote-new-project-repo"
                  className="text-[11px] text-muted-foreground"
                >
                  {t("remoteTasks.newProject.repo")}
                </Label>
                <Input
                  id="remote-new-project-repo"
                  data-testid="remote-new-project-repo"
                  className="h-8 font-mono text-xs"
                  placeholder="https://git.example.com/repo.git"
                  value={repoUrl}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setRepoUrl(event.target.value)
                  }
                />
              </div>
              <div className="space-y-1">
                <Label
                  htmlFor="remote-new-project-branch"
                  className="text-[11px] text-muted-foreground"
                >
                  {t("remoteTasks.projectStatus.defaultBranch")}
                </Label>
                <Input
                  id="remote-new-project-branch"
                  data-testid="remote-new-project-branch"
                  className="h-8 font-mono text-xs"
                  placeholder="main"
                  value={defaultBranch}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setDefaultBranch(event.target.value)
                  }
                />
              </div>
              {projectError ? (
                <p className="text-[11px] text-[#A84452]" data-testid="remote-new-project-error">
                  {projectError}
                </p>
              ) : null}
            </div>

            <DialogFooter>
              <button
                type="button"
                className={GHOST_ACTION_CLASS}
                onClick={() => setCreateOpen(false)}
              >
                {t("common.cancel")}
              </button>
              <RequirePermission code="project:create">
                <Button
                  size="sm"
                  className="h-7 text-[11px]"
                  data-testid="remote-create-project-button"
                  disabled={createProject.isPending}
                  onClick={handleCreateProject}
                >
                  {t("remoteTasks.newProject.submit")}
                </Button>
              </RequirePermission>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </PageContainer>
  );
}
