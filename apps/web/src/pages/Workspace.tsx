import { useQueryClient } from "@tanstack/react-query";
import { Copy, LayoutGrid, Plus, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { InlineEmpty } from "@/components/common/InlineEmpty";
import { RequirePermission } from "@/components/guards/RequirePermission";
import { PageContainer } from "@/components/layout/PageContainer";
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
  useCreateWorkspace,
  useUpdateWorkspaceSettings,
  useWorkspace,
  useWorkspaces,
} from "@/hooks/useWorkspaces";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { usePermission } from "@/lib/permission";
import { queryKeys } from "@/lib/query";
import type { ProjectResponse, WorkspaceResponse } from "@/types";

/**
 * 工作区页（B-23 · V0.4.6 UI 重排；`PageContainer width="content"`）。
 *
 * 布局：**页头范式**（H1 + 副标题「N 个工作区 · 当前：xxx」+ 刷新 + 主 CTA）→
 * **两栏**（左 300px 全部工作区 / 右 1fr 详情 + JSON 设置）。
 *
 * 🔴 能力边界（后端 `routers/v1/workspaces.py` 仅 create / list / get / update-settings）：
 *    **不做改 / 删 / 重命名**，界面也不放灰色假按钮。
 * 🔴 项目数**只读 TanStack Query 缓存**（不发起 N+1 请求），未缓存显示 `—`。
 * 🔴 设置保存前**必须**本地校验 JSON；非法 → 行内报错且**不发** `PUT`。
 */

