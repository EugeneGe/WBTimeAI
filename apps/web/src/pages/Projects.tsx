import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderKanban, LayoutGrid, Plus, RefreshCw, Rocket, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { InlineEmpty } from "@/components/common/InlineEmpty";
import { RequirePermission } from "@/components/guards/RequirePermission";
import { PageContainer } from "@/components/layout/PageContainer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Skeleton } from "@/components/ui/skeleton";
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
import { cn } from "@/lib/cn";
import { queryKeys } from "@/lib/query";
import { projectService } from "@/services/project";
import type { ApiError, EnvironmentResponse, ProjectResponse } from "@/types";

/**
 * 项目页（B-22 · V0.4.6 UI 重排；`PageContainer width="default"`）。
 *
 * 布局：**页头范式**（H1 + 副标题 + 刷新 + 主 CTA）→ **两栏**
 * （左 248px 工作区上下文 / 右 1fr 项目台账 + 详情卡）。
 *
 * 🔴 能力边界（后端 `routers/v1/projects.py` 仅 list / create / get）：
 *    **不做改 / 删 / 重命名**，界面也不放灰色假按钮。
 * 🔴 文件能力未装配（缺 `Storage`）→ 后端 **503** → 文件区渲染降级态，不视为空。
 * 🔴 Environment 敏感项（`masked=true`）**只读展示引用**（`ref`），**禁**明文展示 / 输入。
 * 🔴 详情三段面板**常驻挂载**，非激活段用 `hidden` 属性隐藏——
 *    切换 Tab 不重置文件面板的 prefix / 预览状态，且既有用例可直接 `findByTestId`。
 */

/** 详情分段键（顺序冻结：Git → 文件 → 运行环境；默认 Git）。 */
type ProjectDetailTab = "git" | "files" | "env";

/** 分段定义（`testId` 与冻结口径一致：`project-detail-tab-<key>`）。 */
const DETAIL_TABS: readonly { key: ProjectDetailTab; label: string }[] = [
  { key: "git", label: "Git 元信息" },
  { key: "files", label: "文件" },
  { key: "env", label: "运行环境" },
];

/** 空数组常量（稳定引用，避免 `useMemo` 依赖每次变化）。 */
const NO_PROJECTS: ProjectResponse[] = [];

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

