import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCreateWorkspace,
  useUpdateWorkspaceSettings,
  useWorkspace,
  useWorkspaces,
} from "@/hooks/useWorkspaces";
import { toApiError } from "@/lib/api";
import { usePermission } from "@/lib/permission";
import type { WorkspaceResponse } from "@/types";

/** 工作区页：列表 / 新建 / 详情 / 设置（`workspace:create` / `workspace:update` 守护）。 */
export function Workspace() {
  const { can } = usePermission();
  const { data: workspaces, isLoading } = useWorkspaces();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [settingsText, setSettingsText] = useState("{}");
  const [feedback, setFeedback] = useState<string | null>(null);

  const { data: selected } = useWorkspace(selectedId);
  const createWorkspace = useCreateWorkspace();
  const updateSettings = useUpdateWorkspaceSettings();

  const handleSelect = (workspace: WorkspaceResponse) => {
    setSelectedId(workspace.id);
    setSettingsText(JSON.stringify(workspace.settings ?? {}, null, 2));
    setFeedback(null);
  };

  const handleCreate = () => {
    if (!name.trim()) {
      setFeedback("请输入工作区名称");
      return;
    }
    setFeedback(null);
    createWorkspace.mutate(
      { name: name.trim() },
      {
        onSuccess: (workspace) => {
          setName("");
          handleSelect(workspace);
          setFeedback("创建成功");
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const handleSaveSettings = () => {
    if (!selected) {
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(settingsText) as Record<string, unknown>;
    } catch {
      setFeedback("设置必须是合法 JSON");
      return;
    }
    setFeedback(null);
    updateSettings.mutate(
      { id: selected.id, payload: { settings: parsed } },
      {
        onSuccess: () => setFeedback("设置已保存"),
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[280px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>工作区</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ul className="space-y-1">
            {isLoading ? (
              <li className="text-sm text-muted-foreground">加载中…</li>
            ) : (workspaces ?? []).length === 0 ? (
              <li className="text-sm text-muted-foreground">暂无工作区</li>
            ) : (
              (workspaces ?? []).map((workspace) => (
                <li key={workspace.id}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-accent"
                    onClick={() => handleSelect(workspace)}
                  >
                    <span className="truncate">{workspace.name}</span>
                    {selectedId === workspace.id ? <Badge variant="secondary">选中</Badge> : null}
                  </button>
                </li>
              ))
            )}
          </ul>

          {can("workspace:create") ? (
            <div className="space-y-2 border-t pt-4">
              <Label htmlFor="ws-name">新建工作区</Label>
              <Input
                id="ws-name"
                value={name}
                placeholder="名称"
                onChange={(event) => setName(event.target.value)}
              />
              <Button
                className="w-full"
                size="sm"
                onClick={handleCreate}
                disabled={createWorkspace.isPending}
              >
                新建
              </Button>
            </div>
          ) : (
            <p className="border-t pt-4 text-xs text-muted-foreground">
              无 `workspace:create` 权限，无法新建。
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>详情</CardTitle>
        </CardHeader>
        <CardContent>
          {feedback ? <p className="mb-3 text-sm text-muted-foreground">{feedback}</p> : null}
          {selected ? (
            <div className="space-y-4">
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted-foreground">名称</dt>
                  <dd className="text-sm font-medium">{selected.name}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">类型</dt>
                  <dd className="text-sm font-medium">{selected.workspace_type}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">ID</dt>
                  <dd className="text-sm font-medium">{selected.id}</dd>
                </div>
              </dl>

              <RequirePermission code="workspace:update">
                <div className="space-y-2 border-t pt-4">
                  <Label htmlFor="ws-settings">设置（JSON）</Label>
                  <textarea
                    id="ws-settings"
                    className="h-32 w-full rounded-md border border-input bg-background p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    value={settingsText}
                    onChange={(event) => setSettingsText(event.target.value)}
                  />
                  <Button
                    size="sm"
                    onClick={handleSaveSettings}
                    disabled={updateSettings.isPending}
                  >
                    保存设置
                  </Button>
                </div>
              </RequirePermission>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">请选择左侧工作区查看详情</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
