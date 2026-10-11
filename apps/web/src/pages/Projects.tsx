import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

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
import {
  useCreateProject,
  useProject,
  useProjects,
  useWorkspaceEnvironment,
  useWorkspaceEnvironments,
  useWorkspaceFiles,
} from "@/hooks/useProjects";
import { useWorkspaces } from "@/hooks/useWorkspaces";
import { toApiError } from "@/lib/api";
import { projectService } from "@/services/project";
import type { ApiError, EnvironmentResponse, ProjectResponse } from "@/types";

/**
 * Projects（W10 / T2-50；裁定 R-W10-11 + W10-E1）。
 *
 * 三区：
 * ① **Project 列表 + 创建**（Workspace 选择器驱动；`workspace_id` 必填）；
 * ② **详情面板**——Project 元信息 + 文件浏览器 + Environment 面板；
 * ③ **Git 面板（W10-E1 冻结口径）**——仅展示 Project 元信息 + 降级标注，
 *    **禁止伪造实时 Git 状态 / 禁止绕过 Sandbox / 禁止前端直连 git**。
 *
 * 🔴 文件能力未装配（缺 `Storage`）→ 后端 **503** → 文件区渲染降级态，不视为空。
 * 🔴 Environment 敏感项（`masked=true`）**只读展示引用**（`ref`），**禁**明文展示 / 输入。
 */

/** 提取可展示错误消息（`lib/api.ts` 已归一化为 `ApiError`）。 */
function resolveErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.length > 0) {
      return message;
    }
  }
  return toApiError(error).message;
}

/** 判定是否为「能力未装配」降级（503 / `DEPENDENCY_MISSING`）。 */
function isUnavailable(error: unknown): boolean {
  if (error && typeof error === "object" && "code" in error) {
    const candidate = error as ApiError;
    return candidate.status === 503 || candidate.code === "DEPENDENCY_MISSING";
  }
  return false;
}

/** 尝试把 base64 预览解码为文本；失败则回退展示原文（二进制安全）。 */
function decodeBase64Text(encoded: string): string {
  try {
    return atob(encoded);
  } catch {
    return encoded;
  }
}

