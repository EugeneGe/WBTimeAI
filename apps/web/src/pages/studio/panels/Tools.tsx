import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToolPermissions, useTools } from "@/hooks/useTools";
import type { AgentStudioPanelProps } from "@/types";

/**
 * Tools 面板（W8 / T2-41；设计 §2.13）。
 *
 * - **绑定** Tool（多选，写入草稿 `toolIds` → 发布落 `agent_version` ↔ Tool 绑定）；
 * - 展示该 Agent 的既有 **Tool 授权**（`tool_permission`，只读）。
 *
 * 🔴 复用既有能力（`services/tool.ts`）。
 */
export function Tools({ agent, draft, onDraftChange }: AgentStudioPanelProps) {
  const { data: tools, isLoading } = useTools();
  const { data: permissions } = useToolPermissions(agent?.id ?? null);

  const toggle = (toolId: string): void => {
    onDraftChange({
      toolIds: draft.toolIds.includes(toolId)
        ? draft.toolIds.filter((id) => id !== toolId)
        : [...draft.toolIds, toolId],
    });
  };

  return (
    <div className="space-y-4" data-testid="panel-tools">
      <Card>
        <CardHeader>
          <CardTitle>绑定 Tool</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (tools ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无可用工具</p>
          ) : (
            <ul className="space-y-2">
              {(tools ?? []).map((tool) => {
                const toolId = tool.id ?? tool.name;
                return (
                  <li key={toolId} className="flex items-center gap-2">
                    <input
                      id={`tool-bind-${tool.name}`}
                      data-testid={`tool-bind-${tool.name}`}
                      type="checkbox"
                      checked={draft.toolIds.includes(toolId)}
                      onChange={() => toggle(toolId)}
                    />
                    <label htmlFor={`tool-bind-${tool.name}`} className="text-sm">
                      {tool.display_name || tool.name}
                      {tool.requires_sandbox ? (
                        <span className="ml-1 text-xs text-muted-foreground">（需沙箱）</span>
                      ) : null}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>既有 Tool 授权</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-1 text-xs" data-testid="panel-tool-permissions">
            {(permissions ?? []).length === 0 ? (
              <li className="text-muted-foreground">暂无授权</li>
            ) : (
              (permissions ?? []).map((permission) => (
                <li key={permission.id} className="flex items-center justify-between">
                  <span>
                    {permission.tool_id} · {permission.action}
                  </span>
                  <Badge variant={permission.effect === "ALLOW" ? "default" : "destructive"}>
                    {permission.effect}
                  </Badge>
                </li>
              ))
            )}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
