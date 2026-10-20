import { useQueryClient } from "@tanstack/react-query";
import { Clock, ListChecks, Plus, RefreshCw } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

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
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateSchedule,
  useDeleteSchedule,
  useSchedules,
  useTriggerSchedule,
  useUpdateSchedule,
} from "@/hooks/useSchedules";
import { useCancelTask, useTask, useTaskExecutions, useTasks } from "@/hooks/useTasks";
import { useTranslation } from "@/i18n";
import type { TranslationParams } from "@/i18n";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { queryKeys } from "@/lib/query";
import type { ScheduleResponse, TaskResponse } from "@/types";

/**
 * Tasks（任务中心；D-UI 体验优化波 · WS-P1 / #11 → **B-20 UI 优化 + 调度 CRUD**）。
 *
 * 三区（自上而下）：
 * ① **任务列表**：页头范式对齐「专家与智能体」；工具条两个定宽过滤 Select（变更即刷新）；
 *    列集 `任务 / 类型 / 执行模式 / 状态 / 优先级 / 创建时间 / 操作`；
 *    状态为自绘胶囊（圆点 + 文案，语义四色）；空态为**内联**空态（非 `EmptyState`）；
 * ② **任务详情**（就地展开，非弹窗）：键值 6 格 + 执行历史 + 取消（终态禁用）；
 * ③ **定时调度**：列表（目标 / 触发 / 启用开关 / 上次·下次）+ 新建 / 编辑 / 删除。
 *
 * 🔴 终态（`SUCCESS` / `FAILED` / `CANCELLED`）取消按钮禁用（后端幂等，前端亦不触发）。
 * 🔴 「启用」开关走 `PUT /schedules/{id}`（**部分更新**，只传 `{enabled}`）；失败仅本行提示。
 * 🔴 调度目标（`target_type` / `target_id`）**创建后不可改**：`UpdateScheduleRequest` 不含该两字段，
 *    编辑弹窗内两字段 `disabled` 并注明原因。
 */

/** 终态集合（不可取消）。 */
const TERMINAL_STATUSES: readonly string[] = ["SUCCESS", "FAILED", "CANCELLED"];

/** 任务类型过滤选项。 */
const TASK_TYPE_OPTIONS: readonly string[] = ["agent.run", "project.clone"];

/** 状态过滤选项。 */
const STATUS_OPTIONS: readonly string[] = [
  "CREATED",
  "PENDING",
  "RUNNING",
  "SUCCESS",
  "FAILED",
  "CANCELLED",
];

/** 目标类型选项（`agent` 为后端默认值）。 */
const TARGET_TYPE_OPTIONS: readonly string[] = ["agent", "workflow"];

/** 触发方式选项。 */
const TRIGGER_OPTIONS: readonly string[] = ["cron", "event", "webhook", "manual"];

/** 「全部」哨兵值（Radix `SelectItem` 不接受空串 `value`，故用哨兵映射回空串）。 */
const ALL_VALUE = "__all__";

/** 翻译函数签名（非组件 helper 经参数接收，**不**在模块顶层取 `t`）。 */
type Translate = (key: string, params?: TranslationParams) => string;

/** 提取可展示错误消息（优先后端 `message`）。 */
function resolveErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.length > 0) {
      return message;
    }
  }
  return toApiError(error).message;
}

/** 两位补零。 */
function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** 时间格式化：`MM-DD HH:mm`（**本地时区**；空值 / 非法值 → `—`）。 */
function formatTimestamp(value?: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(
    date.getMinutes(),
  )}`;
}

/** 短 id（`#` + 末 4 位；完整 id 走 `title`）。 */
function shortId(id: string): string {
  return `#${id.slice(-4)}`;
}

/** 状态视觉基调（圆点色 / 胶囊底色 + 文字色）。 */
interface StatusTone {
  /** 圆点背景类。 */
  dot: string;
  /** 胶囊底色 + 文字色。 */
  pill: string;
}

/** 语义四色（成功=绿 / 运行中=金 / 失败=红 / 其余=灰）。 */
const STATUS_TONES: Record<string, StatusTone> = {
  SUCCESS: { dot: "bg-[#4A7C63]", pill: "bg-[#EDF4F0] text-[#3C6650]" },
  RUNNING: { dot: "bg-[#F5B941]", pill: "bg-[#FDF8EC] text-[#8A6322]" },
  FAILED: { dot: "bg-[#A84452]", pill: "bg-[#FBEEF0] text-[#8F3A47]" },
};

/** 中性基调（`CREATED` / `PENDING` / `CANCELLED` / 未知态）。 */
const NEUTRAL_TONE: StatusTone = { dot: "bg-[#97A2B8]", pill: "bg-[#F1F4F9] text-[#5A6478]" };

