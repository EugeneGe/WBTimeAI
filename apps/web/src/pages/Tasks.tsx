import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useSchedules, useTriggerSchedule } from "@/hooks/useSchedules";
import { useCancelTask, useTask, useTaskExecutions, useTasks } from "@/hooks/useTasks";
import { toApiError } from "@/lib/api";
import type { TaskResponse } from "@/types";

/**
 * Tasks（W10 / T2-50；裁定 R-W10-11）。
 *
 * 三区：
 * ① **任务列表**（`task_type` / `status` 过滤）；
 * ② **任务详情 + 执行历史**（`task_execution`，attempt / 状态 / 耗时）+ **取消**（终态禁用）；
 * ③ **Schedules 区**（调度列表 + 可选手动触发）。
 *
 * 🔴 终态（`SUCCESS` / `FAILED` / `CANCELLED`）取消按钮禁用（后端幂等，前端亦不触发）。
 */

/** 终态集合（不可取消）。 */
const TERMINAL_STATUSES: readonly string[] = ["SUCCESS", "FAILED", "CANCELLED"];

/** 提取可展示错误消息。 */
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

/** 任务详情 + 执行历史（含取消）。 */
function TaskDetail({ taskId }: { taskId: string }) {
  const detailQuery = useTask(taskId);
  const executionsQuery = useTaskExecutions(taskId);
  const cancelTask = useCancelTask();
  const [feedback, setFeedback] = useState<string | null>(null);

  const task = detailQuery.data;
  const executions = executionsQuery.data ?? [];
  const isTerminal = task ? TERMINAL_STATUSES.includes(task.status) : false;

  if (!task) {
    return <p className="text-sm text-muted-foreground">加载中…</p>;
  }

  return (
    <div className="space-y-4" data-testid="task-detail">
      {feedback ? (
        <p className="text-xs text-muted-foreground" data-testid="task-detail-feedback">
          {feedback}
        </p>
      ) : null}

      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">类型</dt>
          <dd className="font-mono text-sm" data-testid="task-type">
            {task.type}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">状态</dt>
          <dd>
            <Badge variant={statusVariant(task.status)} data-testid="task-status">
              {task.status}
            </Badge>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">执行模式</dt>
          <dd className="text-sm">{task.execution_mode}</dd>
        </div>
      </dl>

      <RequirePermission code="task:cancel">
        <Button
          size="sm"
          variant="outline"
          data-testid="task-cancel-button"
          disabled={isTerminal || cancelTask.isPending}
          onClick={() =>
            cancelTask.mutate(taskId, {
              onSuccess: (updated) => setFeedback(`已请求取消（${updated.status}）`),
              onError: (error) => setFeedback(resolveErrorMessage(error)),
            })
          }
        >
          取消任务
        </Button>
      </RequirePermission>

      <div data-testid="task-executions">
        <h2 className="mb-2 text-sm font-medium">执行历史</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>尝试</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>耗时 (ms)</TableHead>
              <TableHead>错误</TableHead>
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
                  暂无执行记录
                </TableCell>
              </TableRow>
            ) : (
              executions.map((record) => (
                <TableRow key={record.id} data-testid={`execution-row-${record.attempt}`}>
                  <TableCell>{record.attempt}</TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(record.status)}>{record.status}</Badge>
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

export function Tasks() {
  const [taskType, setTaskType] = useState("");
  const [status, setStatus] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const tasksQuery = useTasks({
    task_type: taskType || null,
    status: status || null,
  });
  const schedulesQuery = useSchedules();
  const triggerSchedule = useTriggerSchedule();

  const tasks: TaskResponse[] = tasksQuery.data ?? [];
  const schedules = schedulesQuery.data ?? [];

  return (
    <div className="space-y-4" data-testid="tasks">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Tasks</h1>
        {feedback ? (
          <span className="text-xs text-muted-foreground" data-testid="tasks-feedback">
            {feedback}
          </span>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>任务列表</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="task-type">任务类型</Label>
              <select
                id="task-type"
                data-testid="task-type-filter"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={taskType}
                onChange={(event) => setTaskType(event.target.value)}
              >
                <option value="">全部</option>
                <option value="agent.run">agent.run</option>
                <option value="project.clone">project.clone</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="task-status">状态</Label>
              <select
                id="task-status"
                data-testid="task-status-filter"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                <option value="">全部</option>
                <option value="CREATED">CREATED</option>
                <option value="PENDING">PENDING</option>
                <option value="RUNNING">RUNNING</option>
                <option value="SUCCESS">SUCCESS</option>
                <option value="FAILED">FAILED</option>
                <option value="CANCELLED">CANCELLED</option>
              </select>
            </div>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>类型</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>优先级</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasksQuery.isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : tasks.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground"
                    data-testid="tasks-empty"
                  >
                    暂无任务
                  </TableCell>
                </TableRow>
              ) : (
                tasks.map((task) => (
                  <TableRow key={task.id} data-testid={`task-row-${task.id}`}>
                    <TableCell className="font-mono text-xs">{task.type}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(task.status)}>{task.status}</Badge>
                    </TableCell>
                    <TableCell>{task.priority}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid={`task-select-${task.id}`}
                        onClick={() => setSelectedTaskId(task.id)}
                      >
                        详情
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          {selectedTaskId ? <TaskDetail taskId={selectedTaskId} /> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Schedules</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {schedulesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : schedules.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="schedules-empty">
              暂无调度
            </p>
          ) : (
            <div data-testid="schedules-list">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>目标</TableHead>
                    <TableHead>触发</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {schedules.map((schedule) => (
                    <TableRow key={schedule.id} data-testid={`schedule-row-${schedule.id}`}>
                      <TableCell>{schedule.name}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {schedule.target_type}:{schedule.target_id}
                      </TableCell>
                      <TableCell>{schedule.trigger}</TableCell>
                      <TableCell className="text-right">
                        <RequirePermission code="schedule:trigger">
                          <Button
                            variant="ghost"
                            size="sm"
                            data-testid={`schedule-trigger-${schedule.id}`}
                            disabled={triggerSchedule.isPending}
                            onClick={() =>
                              triggerSchedule.mutate(schedule.id, {
                                onSuccess: (result) =>
                                  setFeedback(`已触发调度（task ${result.task_id}）`),
                                onError: (error) => setFeedback(resolveErrorMessage(error)),
                              })
                            }
                          >
                            触发
                          </Button>
                        </RequirePermission>
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
  );
}
