import { useParams } from "react-router-dom";

import { VersionList } from "@/components/agents/VersionList";
import { EmptyState } from "@/components/common/EmptyState";
import { PageContainer } from "@/components/layout/PageContainer";
import { ToolPermissionForm } from "@/components/tools/ToolPermissionForm";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
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
 * Agent 详情页（D-UI 体验优化波 · WS-P1 / #7；默认档）。
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
    return (
      <PageContainer width="default">
        <EmptyState title="缺少 Agent 标识" description="请从智能体列表进入详情页" chips={[]} />
      </PageContainer>
    );
  }

  const permissionList = permissions ?? [];

  return (
    <PageContainer width="default">
      <div className="space-y-4" data-testid="agent-detail">
        <Card>
          <CardHeader>
            <CardTitle>{isLoading ? "加载中…" : (agent?.name ?? "Agent 详情")}</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div key={index} className="space-y-2">
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="h-4 w-28" />
                  </div>
                ))}
              </div>
            ) : agent ? (
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
              <EmptyState title="未找到 Agent" description="该智能体可能已被删除" chips={[]} />
            )}
          </CardContent>
        </Card>

        <VersionList agentId={agentId} currentVersionId={agent?.current_version_id ?? null} />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ToolPermissionForm
            agents={agent ? [agent] : []}
            tools={tools ?? []}
            defaultAgentId={agentId}
            disabled={false}
          />

          <Card data-testid="agent-permissions">
            <CardHeader>
              <CardTitle>已授权工具</CardTitle>
            </CardHeader>
            <CardContent>
              {permissionList.length === 0 ? (
                <EmptyState
                  title="暂无权限配置"
                  description="在左侧为 Agent 授权工具权限"
                  chips={[]}
                />
              ) : (
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
                    {permissionList.map((permission) => (
                      <TableRow key={permission.id}>
                        <TableCell>{toolName(permission.tool_id)}</TableCell>
                        <TableCell>{permission.action}</TableCell>
                        <TableCell>{permission.effect}</TableCell>
                        <TableCell className="font-mono text-xs">
                          {JSON.stringify(permission.scope)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </PageContainer>
  );
}