/** 任务状态胶囊（圆点 + 文案 + 浅底）。 */
function TaskStatusBadge({ status, testId }: { status: string; testId?: string }) {
  const tone = STATUS_TONES[status] ?? NEUTRAL_TONE;
  return (
    <span
      data-testid={testId}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium leading-4",
        tone.pill,
      )}
    >
      <span aria-hidden className={cn("h-1.5 w-1.5 flex-none rounded-full", tone.dot)} />
      {status}
    </span>
  );
}

/**
 * 任务来源判定：**`project_id` 非空 → 远程**（后端 `routers/v1/tasks.py::_is_remote_task`
 * 的真实判据；`execution_mode` 只有 `INLINE` / `QUEUED`，**不可**用来区分来源）。
 *
 * 🔴 两种列表口径都要覆盖：
 * - 不按项目过滤（`_to_task_response`）：`payload.project_id` 有值，`project_id` 字段缺省；
 * - 按项目过滤（`_to_remote_view_as_task`）：顶层 `project_id` 有值，**不带** payload。
 */
function isRemoteTask(task: TaskResponse): boolean {
  const payload = task.payload as Record<string, unknown> | undefined;
  return Boolean(task.project_id ?? payload?.project_id);
}

/** 来源徽标（本地=雾蓝底墨蓝字 / 远程=墨蓝底白字）。 */
function TaskSourceBadge({ task }: { task: TaskResponse }) {
  const { t } = useTranslation();
  const remote = isRemoteTask(task);
  return (
    <span
      data-testid={`task-source-${task.id}`}
      className={cn(
        "inline-flex flex-none items-center rounded-full px-2 py-0.5 text-[10px] font-medium leading-4",
        remote ? "bg-primary text-primary-foreground" : "bg-secondary text-primary",
      )}
    >
      {remote ? t("tasks.source.remote") : t("tasks.source.local")}
    </span>
  );
}

/** 内联空态（图标底 + 13px 标题 + 11px 说明 + 可选动作；**非** `EmptyState`）。 */
function InlineEmpty({
  icon,
  title,
  description,
  action,
  testId,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action: ReactNode;
  testId: string;
}) {
  return (
    <div data-testid={testId} className="flex flex-col items-center gap-1 py-6 text-center">
      <div
        aria-hidden
        className="mb-1 flex h-[34px] w-[34px] items-center justify-center rounded-lg bg-secondary text-muted-foreground"
      >
        {icon}
      </div>
      <p className="text-[13px] font-medium text-foreground">{title}</p>
      <p className="text-[11px] text-muted-foreground">{description}</p>
      <div className="mt-1.5">{action}</div>
    </div>
  );
}

/**
 * 调度「启用」开关单元（行内独立状态；失败只在本行提示）。
 *
 * 🔴 走 `PUT /schedules/{id}` **部分更新**，只传 `{enabled}`；不使用 `<Switch>` 之外的交互。
 */
function ScheduleEnabledCell({ schedule }: { schedule: ScheduleResponse }) {
  const { t } = useTranslation();
  const updateSchedule = useUpdateSchedule();
  const [feedback, setFeedback] = useState<string | null>(null);

  const handleToggle = (next: boolean): void => {
    setFeedback(null);
    updateSchedule.mutate(
      { id: schedule.id, enabled: next },
      { onError: () => setFeedback(t("tasks.schedules.toggle.failed")) },
    );
  };

  return (
    <div className="flex items-center gap-2">
      <Switch
        checked={schedule.enabled}
        onCheckedChange={handleToggle}
        disabled={updateSchedule.isPending}
        aria-label={
          schedule.enabled
            ? t("tasks.schedules.toggle.disable")
            : t("tasks.schedules.toggle.enable")
        }
        data-testid={`schedule-toggle-${schedule.id}`}
      />
      {feedback ? (
        <span
          className="text-[11px] text-[#8F3A47]"
          data-testid={`schedule-toggle-error-${schedule.id}`}
        >
          {feedback}
        </span>
      ) : null}
    </div>
  );
}

/**
 * 触发方式展示文案（`cron · 0 2 * * *` / `事件 · pr.merged` / `Webhook` / `手动`）。
 *
 * 🔴 非组件 helper：`t` 由调用方以**参数**传入（模块顶层不得取 `t`）。
 * `cron` / `Webhook` 为技术标识，不翻译。
 */
function describeTrigger(schedule: ScheduleResponse, t: Translate): string {
  if (schedule.trigger === "cron") {
    return `cron · ${schedule.cron ?? "—"}`;
  }
  if (schedule.trigger === "event") {
    return t("tasks.schedules.triggerEvent", { eventType: schedule.event_type ?? "—" });
  }
  if (schedule.trigger === "webhook") {
    return "Webhook";
  }
  return t("tasks.schedules.triggerManual");
}