/** 两位补零。 */
function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** 创建时间格式化为 `MM-DD HH:mm`（空值 / 非法值 → `—`）。 */
function formatCreatedAt(value?: string | null): string {
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

/** 取 ID 末 4 位（列表短 ID 展示，`#a1f2`）。 */
function shortId(id: string): string {
  return id.length <= 4 ? id : id.slice(-4);
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
          <Label htmlFor="files-prefix" className="text-[11px] text-muted-foreground">
            路径前缀
          </Label>
          <Input
            id="files-prefix"
            data-testid="files-prefix-input"
            className="h-8 text-xs"
            value={prefix}
            placeholder="（可空）如 src/"
            onChange={(event) => setPrefix(event.target.value)}
          />
        </div>
      </div>

      {unavailable ? (
        <div
          className="rounded-lg border border-dashed border-border p-3 text-[11px] text-muted-foreground"
          data-testid="files-degrade"
        >
          文件能力未装配（需 Storage）
        </div>
      ) : filesQuery.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 2 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      ) : filesQuery.isError ? (
        <p className="text-xs text-destructive" data-testid="files-error">
          {resolveErrorMessage(filesQuery.error)}
        </p>
      ) : files.length === 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="files-empty">
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
                <TableCell className="text-xs">{file.size}</TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-[11px]"
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
        <div className="rounded-lg border border-border p-3" data-testid="file-preview">
          <div className="mb-2 font-mono text-[11px] text-muted-foreground">{previewPath}</div>
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
        <div className="space-y-2">
          {Array.from({ length: 2 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      ) : envs.length === 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="environment-empty">
          暂无运行环境
        </p>
      ) : (
        <ul className="space-y-1" data-testid="environment-list">
          {envs.map((env) => (
            <li key={env.id}>
              <button
                type="button"
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-3 py-1.5 text-left text-xs transition-colors hover:bg-accent",
                  selectedId === env.id ? "bg-secondary/60" : null,
                )}
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
        <div
          className="space-y-2 rounded-lg border border-border p-3"
          data-testid="environment-detail"
        >
          <div className="text-xs font-medium">{detail.name}</div>
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
                  <TableCell colSpan={2} className="text-xs text-muted-foreground">
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
    <div className="space-y-2 rounded-lg border border-border p-3" data-testid="project-git-panel">
      <div className="grid grid-cols-1 gap-2 text-[11px] sm:grid-cols-2">
        <div>
          <div className="text-muted-foreground">仓库地址</div>
          <div className="font-mono text-foreground" data-testid="project-repo-url">
            {project.repo_url ?? "—"}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground">默认分支</div>
          <div className="font-mono text-foreground" data-testid="project-default-branch">
            {project.default_branch ?? "—"}
          </div>
        </div>
      </div>
      <pre
        className="max-h-32 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2 font-mono text-[11px]"
        data-testid="project-settings"
      >
        {JSON.stringify(project.settings ?? {}, null, 2)}
      </pre>
      <p className="text-[11px] text-muted-foreground" data-testid="project-git-degrade">
        实时 Git 状态需 Sandbox 装配（R1/R3 增量）
      </p>
    </div>
  );
}

/** 小号文字链样式（工作区页 / 项目页共用口径）。 */
const LINK_CLASS =
  "inline-flex items-center text-[11px] font-medium text-primary underline underline-offset-2 transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** 小号「次级」按钮样式（内联空态动作 / 弹窗取消）。 */
const GHOST_ACTION_CLASS =
  "inline-flex h-7 items-center gap-1 rounded-lg border border-input bg-background px-2.5 text-[11px] text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** 页头主按钮样式。 */
const PRIMARY_BUTTON_CLASS =
  "inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50";

/** 页头图标按钮样式。 */
const ICON_BUTTON_CLASS =
  "flex h-8 w-8 items-center justify-center rounded-lg border border-input bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * 项目页。
 *
 * 状态：当前工作区 / 选中项目 / 搜索关键词 / 详情分段 / 新建弹窗与行内错误。
 * 数据：`useWorkspaces` + `useProjects(workspaceId)` + `useProject(selectedId)`。
 */
export function Projects() {
  const queryClient = useQueryClient();
  const workspacesQuery = useWorkspaces();
  const [workspaceId, setWorkspaceId] = useState<string>("");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<ProjectDetailTab>("git");
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [defaultBranch, setDefaultBranch] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const projectsQuery = useProjects(workspaceId || null);
  const detailQuery = useProject(selectedProjectId);
  const createProject = useCreateProject();

  const workspaceList = workspacesQuery.data ?? [];
  const projects = projectsQuery.data ?? NO_PROJECTS;
  const selectedProject = detailQuery.data;
  const currentWorkspace = workspaceList.find((item) => item.id === workspaceId) ?? null;

  /** 台账行：纯前端搜索（名称 / 仓库）+ 按创建时间倒序（空值排末位）。 */
  const rows = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    const matched = keyword
      ? projects.filter(
          (project) =>
            project.name.toLowerCase().includes(keyword) ||
            (project.repo_url ?? "").toLowerCase().includes(keyword),
        )
      : projects;
    return [...matched].sort((left, right) => {
      const leftTime = left.created_at ? Date.parse(left.created_at) : Number.NEGATIVE_INFINITY;
      const rightTime = right.created_at ? Date.parse(right.created_at) : Number.NEGATIVE_INFINITY;
      return rightTime - leftTime;
    });
  }, [projects, search]);

  const subtitle = workspaceId
    ? `当前工作区：${currentWorkspace?.name ?? "—"} · 共 ${
        projectsQuery.data ? projects.length : "—"
      } 个项目`
    : "请选择左侧工作区开始";

  /** 切换工作区：清空选中项目、搜索与分段（避免跨工作区残留上下文）。 */
  const handleSelectWorkspace = (nextWorkspaceId: string): void => {
    setWorkspaceId(nextWorkspaceId);
    setSelectedProjectId(null);
    setSearch("");
    setTab("git");
    setFeedback(null);
  };

  /** 刷新：失效工作区列表 + 当前工作区项目列表。 */
  const handleRefresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
    if (workspaceId) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects(workspaceId) });
    }
  };

  /** 打开新建弹窗（清空上次输入与行内错误）。 */
  const openCreate = (): void => {
    if (!workspaceId) {
      return;
    }
    setName("");
    setRepoUrl("");
    setDefaultBranch("");
    setCreateError(null);
    setCreateOpen(true);
  };

  /** 提交新建（失败只在弹窗内提示，不关闭弹窗）。 */
  const handleCreate = (): void => {
    if (!workspaceId) {
      setCreateError("请先选择工作区");
      return;
    }
    const trimmedName = name.trim();
    if (!trimmedName) {
      setCreateError("请填写项目名称");
      return;
    }
    setCreateError(null);
    createProject.mutate(
      {
        name: trimmedName,
        workspace_id: workspaceId,
        repo_url: repoUrl.trim() ? repoUrl.trim() : null,
        default_branch: defaultBranch.trim() ? defaultBranch.trim() : null,
      },
      {
        onSuccess: (project) => {
          setCreateOpen(false);
          setName("");
          setRepoUrl("");
          setDefaultBranch("");
          setSelectedProjectId(project.id);
          setTab("git");
          setFeedback(`已创建项目 ${project.name}`);
        },
        onError: (error) => setCreateError(resolveErrorMessage(error)),
      },
    );
  };

  return (
    <PageContainer width="default">
      <div className="space-y-3" data-testid="projects">
        {/* ===== 页头：H1 + 副标题（当前工作区 / 项目数）+ 刷新 + 主 CTA ===== */}
        <div className="flex items-start gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground">项目</h1>
            <p className="mt-1 text-xs text-muted-foreground" data-testid="projects-subtitle">
              {subtitle}
            </p>
          </div>
          <div className="ml-auto flex flex-none items-center gap-2 pt-0.5">
            <button
              type="button"
              data-testid="projects-refresh"
              aria-label="刷新"
              title="刷新"
              onClick={handleRefresh}
              className={ICON_BUTTON_CLASS}
            >
              <RefreshCw aria-hidden className="h-4 w-4" />
            </button>
            <RequirePermission code="project:create">
              <button
                type="button"
                data-testid="project-create-open"
                onClick={openCreate}
                disabled={!workspaceId}
                title={workspaceId ? undefined : "请先选择工作区"}
                className={PRIMARY_BUTTON_CLASS}
              >
                <Plus aria-hidden className="h-3.5 w-3.5" />
                新建项目
              </button>
            </RequirePermission>
          </div>
        </div>

        {feedback ? (
          <p
            className="text-xs font-medium text-[#3C6650]"
            data-testid="projects-feedback"
            role="status"
          >
            {feedback}
          </p>
        ) : null}

        {/* ===== 两栏：左工作区上下文 / 右项目台账 + 详情 ===== */}
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[248px_1fr]">
          {/* 左：工作区上下文 */}
          <div className="self-start rounded-xl border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-3 py-2">
              <span className="text-[13px] font-medium text-primary">工作区</span>
              <span
                className="ml-auto text-[11px] text-muted-foreground"
                data-testid="projects-workspace-count"
              >
                {workspaceList.length}
              </span>
            </div>
            <div className="p-2">
              {workspacesQuery.isLoading ? (
                <div className="space-y-1.5">
                  {Array.from({ length: 3 }).map((_, index) => (
                    <Skeleton key={index} className="h-9 w-full" />
                  ))}
                </div>
              ) : workspaceList.length === 0 ? (
                <InlineEmpty
                  icon={LayoutGrid}
                  title="暂无工作区"
                  description="先创建一个工作区，再回来添加项目"
                  testId="projects-workspace-empty"
                  action={
                    <Link to="/workspace" className={LINK_CLASS}>
                      前往创建工作区 →
                    </Link>
                  }
                />
              ) : (
                <ul className="space-y-0.5">
                  {workspaceList.map((workspace) => {
                    const active = workspace.id === workspaceId;
                    // 🔴 项目数**只读缓存**（不发起 N+1 请求）；未缓存显示 `—`。
                    const cached = queryClient.getQueryData<ProjectResponse[]>(
                      queryKeys.projects(workspace.id),
                    );
                    const projectCountLabel = cached ? `${cached.length} 个项目` : "—";
                    return (
                      <li key={workspace.id}>
                        <button
                          type="button"
                          data-testid={`workspace-item-${workspace.id}`}
                          aria-pressed={active}
                          onClick={() => handleSelectWorkspace(workspace.id)}
                          className={cn(
                            "relative flex w-full flex-col items-start gap-0.5 rounded-lg px-2.5 py-1.5 text-left transition-colors",
                            active ? "bg-[#FDF8EC]" : "hover:bg-accent/60",
                          )}
                        >
                          {active ? (
                            <span
                              aria-hidden
                              className="absolute bottom-1.5 left-0 top-1.5 w-[3px] rounded-full bg-[#F5B941]"
                            />
                          ) : null}
                          <span className="w-full truncate text-xs text-foreground">
                            {workspace.name}
                          </span>
                          <span
                            className="text-[10px] text-muted-foreground"
                            data-testid={`workspace-item-meta-${workspace.id}`}
                          >
                            {workspace.workspace_type} · {projectCountLabel}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
              <div className="mt-1.5 border-t border-border/60 px-1 pt-2">
                <Link to="/workspace" className={LINK_CLASS}>
                  管理工作区 →
                </Link>
              </div>
            </div>
          </div>

          {/* 右：项目台账 + 详情 */}
          <div className="min-w-0 space-y-3">
            <div className="rounded-xl border border-border bg-card">
              <div className="flex items-center gap-2 border-b border-border px-3.5 py-2">
                <span className="text-[13px] font-medium text-primary">项目台账</span>
                <span
                  className="ml-auto text-[11px] text-muted-foreground"
                  data-testid="projects-total"
                >
                  共 {rows.length} 个
                </span>
              </div>
              <div className="p-3.5">
                <div className="mb-2.5 flex items-center gap-2">
                  <div className="relative">
                    <Search
                      aria-hidden
                      className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                    />
                    <Input
                      data-testid="projects-search"
                      aria-label="搜索项目"
                      className="h-8 w-[240px] pl-8 text-xs"
                      placeholder="搜索项目名 / 仓库…"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                    />
                  </div>
                  <span className="ml-auto text-[11px] text-muted-foreground">按创建时间倒序</span>
                </div>

                {!workspaceId ? (
                  <InlineEmpty
                    icon={LayoutGrid}
                    title="选择左侧工作区"
                    description="项目按工作区隔离；选中左侧工作区后可查看与新建项目"
                    testId="projects-hint"
                    action={
                      <Link to="/workspace" className={LINK_CLASS}>
                        前往工作区 →
                      </Link>
                    }
                  />
                ) : projectsQuery.isLoading ? (
                  <div className="space-y-2">
                    {Array.from({ length: 3 }).map((_, index) => (
                      <Skeleton key={index} className="h-9 w-full" />
                    ))}
                  </div>
                ) : projectsQuery.isError ? (
                  <p className="py-4 text-xs text-destructive" data-testid="projects-error">
                    {resolveErrorMessage(projectsQuery.error)}
                  </p>
                ) : projects.length === 0 ? (
                  <InlineEmpty
                    icon={FolderKanban}
                    title="暂无项目"
                    description="创建第一个项目，或切换其他工作区"
                    testId="projects-empty"
                    action={
                      <button
                        type="button"
                        data-testid="projects-empty-create"
                        onClick={openCreate}
                        className={GHOST_ACTION_CLASS}
                      >
                        <Plus aria-hidden className="h-3 w-3" />
                        新建项目
                      </button>
                    }
                  />
                ) : rows.length === 0 ? (
                  <InlineEmpty
                    icon={Search}
                    title="无匹配项目"
                    description={`没有名称或仓库包含「${search.trim()}」的项目`}
                    testId="projects-search-empty"
                    action={
                      <button
                        type="button"
                        data-testid="projects-search-clear"
                        onClick={() => setSearch("")}
                        className={GHOST_ACTION_CLASS}
                      >
                        清除搜索
                      </button>
                    }
                  />
                ) : (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>项目</TableHead>
                          <TableHead>仓库</TableHead>
                          <TableHead>默认分支</TableHead>
                          <TableHead>创建时间</TableHead>
                          <TableHead className="text-right">操作</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {rows.map((project) => {
                          const active = project.id === selectedProjectId;
                          return (
                            <TableRow
                              key={project.id}
                              data-testid={`project-row-${project.id}`}
                              className={active ? "bg-[#FDF8EC]" : undefined}
                            >
                              <TableCell>
                                <div className="text-xs font-medium text-primary">
                                  {project.name}
                                </div>
                                <div className="font-mono text-[10px] text-muted-foreground">
                                  #{shortId(project.id)}
                                </div>
                              </TableCell>
                              <TableCell className="font-mono text-[11px] text-muted-foreground">
                                {project.repo_url ?? "—"}
                              </TableCell>
                              <TableCell className="font-mono text-[11px] text-muted-foreground">
                                {project.default_branch ?? "—"}
                              </TableCell>
                              <TableCell className="text-[11px] text-muted-foreground">
                                {formatCreatedAt(project.created_at)}
                              </TableCell>
                              <TableCell className="text-right">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-6 px-2 text-[11px]"
                                  data-testid={`project-select-${project.id}`}
                                  onClick={() => setSelectedProjectId(project.id)}
                                >
                                  详情
                                </Button>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>
            </div>

            {selectedProject ? (
              <div className="rounded-xl border border-border bg-card" data-testid="project-detail">
                <div className="flex items-center gap-2 border-b border-border px-3.5 py-2">
                  <span className="min-w-0 truncate text-[13px] font-medium text-primary">
                    {selectedProject.name}
                  </span>
                  <Badge variant="secondary" className="text-[10px] font-medium">
                    已选中
                  </Badge>
                  <Link
                    to={`/remote-tasks?workspace=${workspaceId}&project=${selectedProject.id}`}
                    data-testid="project-open-remote"
                    className={cn(GHOST_ACTION_CLASS, "ml-auto")}
                  >
                    <Rocket aria-hidden className="h-3 w-3" />
                    在远程工作台打开
                  </Link>
                </div>
                <div className="space-y-3 p-3.5">
                  <div
                    className="flex gap-0.5 border-b border-border"
                    role="tablist"
                    aria-label="项目详情"
                  >
                    {DETAIL_TABS.map((item) => {
                      const active = tab === item.key;
                      return (
                        <button
                          key={item.key}
                          type="button"
                          role="tab"
                          aria-selected={active}
                          data-testid={`project-detail-tab-${item.key}`}
                          onClick={() => setTab(item.key)}
                          className={cn(
                            "border-b-2 px-2.5 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            active
                              ? "border-[#F5B941] font-medium text-primary"
                              : "border-transparent text-muted-foreground hover:text-foreground",
                          )}
                        >
                          {item.label}
                        </button>
                      );
                    })}
                  </div>

                  {/* 🔴 三段常驻挂载（切换 Tab 不重置文件面板 prefix / 预览状态）。 */}
                  <div hidden={tab !== "git"}>
                    <GitPanel project={selectedProject} />
                  </div>
                  <div hidden={tab !== "files"}>
                    <FilesPanel workspaceId={workspaceId || null} />
                  </div>
                  <div hidden={tab !== "env"}>
                    <EnvironmentPanel workspaceId={workspaceId || null} />
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        {/* ===== 新建项目弹窗（工作区取当前选中，只读展示）===== */}
        <Dialog
          open={createOpen}
          onOpenChange={(open) => {
            setCreateOpen(open);
            if (!open) {
              setCreateError(null);
            }
          }}
        >
          <DialogContent data-testid="project-create-dialog" className="max-w-md">
            <DialogHeader>
              <DialogTitle>新建项目</DialogTitle>
              <DialogDescription>
                项目归属当前工作区；创建后可在项目台账中查看详情。
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="project-name" className="text-[11px] text-muted-foreground">
                  项目名称
                </Label>
                <Input
                  id="project-name"
                  data-testid="project-name-input"
                  className="h-8 text-xs"
                  value={name}
                  placeholder="如 console-web"
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="project-repo" className="text-[11px] text-muted-foreground">
                  仓库地址
                </Label>
                <Input
                  id="project-repo"
                  data-testid="project-repo-input"
                  className="h-8 font-mono text-xs"
                  value={repoUrl}
                  placeholder="git@example.com:team/repo.git"
                  onChange={(event) => setRepoUrl(event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="project-branch" className="text-[11px] text-muted-foreground">
                  默认分支
                </Label>
                <Input
                  id="project-branch"
                  data-testid="project-branch-input"
                  className="h-8 font-mono text-xs"
                  value={defaultBranch}
                  placeholder="main"
                  onChange={(event) => setDefaultBranch(event.target.value)}
                />
              </div>
              <div className="rounded-lg border border-border bg-secondary/40 px-2.5 py-1.5 text-[11px] text-muted-foreground">
                工作区：
                <span
                  className="font-medium text-foreground"
                  data-testid="project-create-workspace"
                >
                  {currentWorkspace?.name ?? "—"}
                </span>
              </div>
              {createError ? (
                <p className="text-[11px] text-[#A84452]" data-testid="project-create-error">
                  {createError}
                </p>
              ) : null}
            </div>

            <DialogFooter>
              <button
                type="button"
                className={GHOST_ACTION_CLASS}
                onClick={() => setCreateOpen(false)}
              >
                取消
              </button>
              <Button
                size="sm"
                className="h-7 text-[11px]"
                data-testid="project-create-button"
                onClick={handleCreate}
                disabled={createProject.isPending}
              >
                创建
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </PageContainer>
  );
}