/** 两位补零。 */
function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** 创建时间格式化为 `MM-DD`（列表次行；空值 / 非法值 → `—`）。 */
function formatMonthDay(value?: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

/** 完整时间格式化为 `YYYY-MM-DD HH:mm`（详情信息格；空值 / 非法值 → `—`）。 */
function formatFullTime(value?: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(
    date.getHours(),
  )}:${pad2(date.getMinutes())}`;
}

/** JSON 文本解析结果（`valid=false` 时携带可展示原因）。 */
interface JsonParseResult {
  valid: boolean;
  error: string | null;
}

/** 解析设置文本（**不抛异常**，供徽标实时校验与保存前守卫复用）。 */
function parseSettings(text: string): JsonParseResult {
  try {
    JSON.parse(text);
    return { valid: true, error: null };
  } catch (error) {
    const reason = error instanceof Error ? error.message : "格式错误";
    return { valid: false, error: reason };
  }
}

/** 小号「次级」按钮样式。 */
const GHOST_ACTION_CLASS =
  "inline-flex h-7 items-center gap-1 rounded-lg border border-input bg-background px-2.5 text-[11px] text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50";

/** 页头主按钮样式。 */
const PRIMARY_BUTTON_CLASS =
  "inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50";

/** 页头图标按钮样式。 */
const ICON_BUTTON_CLASS =
  "flex h-8 w-8 items-center justify-center rounded-lg border border-input bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** 行内「op」小按钮样式（格式化 / 重置 / 复制 ID）。 */
const OP_BUTTON_CLASS =
  "inline-flex h-6 items-center gap-1 rounded-md border border-input bg-background px-2 text-[11px] text-primary transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/**
 * 工作区页。
 *
 * 状态：选中工作区 / 设置文本 / 新建弹窗 / 复制反馈 / 行内反馈。
 * 数据：`useWorkspaces` + `useWorkspace(selectedId)`。
 */
export function Workspace() {
  const queryClient = useQueryClient();
  const { can } = usePermission();
  const workspacesQuery = useWorkspaces();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [settingsText, setSettingsText] = useState("{}");
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [copyLabel, setCopyLabel] = useState("复制 ID");

  const { data: selected } = useWorkspace(selectedId);
  const createWorkspace = useCreateWorkspace();
  const updateSettings = useUpdateWorkspaceSettings();

  /** 复制反馈 2s 归位的定时器（卸载时清理）。 */
  const copyTimer = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (copyTimer.current !== null) {
        window.clearTimeout(copyTimer.current);
      }
    };
  }, []);

  const workspaceList = workspacesQuery.data ?? [];
  const jsonState = useMemo(() => parseSettings(settingsText), [settingsText]);
  const canCreate = can("workspace:create");

  const subtitle = selected
    ? `${workspaceList.length} 个工作区 · 当前：${selected.name}`
    : `${workspaceList.length} 个工作区 · 选择一个工作区查看详情`;

  /** 选中工作区：设置文本回落到该工作区当前设置，清空旧反馈。 */
  const handleSelect = (workspace: WorkspaceResponse): void => {
    setSelectedId(workspace.id);
    setSettingsText(JSON.stringify(workspace.settings ?? {}, null, 2));
    setFeedback(null);
    setCopyLabel("复制 ID");
  };

  /** 刷新：失效工作区列表 + 当前详情。 */
  const handleRefresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces });
    if (selectedId) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workspace(selectedId) });
    }
  };

  /** 打开新建弹窗。 */
  const openCreate = (): void => {
    setName("");
    setCreateError(null);
    setCreateOpen(true);
  };

  /** 提交新建（成功 → 关闭 + 选中 + 反馈）。 */
  const handleCreate = (): void => {
    const trimmed = name.trim();
    if (!trimmed) {
      setCreateError("请输入工作区名称");
      return;
    }
    setCreateError(null);
    createWorkspace.mutate(
      { name: trimmed },
      {
        onSuccess: (workspace) => {
          setCreateOpen(false);
          setName("");
          handleSelect(workspace);
          setFeedback("创建成功");
        },
        onError: (error) => setCreateError(toApiError(error).message),
      },
    );
  };

  /** 保存设置：**先校验**，非法不发请求。 */
  const handleSaveSettings = (): void => {
    if (!selected) {
      return;
    }
    const parsed = parseSettings(settingsText);
    if (!parsed.valid) {
      setFeedback("设置必须是合法 JSON，未提交");
      return;
    }
    setFeedback(null);
    updateSettings.mutate(
      {
        id: selected.id,
        payload: { settings: JSON.parse(settingsText) as Record<string, unknown> },
      },
      {
        onSuccess: () => setFeedback("设置已保存"),
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  /** 格式化（仅合法 JSON 时重排，非法保持原样并提示）。 */
  const handleFormat = (): void => {
    const parsed = parseSettings(settingsText);
    if (!parsed.valid) {
      setFeedback("设置必须是合法 JSON，无法格式化");
      return;
    }
    setSettingsText(JSON.stringify(JSON.parse(settingsText), null, 2));
  };

  /** 重置：回落到当前选中工作区的设置。 */
  const handleReset = (): void => {
    if (!selected) {
      return;
    }
    setSettingsText(JSON.stringify(selected.settings ?? {}, null, 2));
    setFeedback(null);
  };

  /** 复制工作区 ID（成功 2s 内就地反馈「已复制」；不可用降级为 `—`）。 */
  const handleCopyId = (id: string): void => {
    const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
    if (!clipboard || typeof clipboard.writeText !== "function") {
      setCopyLabel("—");
      return;
    }
    void clipboard
      .writeText(id)
      .then(() => {
        setCopyLabel("已复制");
        if (copyTimer.current !== null) {
          window.clearTimeout(copyTimer.current);
        }
        copyTimer.current = window.setTimeout(() => setCopyLabel("复制 ID"), 2000);
      })
      .catch(() => setCopyLabel("—"));
  };

  return (
    <PageContainer width="content">
      <div className="space-y-4" data-testid="workspace">
        {/* ===== 页头：H1 + 副标题（总数 / 当前）+ 刷新 + 主 CTA ===== */}
        <div className="flex items-start gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground">工作区</h1>
            <p className="mt-1 text-xs text-muted-foreground" data-testid="workspace-subtitle">
              {subtitle}
            </p>
          </div>
          <div className="ml-auto flex flex-none items-center gap-2 pt-0.5">
            <button
              type="button"
              data-testid="workspace-refresh"
              aria-label="刷新"
              title="刷新"
              onClick={handleRefresh}
              className={ICON_BUTTON_CLASS}
            >
              <RefreshCw aria-hidden className="h-4 w-4" />
            </button>
            {canCreate ? (
              <button
                type="button"
                data-testid="workspace-create-open"
                onClick={openCreate}
                className={PRIMARY_BUTTON_CLASS}
              >
                <Plus aria-hidden className="h-3.5 w-3.5" />
                新建工作区
              </button>
            ) : (
              <span className="text-[11px] text-muted-foreground">无 workspace:create 权限</span>
            )}
          </div>
        </div>

        {feedback ? (
          <p
            className="rounded-md bg-secondary px-2.5 py-1 text-[11px] font-medium text-foreground"
            data-testid="workspace-feedback"
            role="status"
          >
            {feedback}
          </p>
        ) : null}

        {/* ===== 两栏：左全部工作区 / 右详情 + 设置 ===== */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[300px_1fr]">
          {/* 左：全部工作区 */}
          <div className="self-start rounded-xl border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-3 py-2">
              <span className="text-[13px] font-medium text-primary">全部工作区</span>
              <span
                className="ml-auto text-[11px] text-muted-foreground"
                data-testid="workspace-total"
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
                  description="创建工作区后即可管理项目与远程任务"
                  testId="workspace-empty"
                  action={
                    canCreate ? (
                      <button
                        type="button"
                        data-testid="workspace-empty-create"
                        onClick={openCreate}
                        className={GHOST_ACTION_CLASS}
                      >
                        <Plus aria-hidden className="h-3 w-3" />
                        新建工作区
                      </button>
                    ) : null
                  }
                />
              ) : (
                <ul className="space-y-0.5">
                  {workspaceList.map((workspace) => {
                    const active = workspace.id === selectedId;
                    // 🔴 项目数**只读缓存**（不发 N+1）；未缓存显示 `—`。
                    const cached = queryClient.getQueryData<ProjectResponse[]>(
                      queryKeys.projects(workspace.id),
                    );
                    const projectCountLabel = cached ? `${cached.length} 个项目` : "—";
                    return (
                      <li key={workspace.id}>
                        <button
                          type="button"
                          data-testid={`workspace-row-${workspace.id}`}
                          aria-pressed={active}
                          onClick={() => handleSelect(workspace)}
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
                            data-testid={`workspace-row-meta-${workspace.id}`}
                          >
                            {workspace.workspace_type} · {projectCountLabel} ·{" "}
                            {formatMonthDay(workspace.created_at)}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>

          {/* 右：详情 + 设置 */}
          <div className="min-w-0 rounded-xl border border-border bg-card">
            {selected ? (
              <>
                <div className="flex items-center gap-2 border-b border-border px-3.5 py-2">
                  <span className="min-w-0 truncate text-[13px] font-medium text-primary">
                    {selected.name}
                  </span>
                  <span className="rounded-full bg-secondary px-1.5 py-0.5 text-[10px] leading-none text-primary">
                    {selected.workspace_type}
                  </span>
                  <button
                    type="button"
                    data-testid="workspace-copy-id"
                    onClick={() => handleCopyId(selected.id)}
                    className={cn(OP_BUTTON_CLASS, "ml-auto")}
                  >
                    <Copy aria-hidden className="h-3 w-3" />
                    {copyLabel}
                  </button>
                </div>

                <div className="space-y-3 p-3.5">
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                    <div>
                      <div className="text-[10px] text-muted-foreground">工作区 ID</div>
                      <div
                        className="mt-0.5 break-all font-mono text-[10px] text-foreground"
                        data-testid="workspace-id"
                      >
                        {selected.id}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-muted-foreground">创建时间</div>
                      <div
                        className="mt-0.5 text-[11px] text-foreground"
                        data-testid="workspace-created-at"
                      >
                        {formatFullTime(selected.created_at)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-muted-foreground">更新时间</div>
                      <div
                        className="mt-0.5 text-[11px] text-foreground"
                        data-testid="workspace-updated-at"
                      >
                        {formatFullTime(selected.updated_at)}
                      </div>
                    </div>
                  </div>

                  <RequirePermission code="workspace:update">
                    <div className="border-t border-border pt-2.5">
                      <div className="mb-1.5 flex items-center gap-2">
                        <span className="text-xs font-medium text-primary">设置（JSON）</span>
                        <span
                          data-testid="workspace-json-status"
                          className={cn(
                            "rounded-full px-1.5 py-0.5 text-[10px] leading-none",
                            jsonState.valid
                              ? "bg-[#EDF4F0] text-[#3C6650]"
                              : "bg-[#FBEEF0] text-[#8F3A47]",
                          )}
                        >
                          {jsonState.valid ? "合法" : "非法"}
                        </span>
                        <span className="ml-auto flex items-center gap-1.5">
                          <button
                            type="button"
                            data-testid="workspace-json-format"
                            onClick={handleFormat}
                            className={OP_BUTTON_CLASS}
                          >
                            格式化
                          </button>
                          <button
                            type="button"
                            data-testid="workspace-json-reset"
                            onClick={handleReset}
                            className={OP_BUTTON_CLASS}
                          >
                            重置
                          </button>
                        </span>
                      </div>

                      <textarea
                        id="ws-settings"
                        data-testid="workspace-settings-input"
                        aria-label="工作区设置（JSON）"
                        className="h-32 w-full rounded-lg border border-input bg-background p-2.5 font-mono text-[11px] leading-[1.55] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        value={settingsText}
                        onChange={(event) => setSettingsText(event.target.value)}
                      />

                      {jsonState.error ? (
                        <p
                          className="mt-1 text-[11px] text-[#8F3A47]"
                          data-testid="workspace-json-error"
                        >
                          JSON 非法：{jsonState.error}
                        </p>
                      ) : null}

                      <div className="mt-2 flex items-center gap-2">
                        <Button
                          size="sm"
                          className="h-7 text-[11px]"
                          data-testid="workspace-settings-save"
                          onClick={handleSaveSettings}
                          disabled={updateSettings.isPending}
                        >
                          保存设置
                        </Button>
                        <span className="text-[10px] text-muted-foreground">
                          保存后即时生效；非法 JSON 不提交。
                        </span>
                      </div>
                    </div>
                  </RequirePermission>

                  <p className="border-t border-border pt-2.5 text-[10px] text-muted-foreground">
                    工作区维护能力仅包含设置更新（后端未提供其他端点），本轮不新增入口。
                  </p>
                </div>
              </>
            ) : (
              <InlineEmpty
                icon={LayoutGrid}
                title="选择工作区"
                description="在左侧选择一个工作区查看详情与设置"
                testId="workspace-detail-empty"
                className="py-12"
              />
            )}
          </div>
        </div>

        {/* ===== 新建工作区弹窗 ===== */}
        <Dialog
          open={createOpen}
          onOpenChange={(open) => {
            setCreateOpen(open);
            if (!open) {
              setCreateError(null);
            }
          }}
        >
          <DialogContent data-testid="workspace-create-dialog" className="max-w-md">
            <DialogHeader>
              <DialogTitle>新建工作区</DialogTitle>
              <DialogDescription>工作区是项目与远程任务的归属容器。</DialogDescription>
            </DialogHeader>

            <div className="space-y-1">
              <Label htmlFor="ws-name" className="text-[11px] text-muted-foreground">
                名称
              </Label>
              <Input
                id="ws-name"
                data-testid="workspace-name-input"
                className="h-8 text-xs"
                value={name}
                placeholder="如 研发中心"
                onChange={(event) => setName(event.target.value)}
              />
              {createError ? (
                <p className="text-[11px] text-[#A84452]" data-testid="workspace-create-error">
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
                data-testid="workspace-create-submit"
                onClick={handleCreate}
                disabled={createWorkspace.isPending}
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
