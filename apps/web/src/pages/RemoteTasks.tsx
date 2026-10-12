import { useMemo, useState } from "react";
import type { ChangeEvent } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { toApiError } from "@/lib/api";
import type {
  RemoteTaskSubmitRequest,
  TaskAttemptResponse,
  WorkflowResponse,
  WorkflowVersionResponse,
} from "@/types";

/**
 * RemoteTasks（R4 / T2-62；U-P2-41 / #41 / D17–D18）——远程工作台。
 *
 * 四区：
 * ① **Project / Workspace 选择 + 创建**（`repo_url` / `default_branch`）；
 * ② **远程提交**：固定 Agent / Workflow 版本 + 目标 Ref + 需求 + 资源限额；
 * ③ **运行视图**：状态 / Attempt 时间线 / 日志 / 事件（**断点续读**）/ Diff / Artifact；
 * ④ **显式变更**：**Apply**（不 Push）与**独立** **Push**，各自权限守卫。
 *
 * 🔴 **冻结路径**：Apply / Push 经 `remoteTaskService.apply|push`（`/tasks/{id}/apply` · `/push`），
 *    **禁止** `/diff/apply`。
 * 🔴 **敏感值纪律**：本页**不**渲染宿主路径 / Token / 凭证；仅展示不透明 `checkout_ref` 与提交哈希。
 * 🔴 **降级**：Diff 读取以 `available` 标志降级（200）；Artifact 下载 / Apply / Push 未装配 → **503**
 *    （`DEPENDENCY_MISSING`）；两种降级均渲染降级文案（**不**伪造）。
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

/** 运行视图：状态 / Attempt / 日志 / 事件（断点续读）/ Diff / Artifact / 变更操作。 */
function TaskWorkbench({ taskId }: { taskId: string }) {
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

  const snapshot = taskQuery.data;
  const attempts: TaskAttemptResponse[] = attemptsQuery.data ?? [];
  const events = eventsQuery.data?.events ?? [];
  const logs = logsQuery.data ?? [];

  /** Apply / Push 的 payload（`target_ref` 空 → 由后端取默认分支）。 */
  const changePayload = useMemo(
    () => (targetRef.trim() ? { target_ref: targetRef.trim() } : {}),
    [targetRef],
  );

  return (
    <div className="space-y-4" data-testid="remote-task-detail">
      {feedback ? (
        <p className="text-xs text-muted-foreground" data-testid="remote-change-feedback">
          {feedback}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>运行状态</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!snapshot ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <dt className="text-xs text-muted-foreground">状态</dt>
                <dd>
                  <Badge variant={statusVariant(snapshot.status)} data-testid="remote-task-status">
                    {snapshot.status}
                  </Badge>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Attempt 数</dt>
                <dd className="text-sm">{snapshot.attempt_count}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">checkout_ref</dt>
                <dd className="font-mono text-xs" data-testid="remote-task-checkout-ref">
                  {snapshot.checkout_ref ?? "—"}
                </dd>
              </div>
            </dl>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="remote-target-ref">目标分支（Apply / Push）</Label>
              <Input
                id="remote-target-ref"
                data-testid="remote-target-ref-input"
                placeholder="默认取 Project default_branch"
                value={targetRef}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  setTargetRef(event.target.value)
                }
              />
            </div>
            <RequirePermission code="git:apply">
              <Button
                size="sm"
                data-testid="remote-apply-button"
                disabled={applyChange.isPending}
                onClick={() =>
                  applyChange.mutate(changePayload, {
                    onSuccess: (result) =>
                      setFeedback(
                        result.already_applied
                          ? `目标分支已包含结果提交（${result.applied_commit ?? ""}）`
                          : `已应用到 ${result.target_ref}（${result.applied_commit ?? ""}）`,
                      ),
                    onError: (error) => setFeedback(resolveErrorMessage(error)),
                  })
                }
              >
                应用到目标分支（不 Push）
              </Button>
            </RequirePermission>
            <RequirePermission code="git:push">
              <Button
                size="sm"
                variant="outline"
                data-testid="remote-push-button"
                disabled={pushChange.isPending}
                onClick={() =>
                  pushChange.mutate(
                    { ...changePayload, remote: "origin" },
                    {
                      onSuccess: (result) =>
                        setFeedback(
                          result.already_up_to_date
                            ? "远端已是最新（无需推送）"
                            : `已推送 ${result.ref}`,
                        ),
                      onError: (error) => setFeedback(resolveErrorMessage(error)),
                    },
                  )
                }
              >
                推送到远端（独立权限）
              </Button>
            </RequirePermission>
            <RequirePermission code="task:cancel">
              <Button
                size="sm"
                variant="ghost"
                data-testid="remote-cancel-button"
                disabled={cancelTask.isPending}
                onClick={() =>
                  cancelTask.mutate(undefined, {
                    onSuccess: (updated) => setFeedback(`已请求取消（${updated.status}）`),
                    onError: (error) => setFeedback(resolveErrorMessage(error)),
                  })
                }
              >
                取消任务
              </Button>
            </RequirePermission>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Attempt 时间线</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>尝试</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>耗时 (ms)</TableHead>
                <TableHead className="text-right">审阅</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {attempts.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground"
                    data-testid="remote-attempts-empty"
                  >
                    暂无 Attempt
                  </TableCell>
                </TableRow>
              ) : (
                attempts.map((attempt) => (
                  <TableRow
                    key={attempt.attempt}
                    data-testid={`remote-attempt-row-${attempt.attempt}`}
                  >
                    <TableCell>{attempt.attempt}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(attempt.status)}>{attempt.status}</Badge>
                    </TableCell>
                    <TableCell>{attempt.duration_ms ?? "N/A"}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid={`remote-attempt-select-${attempt.attempt}`}
                        onClick={() => setSelectedAttempt(attempt.attempt)}
                      >
                        审阅
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Diff 与 Artifact</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div data-testid="remote-diff">
            {diffQuery.isError || diffQuery.data?.available === false ? (
              <p className="text-sm text-muted-foreground" data-testid="remote-diff-degraded">
                Diff 不可用（能力未装配或缺少可比较提交）
              </p>
            ) : diffQuery.data && diffQuery.data.files.length > 0 ? (
              <ul className="space-y-1 text-sm">
                {diffQuery.data.files.map((file) => (
                  <li
                    key={file.path}
                    className="font-mono text-xs"
                    data-testid={`remote-diff-file-${file.path}`}
                  >
                    <Badge variant="outline">{file.change_type}</Badge> {file.path}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground" data-testid="remote-diff-empty">
                {diffQuery.isLoading ? "加载中…" : "无变更（或选择 Attempt 后查看）"}
              </p>
            )}
          </div>

          <div data-testid="remote-artifacts">
            {artifactsQuery.isError ? (
              <p className="text-sm text-muted-foreground" data-testid="remote-artifacts-degraded">
                Artifact 能力未装配（DEPENDENCY_MISSING）
              </p>
            ) : (artifactsQuery.data ?? []).length > 0 ? (
              <ul className="space-y-1 text-sm">
                {(artifactsQuery.data ?? []).map((artifact) => (
                  <li
                    key={artifact.name}
                    className="font-mono text-xs"
                    data-testid={`remote-artifact-${artifact.name}`}
                  >
                    {artifact.name}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground" data-testid="remote-artifacts-empty">
                暂无 Artifact
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>事件（断点续读）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div data-testid="remote-events">
            {events.length === 0 ? (
              <p className="text-sm text-muted-foreground" data-testid="remote-events-empty">
                暂无事件
              </p>
            ) : (
              <ul className="space-y-1 text-sm">
                {events.map((event) => (
                  <li
                    key={event.seq}
                    className="font-mono text-xs"
                    data-testid={`remote-event-${event.seq}`}
                  >
                    #{event.seq} {event.type}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {eventsQuery.isError ? (
            <p className="text-xs text-destructive" data-testid="remote-events-error">
              {resolveErrorMessage(eventsQuery.error)}
            </p>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            data-testid="remote-events-resume"
            disabled={eventsQuery.isFetching}
            onClick={() => {
              const next = eventsQuery.data?.next_cursor;
              setCursor(next && next.length > 0 ? next : null);
            }}
          >
            续读
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>日志</CardTitle>
        </CardHeader>
        <CardContent>
          <div data-testid="remote-logs">
            {logs.length === 0 ? (
              <p className="text-sm text-muted-foreground" data-testid="remote-logs-empty">
                暂无日志
              </p>
            ) : (
              <ul className="space-y-1 text-xs">
                {logs.map((line) => (
                  <li key={line.seq} className="font-mono" data-testid={`remote-log-${line.seq}`}>
                    [{line.level}] {line.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/** 提交表单：固定 Agent / Workflow 版本。 */
function SubmitPanel({
  workspaceId,
  onSubmitted,
}: {
  workspaceId: string;
  onSubmitted: (taskId: string) => void;
}) {
  const projectsQuery = useProjects(workspaceId);
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
      setFeedback("请选择 Agent 版本或 Workflow 版本之一");
      return;
    }
    submit.mutate(payload, {
      onSuccess: (result) => {
        setFeedback(`已提交（task ${result.task_id}）`);
        onSubmitted(result.task_id);
      },
      onError: (error) => setFeedback(resolveErrorMessage(error)),
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>远程提交</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3" data-testid="remote-submit-form">
        {feedback ? (
          <p className="text-xs text-muted-foreground" data-testid="remote-submit-feedback">
            {feedback}
          </p>
        ) : null}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="remote-project">Project</Label>
            <select
              id="remote-project"
              data-testid="remote-project-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
            >
              <option value="">选择项目</option>
              {(projectsQuery.data ?? []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="remote-agent">Agent</Label>
            <select
              id="remote-agent"
              data-testid="remote-agent-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={agentId}
              onChange={(event) => {
                setAgentId(event.target.value);
                setAgentVersionId("");
                setWorkflowId("");
                setWorkflowVersionId("");
              }}
            >
              <option value="">（不使用 Agent）</option>
              {(agentsQuery.data ?? []).map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="remote-agent-version">Agent 版本</Label>
            <select
              id="remote-agent-version"
              data-testid="remote-agent-version-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={agentVersionId}
              disabled={!agentId}
              onChange={(event) => setAgentVersionId(event.target.value)}
            >
              <option value="">选择版本</option>
              {agentVersions.map((version) => (
                <option key={version.id} value={version.id}>
                  {version.version}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="remote-workflow">Workflow</Label>
            <select
              id="remote-workflow"
              data-testid="remote-workflow-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={workflowId}
              onChange={(event) => {
                setWorkflowId(event.target.value);
                setWorkflowVersionId("");
                setAgentId("");
                setAgentVersionId("");
              }}
            >
              <option value="">（不使用 Workflow）</option>
              {(workflowsQuery.data ?? []).map((workflow: WorkflowResponse) => (
                <option key={workflow.id} value={workflow.id}>
                  {workflow.name}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="remote-workflow-version">Workflow 版本</Label>
            <select
              id="remote-workflow-version"
              data-testid="remote-workflow-version-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={workflowVersionId}
              disabled={!workflowId}
              onChange={(event) => setWorkflowVersionId(event.target.value)}
            >
              <option value="">选择版本</option>
              {workflowVersions.map((version) => (
                <option key={version.id} value={version.id}>
                  {version.version}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="remote-base-ref">目标 Ref</Label>
            <Input
              id="remote-base-ref"
              data-testid="remote-base-ref-input"
              placeholder="main"
              value={baseRef}
              onChange={(event: ChangeEvent<HTMLInputElement>) => setBaseRef(event.target.value)}
            />
          </div>
        </div>

        <div className="space-y-1">
          <Label htmlFor="remote-requirement">需求</Label>
          <Input
            id="remote-requirement"
            data-testid="remote-requirement-input"
            placeholder="描述要让 Agent 完成的需求"
            value={requirement}
            onChange={(event: ChangeEvent<HTMLInputElement>) => setRequirement(event.target.value)}
          />
        </div>

        <RequirePermission code="task:submit">
          <Button
            data-testid="remote-submit-button"
            disabled={submit.isPending || !projectId}
            onClick={onSubmit}
          >
            提交远程任务
          </Button>
        </RequirePermission>
      </CardContent>
    </Card>
  );
}

export function RemoteTasks() {
  const workspacesQuery = useWorkspaces();
  const [workspaceId, setWorkspaceId] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("");
  const createProject = useCreateProject();
  const [projectFeedback, setProjectFeedback] = useState<string | null>(null);

  return (
    <div className="space-y-4" data-testid="remote-tasks">
      <h1 className="text-lg font-semibold">Remote Workbench</h1>

      <Card>
        <CardHeader>
          <CardTitle>工作区与项目</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="remote-workspace">工作区</Label>
            <select
              id="remote-workspace"
              data-testid="remote-workspace-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={workspaceId}
              onChange={(event) => {
                setWorkspaceId(event.target.value);
                setTaskId(null);
              }}
            >
              <option value="">选择工作区</option>
              {(workspacesQuery.data ?? []).map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </div>

          {workspaceId ? (
            <div className="grid grid-cols-1 gap-3 rounded-md border border-dashed p-3 sm:grid-cols-3">
              {projectFeedback ? (
                <p
                  className="col-span-full text-xs text-muted-foreground"
                  data-testid="remote-project-feedback"
                >
                  {projectFeedback}
                </p>
              ) : null}
              <div className="space-y-1">
                <Label htmlFor="remote-new-project-name">新项目名称</Label>
                <Input
                  id="remote-new-project-name"
                  data-testid="remote-new-project-name"
                  value={projectName}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setProjectName(event.target.value)
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="remote-new-project-repo">仓库地址</Label>
                <Input
                  id="remote-new-project-repo"
                  data-testid="remote-new-project-repo"
                  placeholder="https://git.example.com/repo.git"
                  value={repoUrl}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setRepoUrl(event.target.value)
                  }
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="remote-new-project-branch">默认分支</Label>
                <Input
                  id="remote-new-project-branch"
                  data-testid="remote-new-project-branch"
                  placeholder="main"
                  value={defaultBranch}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setDefaultBranch(event.target.value)
                  }
                />
              </div>
              <RequirePermission code="project:create">
                <Button
                  size="sm"
                  data-testid="remote-create-project-button"
                  disabled={createProject.isPending || !projectName}
                  onClick={() =>
                    createProject.mutate(
                      {
                        name: projectName,
                        workspace_id: workspaceId,
                        repo_url: repoUrl || null,
                        default_branch: defaultBranch || null,
                      },
                      {
                        onSuccess: (project) => setProjectFeedback(`已创建项目 ${project.name}`),
                        onError: (error) => setProjectFeedback(resolveErrorMessage(error)),
                      },
                    )
                  }
                >
                  创建项目
                </Button>
              </RequirePermission>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {workspaceId ? (
        <SubmitPanel workspaceId={workspaceId} onSubmitted={(id) => setTaskId(id)} />
      ) : null}

      {taskId ? <TaskWorkbench taskId={taskId} /> : null}
    </div>
  );
}