/** `TaskResponse` 的 R3 加性字段 `attempt_count`（后端已返回，前端 DTO 尚未收录）。 */
type TaskWithAttempts = TaskResponse & { attempt_count?: number | null };

/** 任务详情 + 执行历史（就地展开的灰底内嵌面板）。 */
function TaskDetail({ taskId, onCollapse }: { taskId: string; onCollapse: () => void }) {
  const { t } = useTranslation();
  const detailQuery = useTask(taskId);
  const executionsQuery = useTaskExecutions(taskId);
  const cancelTask = useCancelTask();
  const [feedback, setFeedback] = useState<string | null>(null);

  const task = detailQuery.data;
  const executions = executionsQuery.data ?? [];
  const isTerminal = task ? TERMINAL_STATUSES.includes(task.status) : false;

  if (!task) {
    return (
      <div
        className="mt-3 space-y-2 rounded-lg border bg-[#FBFCFE] p-3"
        data-testid="task-detail-loading"
      >
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-9 w-full" />
      </div>
    );
  }

  const attemptCount = (task as TaskWithAttempts).attempt_count ?? "—";

  return (
    <div className="mt-3 rounded-lg border bg-[#FBFCFE] p-3" data-testid="task-detail">
      <div className="flex items-center gap-2">
        <span className="flex-none text-xs font-medium text-foreground">
          {t("tasks.detail.title")}
        </span>
        <span
          className="min-w-0 truncate font-mono text-[10px] text-muted-foreground"
          title={task.id}
        >
          {task.id}
        </span>
        <div className="ml-auto flex flex-none items-center gap-1.5">
          <RequirePermission
            code="task:cancel"
            fallback={
              <span className="text-[11px] text-muted-foreground">
                {t("common.permissionDenied", { code: "task:cancel" })}
              </span>
            }
          >
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2 text-[11px]"
              data-testid="task-cancel-button"
              disabled={isTerminal || cancelTask.isPending}
              onClick={() =>
                cancelTask.mutate(taskId, {
                  onSuccess: (updated) =>
                    setFeedback(t("tasks.detail.cancelRequested", { status: updated.status })),
                  onError: (error) => setFeedback(resolveErrorMessage(error)),
                })
              }
            >
              {t("tasks.detail.cancel")}
            </Button>
          </RequirePermission>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11px] text-muted-foreground"
            data-testid="task-detail-collapse"
            onClick={onCollapse}
          >
            {t("tasks.detail.collapse")}
          </Button>
        </div>
      </div>

      {feedback ? (
        <p className="mt-2 text-[11px] text-muted-foreground" data-testid="task-detail-feedback">
          {feedback}
        </p>
      ) : null}

      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div>
          <dt className="text-[11px] text-muted-foreground">{t("tasks.field.type")}</dt>
          <dd className="font-mono text-xs text-foreground" data-testid="task-type">
            {task.type}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-muted-foreground">{t("tasks.field.status")}</dt>
          <dd>
            <TaskStatusBadge status={task.status} testId="task-status" />
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-muted-foreground">{t("tasks.field.executionMode")}</dt>
          <dd className="font-mono text-xs text-foreground">{task.execution_mode}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-muted-foreground">{t("tasks.field.priority")}</dt>
          <dd className="text-xs text-foreground">{task.priority}</dd>
        </div>
        <div>
          <dt className="text-[11px] text-muted-foreground">{t("tasks.field.attemptCount")}</dt>
          <dd className="text-xs text-foreground" data-testid="task-attempt-count">
            {attemptCount}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-muted-foreground">{t("tasks.field.createdAt")}</dt>
          <dd className="text-xs text-foreground" data-testid="task-created-at">
            {formatTimestamp(task.created_at)}
          </dd>
        </div>
      </dl>

      <div className="mt-3" data-testid="task-executions">
        <h3 className="mb-2 text-[11px] font-medium text-muted-foreground">
          {t("tasks.executions.title")}
        </h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("tasks.field.attempt")}</TableHead>
              <TableHead>{t("tasks.field.status")}</TableHead>
              <TableHead>{t("tasks.field.durationMs")}</TableHead>
              <TableHead>{t("tasks.field.error")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {executions.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="text-muted-foreground"
                  data-testid="task-executions-empty"
                >
                  {t("tasks.executions.empty")}
                </TableCell>
              </TableRow>
            ) : (
              executions.map((record) => (
                <TableRow key={record.id} data-testid={`execution-row-${record.attempt}`}>
                  <TableCell>{record.attempt}</TableCell>
                  <TableCell>
                    <TaskStatusBadge status={record.status} />
                  </TableCell>
                  <TableCell>{record.duration_ms ?? "N/A"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {record.error ?? "—"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/** 调度表单状态（弹窗内部，`payload` 以文本保存待提交时解析）。 */
interface ScheduleFormState {
  name: string;
  targetType: string;
  targetId: string;
  trigger: string;
  cron: string;
  eventType: string;
  payloadText: string;
  enabled: boolean;
}

/** 由既有调度（或空）构造表单初始值。 */
function toFormState(schedule: ScheduleResponse | null): ScheduleFormState {
  if (!schedule) {
    return {
      name: "",
      targetType: "agent",
      targetId: "",
      trigger: "manual",
      cron: "",
      eventType: "",
      payloadText: "{}",
      enabled: true,
    };
  }
  return {
    name: schedule.name,
    targetType: schedule.target_type,
    targetId: schedule.target_id,
    trigger: schedule.trigger,
    cron: schedule.cron ?? "",
    eventType: schedule.event_type ?? "",
    payloadText: JSON.stringify(schedule.payload ?? {}, null, 2),
    enabled: schedule.enabled,
  };
}

/** payload 文本结构非法（非 JSON 对象）——由组件映射为 i18n 文案。 */
class PayloadNotObjectError extends Error {
  /** 构造（无固定 message：文案由调用方按语言取）。 */
  constructor() {
    super("payload must be a JSON object");
    this.name = "PayloadNotObjectError";
  }
}

/** 解析 payload 文本：必须是 JSON **对象**（数组 / 标量 / 非法 JSON → 抛错）。 */
function parsePayload(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  const raw = trimmed === "" ? "{}" : trimmed;
  const parsed: unknown = JSON.parse(raw);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new PayloadNotObjectError();
  }
  return parsed as Record<string, unknown>;
}

/**
 * 新建 / 编辑调度弹窗（受控；编辑态目标两字段 `disabled`）。
 *
 * 🔴 新建 → `POST /schedules`；编辑 → `PUT /schedules/{id}`（**不含** `target_type` / `target_id`）。
 * 🔴 `cron` 与 `event_type` 二选一：不适用的一侧**显式传 `null`**，避免切换触发方式后残留旧值。
 */
function ScheduleDialog({
  schedule,
  onClose,
  onSaved,
}: {
  schedule: ScheduleResponse | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const isEdit = schedule !== null;
  const { t } = useTranslation();
  const [form, setForm] = useState<ScheduleFormState>(() => toFormState(schedule));
  const [error, setError] = useState<string | null>(null);
  const createSchedule = useCreateSchedule();
  const updateSchedule = useUpdateSchedule();
  const isPending = createSchedule.isPending || updateSchedule.isPending;

  const patch = (next: Partial<ScheduleFormState>): void => {
    setForm((prev) => ({ ...prev, ...next }));
  };

  const handleSubmit = (): void => {
    setError(null);

    const name = form.name.trim();
    if (name.length === 0) {
      setError(t("tasks.scheduleDialog.error.nameRequired"));
      return;
    }
    const targetId = form.targetId.trim();
    if (targetId.length === 0) {
      setError(t("tasks.scheduleDialog.error.targetIdRequired"));
      return;
    }
    if (form.trigger === "cron" && form.cron.trim().length === 0) {
      setError(t("tasks.scheduleDialog.error.cronRequired"));
      return;
    }
    if (form.trigger === "event" && form.eventType.trim().length === 0) {
      setError(t("tasks.scheduleDialog.error.eventTypeRequired"));
      return;
    }

    let payload: Record<string, unknown>;
    try {
      payload = parsePayload(form.payloadText);
    } catch (parseError) {
      setError(
        parseError instanceof PayloadNotObjectError
          ? t("tasks.scheduleDialog.error.payloadNotObject")
          : t("tasks.scheduleDialog.error.payloadInvalid"),
      );
      return;
    }

    const cron = form.trigger === "cron" ? form.cron.trim() : null;
    const eventType = form.trigger === "event" ? form.eventType.trim() : null;

    if (isEdit) {
      updateSchedule.mutate(
        {
          id: schedule.id,
          name,
          trigger: form.trigger,
          cron,
          event_type: eventType,
          payload,
          enabled: form.enabled,
        },
        {
          onSuccess: () => onSaved(t("tasks.scheduleDialog.saved.updated")),
          onError: (submitError) => setError(resolveErrorMessage(submitError)),
        },
      );
      return;
    }

    createSchedule.mutate(
      {
        name,
        target_type: form.targetType,
        target_id: targetId,
        trigger: form.trigger,
        cron,
        event_type: eventType,
        payload,
        enabled: form.enabled,
      },
      {
        onSuccess: () => onSaved(t("tasks.scheduleDialog.saved.created")),
        onError: (submitError) => setError(resolveErrorMessage(submitError)),
      },
    );
  };

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) {
          onClose();
        }
      }}
    >
      <DialogContent data-testid="schedule-dialog" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">
            {isEdit ? t("tasks.scheduleDialog.title.edit") : t("tasks.scheduleDialog.title.create")}
          </DialogTitle>
          <DialogDescription className="text-[11px] text-muted-foreground">
            {isEdit
              ? t("tasks.scheduleDialog.description.edit")
              : t("tasks.scheduleDialog.description.create")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="schedule-name" className="text-[11px] text-muted-foreground">
              {t("tasks.field.name")} <span className="text-[#8F3A47]">*</span>
            </Label>
            <Input
              id="schedule-name"
              data-testid="schedule-dialog-name"
              className="h-8 text-xs"
              placeholder={t("tasks.scheduleDialog.name.placeholder")}
              value={form.name}
              onChange={(event) => patch({ name: event.target.value })}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="schedule-target-type" className="text-[11px] text-muted-foreground">
                {t("tasks.field.targetType")}
              </Label>
              <Select
                value={form.targetType}
                onValueChange={(value) => patch({ targetType: value })}
                disabled={isEdit}
              >
                <SelectTrigger
                  id="schedule-target-type"
                  size="sm"
                  className="h-8"
                  data-testid="schedule-dialog-target-type"
                >
                  <SelectValue placeholder="agent" />
                </SelectTrigger>
                <SelectContent>
                  {TARGET_TYPE_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="schedule-target-id" className="text-[11px] text-muted-foreground">
                {t("tasks.field.targetId")} <span className="text-[#8F3A47]">*</span>
              </Label>
              <Input
                id="schedule-target-id"
                data-testid="schedule-dialog-target-id"
                className="h-8 font-mono text-xs"
                placeholder="agt_21"
                value={form.targetId}
                disabled={isEdit}
                onChange={(event) => patch({ targetId: event.target.value })}
              />
            </div>
          </div>

          {isEdit ? (
            <p
              className="text-[10px] text-muted-foreground"
              data-testid="schedule-dialog-target-hint"
            >
              {t("tasks.scheduleDialog.targetImmutableHint")}
            </p>
          ) : null}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="schedule-trigger" className="text-[11px] text-muted-foreground">
                {t("tasks.field.triggerType")}
              </Label>
              <Select value={form.trigger} onValueChange={(value) => patch({ trigger: value })}>
                <SelectTrigger
                  id="schedule-trigger"
                  size="sm"
                  className="h-8"
                  data-testid="schedule-dialog-trigger"
                >
                  <SelectValue placeholder="manual" />
                </SelectTrigger>
                <SelectContent>
                  {TRIGGER_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="schedule-enabled" className="text-[11px] text-muted-foreground">
                {t("tasks.field.enabled")}
              </Label>
              <div className="flex h-8 items-center">
                <Switch
                  checked={form.enabled}
                  onCheckedChange={(next) => patch({ enabled: next })}
                  aria-label={
                    form.enabled
                      ? t("tasks.schedules.toggle.disable")
                      : t("tasks.schedules.toggle.enable")
                  }
                  data-testid="schedule-dialog-enabled"
                />
              </div>
            </div>
          </div>

          {form.trigger === "cron" ? (
            <div className="space-y-1">
              <Label htmlFor="schedule-cron" className="text-[11px] text-muted-foreground">
                {t("tasks.field.cron")} <span className="text-[#8F3A47]">*</span>
              </Label>
              <Input
                id="schedule-cron"
                data-testid="schedule-dialog-cron"
                className="h-8 font-mono text-xs"
                placeholder="0 2 * * *"
                value={form.cron}
                onChange={(event) => patch({ cron: event.target.value })}
              />
            </div>
          ) : null}

          {form.trigger === "event" ? (
            <div className="space-y-1">
              <Label htmlFor="schedule-event" className="text-[11px] text-muted-foreground">
                {t("tasks.field.eventType")} <span className="text-[#8F3A47]">*</span>
              </Label>
              <Input
                id="schedule-event"
                data-testid="schedule-dialog-event"
                className="h-8 font-mono text-xs"
                placeholder="pr.merged"
                value={form.eventType}
                onChange={(event) => patch({ eventType: event.target.value })}
              />
            </div>
          ) : null}

          <div className="space-y-1">
            <Label htmlFor="schedule-payload" className="text-[11px] text-muted-foreground">
              {t("tasks.field.payload")}
            </Label>
            <textarea
              id="schedule-payload"
              data-testid="schedule-dialog-payload"
              rows={4}
              spellCheck={false}
              className="flex min-h-[84px] w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              placeholder="{}"
              value={form.payloadText}
              onChange={(event) => patch({ payloadText: event.target.value })}
            />
          </div>

          {error ? (
            <p className="text-[11px] text-[#8F3A47]" data-testid="schedule-dialog-error">
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <Button size="sm" variant="outline" onClick={onClose} disabled={isPending}>
            {t("common.cancel")}
          </Button>
          <Button
            size="sm"
            data-testid="schedule-dialog-submit"
            disabled={isPending}
            onClick={handleSubmit}
          >
            {isEdit ? t("common.save") : t("tasks.scheduleDialog.submit.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 删除调度二次确认弹窗（不可恢复提示 + 名称 / 触发描述）。 */
function ScheduleDeleteDialog({
  schedule,
  onClose,
  onDeleted,
}: {
  schedule: ScheduleResponse;
  onClose: () => void;
  onDeleted: (message: string) => void;
}) {
  const deleteSchedule = useDeleteSchedule();
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) {
          onClose();
        }
      }}
    >
      <DialogContent data-testid="schedule-delete-dialog" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">
            {t("tasks.deleteDialog.title")}
          </DialogTitle>
          <DialogDescription className="text-[11px] text-muted-foreground">
            {t("tasks.deleteDialog.description")}
          </DialogDescription>
        </DialogHeader>

        <dl className="space-y-1 rounded-lg border bg-[#FBFCFE] p-3">
          <div className="flex items-center gap-2">
            <dt className="flex-none text-[11px] text-muted-foreground">{t("tasks.field.name")}</dt>
            <dd
              className="min-w-0 truncate text-xs text-foreground"
              data-testid="schedule-delete-name"
            >
              {schedule.name}
            </dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="flex-none text-[11px] text-muted-foreground">
              {t("tasks.field.trigger")}
            </dt>
            <dd className="min-w-0 truncate font-mono text-[11px] text-foreground">
              {describeTrigger(schedule, t)}
            </dd>
          </div>
        </dl>

        {error ? (
          <p className="text-[11px] text-[#8F3A47]" data-testid="schedule-delete-error">
            {error}
          </p>
        ) : null}

        <DialogFooter>
          <Button size="sm" variant="outline" onClick={onClose} disabled={deleteSchedule.isPending}>
            {t("common.cancel")}
          </Button>
          <Button
            size="sm"
            variant="destructive"
            data-testid="schedule-delete-confirm"
            disabled={deleteSchedule.isPending}
            onClick={() =>
              deleteSchedule.mutate(schedule.id, {
                onSuccess: () => onDeleted(t("tasks.deleteDialog.deleted")),
                onError: (deleteError) => setError(resolveErrorMessage(deleteError)),
              })
            }
          >
            {t("tasks.action.delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function Tasks() {
  const { t } = useTranslation();
  const [taskType, setTaskType] = useState("");
  const [status, setStatus] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<ScheduleResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ScheduleResponse | null>(null);

  const tasksQuery = useTasks({
    task_type: taskType || null,
    status: status || null,
  });
  const schedulesQuery = useSchedules();
  const triggerSchedule = useTriggerSchedule();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const tasks: TaskResponse[] = tasksQuery.data ?? [];
  const schedules = schedulesQuery.data ?? [];
  const enabledCount = schedules.filter((schedule) => schedule.enabled).length;

  /** 手动刷新：同时失效任务列表（含各过滤组合）与调度列表。 */
  const handleRefresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.schedules });
  };

  const openCreate = (): void => {
    setEditingSchedule(null);
    setDialogOpen(true);
  };

  const openEdit = (schedule: ScheduleResponse): void => {
    setEditingSchedule(schedule);
    setDialogOpen(true);
  };

  const handleSaved = (message: string): void => {
    setDialogOpen(false);
    setFeedback(message);
  };

  const handleDeleted = (message: string): void => {
    setDeleteTarget(null);
    setFeedback(message);
  };

  return (
    <PageContainer width="default">
      <div className="space-y-3" data-testid="tasks">
        {/* ===== 页头：标题 + 计数副标题 + 反馈位 + 刷新 ===== */}
        <div className="flex items-start gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground">{t("tasks.title")}</h1>
            <p className="mt-1 text-xs text-muted-foreground" data-testid="tasks-subtitle">
              {t("tasks.subtitle", {
                taskCount: tasks.length,
                scheduleCount: schedules.length,
                enabledCount,
              })}
            </p>
          </div>
          <div className="ml-auto flex flex-none items-center gap-2 pt-0.5">
            {feedback ? (
              <span className="text-[11px] text-muted-foreground" data-testid="tasks-feedback">
                {feedback}
              </span>
            ) : null}
            <button
              type="button"
              data-testid="tasks-refresh"
              aria-label={t("tasks.refresh")}
              title={t("tasks.refresh")}
              onClick={handleRefresh}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-input bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <RefreshCw aria-hidden className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* ===== ① 任务列表 ===== */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 px-4 pb-2 pt-4">
            <CardTitle className="text-sm font-semibold text-foreground">
              {t("tasks.list.title")}
            </CardTitle>
            <span className="text-[11px] text-muted-foreground" data-testid="tasks-count">
              {t("tasks.list.count", { count: tasks.length })}
            </span>
          </CardHeader>
          <CardContent className="space-y-3 px-4 pb-4 pt-0">
            {/* 工具条：两个定宽 Select（变更即刷新，无查询按钮 / 无防抖）。 */}
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={taskType === "" ? ALL_VALUE : taskType}
                onValueChange={(value) => setTaskType(value === ALL_VALUE ? "" : value)}
              >
                <SelectTrigger
                  size="sm"
                  className="h-8 w-[150px] text-xs"
                  aria-label={t("tasks.filter.type.label")}
                  data-testid="task-type-filter"
                >
                  <SelectValue placeholder={t("tasks.filter.type.all")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_VALUE}>{t("tasks.filter.type.all")}</SelectItem>
                  {TASK_TYPE_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select
                value={status === "" ? ALL_VALUE : status}
                onValueChange={(value) => setStatus(value === ALL_VALUE ? "" : value)}
              >
                <SelectTrigger
                  size="sm"
                  className="h-8 w-[132px] text-xs"
                  aria-label={t("tasks.filter.status.label")}
                  data-testid="task-status-filter"
                >
                  <SelectValue placeholder={t("tasks.filter.status.all")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_VALUE}>{t("tasks.filter.status.all")}</SelectItem>
                  {STATUS_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <span className="ml-auto text-[11px] text-muted-foreground">
                {t("tasks.filter.hint")}
              </span>
            </div>

            {tasksQuery.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, index) => (
                  <Skeleton key={index} className="h-9 w-full" />
                ))}
              </div>
            ) : tasks.length === 0 ? (
              <InlineEmpty
                testId="tasks-empty"
                icon={<ListChecks className="h-4 w-4" />}
                title={t("tasks.empty.title")}
                description={t("tasks.empty.description")}
                action={
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px]"
                    data-testid="tasks-empty-cta"
                    onClick={() => navigate("/remote-tasks")}
                  >
                    {t("tasks.empty.cta")}
                  </Button>
                }
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("tasks.field.task")}</TableHead>
                    <TableHead>{t("tasks.field.type")}</TableHead>
                    <TableHead>{t("tasks.field.executionMode")}</TableHead>
                    <TableHead>{t("tasks.field.status")}</TableHead>
                    <TableHead>{t("tasks.field.priority")}</TableHead>
                    <TableHead>{t("tasks.field.createdAt")}</TableHead>
                    <TableHead className="text-right">{t("tasks.field.actions")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tasks.map((task) => (
                    <TableRow key={task.id} data-testid={`task-row-${task.id}`}>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          {/* 来源徽标（10px）：`project_id` 非空 → 远程，其余 → 本地。 */}
                          <TaskSourceBadge task={task} />
                          <span
                            className="font-mono text-[11px] text-muted-foreground"
                            title={task.id}
                          >
                            {shortId(task.id)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-[11px] text-foreground">
                        {task.type}
                      </TableCell>
                      <TableCell>
                        {/* 执行模式列按真实值渲染（`INLINE` / `QUEUED`），**不**映射为来源。 */}
                        <Badge
                          variant="outline"
                          className="font-mono text-[10px] font-medium leading-4"
                          data-testid={`task-execution-mode-${task.id}`}
                        >
                          {task.execution_mode}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <TaskStatusBadge status={task.status} testId={`task-status-${task.id}`} />
                      </TableCell>
                      <TableCell className="text-xs text-foreground">{task.priority}</TableCell>
                      <TableCell className="text-[11px] text-[#5A6478]">
                        {formatTimestamp(task.created_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        {/* 远程任务（`project_id` 非空）可直达审阅工作台；本地任务只有「详情」。 */}
                        {isRemoteTask(task) ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-[11px]"
                            data-testid={`task-review-${task.id}`}
                            onClick={() => navigate("/remote-tasks")}
                          >
                            {t("tasks.action.review")}
                          </Button>
                        ) : null}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-[11px]"
                          data-testid={`task-select-${task.id}`}
                          onClick={() => setSelectedTaskId(task.id)}
                        >
                          {t("tasks.action.detail")}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}

            {selectedTaskId ? (
              <TaskDetail taskId={selectedTaskId} onCollapse={() => setSelectedTaskId(null)} />
            ) : null}
          </CardContent>
        </Card>

        {/* ===== ② 定时调度 ===== */}
        <Card>
          <CardHeader className="flex flex-row items-center gap-2 space-y-0 px-4 pb-2 pt-4">
            <CardTitle className="text-sm font-semibold text-foreground">
              {t("tasks.schedules.title")}
            </CardTitle>
            <span
              className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground"
              data-testid="schedules-count"
            >
              {t("tasks.schedules.count", {
                count: schedules.length,
                enabledCount,
              })}
            </span>
            <Button
              size="sm"
              className="ml-auto h-8 text-[11px]"
              data-testid="schedule-create-open"
              onClick={openCreate}
            >
              <Plus aria-hidden className="h-3.5 w-3.5" />
              {t("tasks.schedules.create")}
            </Button>
          </CardHeader>
          <CardContent className="px-4 pb-4 pt-0">
            {schedulesQuery.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 2 }).map((_, index) => (
                  <Skeleton key={index} className="h-9 w-full" />
                ))}
              </div>
            ) : schedules.length === 0 ? (
              <InlineEmpty
                testId="schedules-empty"
                icon={<Clock className="h-4 w-4" />}
                title={t("tasks.schedules.empty.title")}
                description={t("tasks.schedules.empty.description")}
                action={
                  <Button
                    variant="link"
                    size="sm"
                    className="h-6 p-0 text-[11px]"
                    data-testid="schedule-create-open-empty"
                    onClick={openCreate}
                  >
                    {t("tasks.schedules.empty.cta")}
                  </Button>
                }
              />
            ) : (
              <div data-testid="schedules-list">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("tasks.field.name")}</TableHead>
                      <TableHead>{t("tasks.field.target")}</TableHead>
                      <TableHead>{t("tasks.field.trigger")}</TableHead>
                      <TableHead>{t("tasks.field.enabled")}</TableHead>
                      <TableHead>{t("tasks.field.lastNextRun")}</TableHead>
                      <TableHead className="text-right">{t("tasks.field.actions")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {schedules.map((schedule) => (
                      <TableRow key={schedule.id} data-testid={`schedule-row-${schedule.id}`}>
                        <TableCell className="text-xs text-foreground">{schedule.name}</TableCell>
                        <TableCell className="font-mono text-[11px] text-muted-foreground">
                          {schedule.target_type} · {schedule.target_id}
                        </TableCell>
                        <TableCell className="font-mono text-[11px] text-muted-foreground">
                          {describeTrigger(schedule, t)}
                        </TableCell>
                        <TableCell>
                          {/* 启用开关（`PUT /schedules/{id}`；行内独立失败提示）。 */}
                          <ScheduleEnabledCell schedule={schedule} />
                        </TableCell>
                        <TableCell className="font-mono text-[10px] text-muted-foreground">
                          {formatTimestamp(schedule.last_run_at)} ·{" "}
                          {formatTimestamp(schedule.next_run_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <RequirePermission code="schedule:trigger">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 px-2 text-[11px]"
                              data-testid={`schedule-trigger-${schedule.id}`}
                              disabled={triggerSchedule.isPending}
                              onClick={() =>
                                triggerSchedule.mutate(schedule.id, {
                                  onSuccess: (result) =>
                                    setFeedback(
                                      t("tasks.schedules.triggered", { taskId: result.task_id }),
                                    ),
                                  onError: (error) => setFeedback(resolveErrorMessage(error)),
                                })
                              }
                            >
                              {t("tasks.schedules.triggerNow")}
                            </Button>
                          </RequirePermission>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-[11px]"
                            data-testid={`schedule-edit-${schedule.id}`}
                            onClick={() => openEdit(schedule)}
                          >
                            {t("tasks.action.edit")}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-[11px] text-[#8F3A47] hover:text-[#8F3A47]"
                            data-testid={`schedule-delete-${schedule.id}`}
                            onClick={() => setDeleteTarget(schedule)}
                          >
                            {t("tasks.action.delete")}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ===== 新建 / 编辑 / 删除弹窗（受控；打开即挂载以重置表单） ===== */}
      {dialogOpen ? (
        <ScheduleDialog
          key={editingSchedule?.id ?? "new"}
          schedule={editingSchedule}
          onClose={() => setDialogOpen(false)}
          onSaved={handleSaved}
        />
      ) : null}

      {deleteTarget ? (
        <ScheduleDeleteDialog
          schedule={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={handleDeleted}
        />
      ) : null}
    </PageContainer>
  );
}