/** 文件浏览器（`prefix` 过滤 + 内容预览；未装配 → 降级态）。 */
function FilesPanel({ workspaceId }: { workspaceId: string | null }) {
  const [prefix, setPrefix] = useState("");
  const [previewPath, setPreviewPath] = useState<string | null>(null);

  const filesQuery = useWorkspaceFiles(workspaceId, prefix);
  const contentQuery = useQuery({
    queryKey: ["workspace", workspaceId ?? "", "file-content", previewPath ?? ""],
    queryFn: () => projectService.readFile(workspaceId as string, previewPath as string),
    enabled: Boolean(workspaceId) && Boolean(previewPath),
    retry: false,
  });

  const unavailable = filesQuery.isError && isUnavailable(filesQuery.error);
  const files = filesQuery.data ?? [];

  return (
    <div className="space-y-3" data-testid="files-panel">
      <div className="flex items-end gap-2">
        <div className="flex-1 space-y-1">
          <Label htmlFor="files-prefix">路径前缀</Label>
          <Input
            id="files-prefix"
            data-testid="files-prefix-input"
            value={prefix}
            placeholder="（可空）如 src/"
            onChange={(event) => setPrefix(event.target.value)}
          />
        </div>
      </div>

      {unavailable ? (
        <div
          className="rounded-md border border-dashed p-3 text-xs text-muted-foreground"
          data-testid="files-degrade"
        >
          文件能力未装配（需 Storage）
        </div>
      ) : filesQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : filesQuery.isError ? (
        <p className="text-sm text-destructive" data-testid="files-error">
          {resolveErrorMessage(filesQuery.error)}
        </p>
      ) : files.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="files-empty">
          暂无文件
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>对象键</TableHead>
              <TableHead>大小</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {files.map((file) => (
              <TableRow key={file.key} data-testid={`file-row-${file.key}`}>
                <TableCell className="font-mono text-xs">{file.key}</TableCell>
                <TableCell>{file.size}</TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid={`file-preview-${file.key}`}
                    onClick={() => setPreviewPath(file.key)}
                  >
                    预览
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {previewPath ? (
        <div className="rounded-md border p-3" data-testid="file-preview">
          <div className="mb-2 text-xs text-muted-foreground">{previewPath}</div>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs">
            {contentQuery.isLoading
              ? "加载中…"
              : contentQuery.isError
                ? resolveErrorMessage(contentQuery.error)
                : decodeBase64Text(contentQuery.data?.content_base64 ?? "")}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

/** Environment 面板（列表 + 详情；敏感项只读引用）。 */
function EnvironmentPanel({ workspaceId }: { workspaceId: string | null }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const envsQuery = useWorkspaceEnvironments(workspaceId);
  const detailQuery = useWorkspaceEnvironment(workspaceId, selectedId);

  const envs: EnvironmentResponse[] = envsQuery.data ?? [];
  const detail = detailQuery.data;

  return (
    <div className="space-y-3" data-testid="environment-panel">
      {envsQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : envs.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="environment-empty">
          暂无运行环境
        </p>
      ) : (
        <ul className="space-y-1" data-testid="environment-list">
          {envs.map((env) => (
            <li key={env.id}>
              <button
                type="button"
                className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-accent"
                data-testid={`environment-row-${env.id}`}
                onClick={() => setSelectedId(env.id)}
              >
                <span className="truncate">{env.name}</span>
                {selectedId === env.id ? <Badge variant="secondary">选中</Badge> : null}
              </button>
            </li>
          ))}
        </ul>
      )}

      {detail ? (
        <div className="space-y-2 rounded-md border p-3" data-testid="environment-detail">
          <div className="text-sm font-medium">{detail.name}</div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>变量</TableHead>
                <TableHead>值 / 引用</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.env_vars.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={2} className="text-muted-foreground">
                    暂无变量
                  </TableCell>
                </TableRow>
              ) : (
                detail.env_vars.map((item) => (
                  <TableRow key={item.name} data-testid={`env-var-${item.name}`}>
                    <TableCell className="font-mono text-xs">{item.name}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {item.masked ? (
                        <span data-testid={`env-var-ref-${item.name}`}>
                          {item.ref ?? "（敏感引用）"}
                          <span className="ml-1 text-muted-foreground">（敏感，只读引用）</span>
                        </span>
                      ) : (
                        <span data-testid={`env-var-value-${item.name}`}>{item.value}</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}

/** Git 面板（W10-E1：仅元信息 + 降级标注；不伪造实时状态）。 */
function GitPanel({ project }: { project: ProjectResponse }) {
  return (
    <div className="space-y-2 rounded-md border p-3" data-testid="project-git-panel">
      <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
        <div>
          <div className="text-muted-foreground">仓库地址</div>
          <div className="font-mono" data-testid="project-repo-url">
            {project.repo_url ?? "—"}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">默认分支</div>
          <div className="font-mono" data-testid="project-default-branch">
            {project.default_branch ?? "—"}
          </div>
        </div>
      </div>
      <pre
        className="max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2 font-mono text-xs"
        data-testid="project-settings"
      >
        {JSON.stringify(project.settings ?? {}, null, 2)}
      </pre>
      <p className="text-xs text-muted-foreground" data-testid="project-git-degrade">
        实时 Git 状态需 Sandbox 装配（R1/R3 增量）
      </p>
    </div>
  );
}

export function Projects() {
  const { data: workspaces } = useWorkspaces();
  const [workspaceId, setWorkspaceId] = useState<string>("");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);

  const projectsQuery = useProjects(workspaceId || null);
  const detailQuery = useProject(selectedProjectId);
  const createProject = useCreateProject();

  const projects = projectsQuery.data ?? [];
  const selectedProject = detailQuery.data;

  const handleCreate = (): void => {
    if (!workspaceId) {
      setFeedback("请先选择工作区");
      return;
    }
    if (!name.trim()) {
      setFeedback("请填写项目名称");
      return;
    }
    createProject.mutate(
      { name: name.trim(), workspace_id: workspaceId },
      {
        onSuccess: (project) => {
          setName("");
          setSelectedProjectId(project.id);
          setFeedback(`已创建项目 ${project.name}`);
        },
        onError: (error) => setFeedback(resolveErrorMessage(error)),
      },
    );
  };

  return (
    <div className="space-y-4" data-testid="projects">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Projects</h1>
        {feedback ? (
          <span className="text-xs text-muted-foreground" data-testid="projects-feedback">
            {feedback}
          </span>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>工作区</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="max-w-xs space-y-1">
            <Label htmlFor="workspace-select">工作区</Label>
            <select
              id="workspace-select"
              data-testid="workspace-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={workspaceId}
              onChange={(event) => {
                setWorkspaceId(event.target.value);
                setSelectedProjectId(null);
              }}
            >
              <option value="">请选择</option>
              {(workspaces ?? []).map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>仓库</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!workspaceId ? (
                <TableRow>
                  <TableCell
                    colSpan={3}
                    className="text-muted-foreground"
                    data-testid="projects-hint"
                  >
                    请先选择工作区
                  </TableCell>
                </TableRow>
              ) : projectsQuery.isLoading ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-muted-foreground">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : projects.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={3}
                    className="text-muted-foreground"
                    data-testid="projects-empty"
                  >
                    暂无项目
                  </TableCell>
                </TableRow>
              ) : (
                projects.map((project) => (
                  <TableRow key={project.id} data-testid={`project-row-${project.id}`}>
                    <TableCell>{project.name}</TableCell>
                    <TableCell className="font-mono text-xs">{project.repo_url ?? "—"}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid={`project-select-${project.id}`}
                        onClick={() => setSelectedProjectId(project.id)}
                      >
                        详情
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          <div className="flex items-end gap-3">
            <div className="max-w-xs flex-1 space-y-1">
              <Label htmlFor="project-name">项目名称</Label>
              <Input
                id="project-name"
                data-testid="project-name-input"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <RequirePermission code="project:create">
              <Button
                size="sm"
                data-testid="project-create-button"
                onClick={handleCreate}
                disabled={createProject.isPending}
              >
                新建项目
              </Button>
            </RequirePermission>
          </div>
        </CardContent>
      </Card>

      {selectedProject ? (
        <Card>
          <CardHeader>
            <CardTitle>项目详情：{selectedProject.name}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4" data-testid="project-detail">
            <GitPanel project={selectedProject} />

            <div>
              <h2 className="mb-2 text-sm font-medium">文件浏览器</h2>
              <FilesPanel workspaceId={workspaceId || null} />
            </div>

            <div>
              <h2 className="mb-2 text-sm font-medium">运行环境</h2>
              <EnvironmentPanel workspaceId={workspaceId || null} />
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
