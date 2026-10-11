import { useParams } from "react-router-dom";

import { VersionList } from "@/components/agents/VersionList";
import { ToolPermissionForm } from "@/components/tools/ToolPermissionForm";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAgent } from "@/hooks/useAgents";
import { useTools, useToolPermissions } from "@/hooks/useTools";

/**
 * Agent 详情页（W7 / T1-33）。
 *
 * 详情 + 版本列表 / 发布（切换 `current_version_id`）+ Agent↔Tool 权限 scope 配置入口。
 */
export function AgentDetail() {
  const { agentId } = useParams<{ agentId: string }>();
  const { data: agent, isLoading } = useAgent(agentId ?? null);
  const { data: tools } = useTools();
  const { data: permissions } = useToolPermissions(agentId ?? null);

  const toolName = (toolId: string): string => {
    const tool = (tools ?? []).find((item) => (item.id ?? item.name) === toolId);
    return tool ? tool.display_name || tool.name : toolId;
  };

  if (!agentId) {
    return <p className="text-sm text-muted-foreground">缺少 Agent 标识</p>;
  }

  return (
    <div className="space-y-4" data-testid="agent-detail">
      <Card>
        <CardHeader>
          <CardTitle>{isLoading ? "加载中…" : (agent?.name ?? "Agent 详情")}</CardTitle>
        </CardHeader>
        <CardContent>
          {agent ? (
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <dt className="text-xs text-muted-foreground">类型</dt>
                <dd className="text-sm font-medium">{agent.type}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">状态</dt>
                <dd className="text-sm font-medium">
                  <Badge variant={agent.status === "ACTIVE" ? "default" : "secondary"}>
                    {agent.status}
                  </Badge>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">当前版本</dt>
                <dd className="font-mono text-xs">{agent.current_version_id ?? "—"}</dd>
              </div>
              <div className="sm:col-span-3">
                <dt className="text-xs text-muted-foreground">描述</dt>
                <dd className="text-sm">{agent.description || "—"}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">请稍候…</p>
          )}
        </CardContent>
      </Card>

      <VersionList agentId={agentId} currentVersionId={agent?.current_version_id ?? null} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ToolPermissionForm
          agents={agent ? [agent] : []}
          tools={tools ?? []}
          defaultAgentId={agentId}
        />

        <Card data-testid="agent-permissions">
          <CardHeader>
            <CardTitle>已授权工具</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tool</TableHead>
                  <TableHead>动作</TableHead>
                  <TableHead>效果</TableHead>
                  <TableHead>Scope</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(permissions ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-sm text-muted-foreground">
                      暂无权限配置
                    </TableCell>
                  </TableRow>
                ) : (
                  (permissions ?? []).map((permission) => (
                    <TableRow key={permission.id}>
                      <TableCell>{toolName(permission.tool_id)}</TableCell>
                      <TableCell>{permission.action}</TableCell>
                      <TableCell>{permission.effect}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {JSON.stringify(permission.scope)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
