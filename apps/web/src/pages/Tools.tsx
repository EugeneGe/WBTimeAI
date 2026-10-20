import { EmptyState } from "@/components/common/EmptyState";
import { PageContainer } from "@/components/layout/PageContainer";
import { ToolPermissionForm } from "@/components/tools/ToolPermissionForm";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAgents } from "@/hooks/useAgents";
import { useTools } from "@/hooks/useTools";

/**
 * Tools 页面（D-UI 体验优化波 · WS-P1 / #9；默认档）。
 *
 * 内置工具浏览器（首批 5 个 Tool）+ 权限配置（agent × tool × effect × scope）。
 */
export function Tools() {
  const { data: tools } = useTools();
  const { data: agents } = useAgents();

  const toolList = tools ?? [];

  return (
    <PageContainer width="default">
      <div className="space-y-4">
        <h1 className="text-lg font-semibold text-foreground">工具</h1>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>内置工具浏览器</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2" data-testid="tool-browser">
                {toolList.length === 0 ? (
                  <li>
                    <EmptyState title="暂无工具" description="内置工具装配后在此浏览" chips={[]} />
                  </li>
                ) : (
                  toolList.map((tool) => (
                    <li
                      key={tool.id ?? tool.name}
                      data-testid={`tool-item-${tool.name}`}
                      className="rounded-lg border border-border p-3"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-foreground">
                          {tool.display_name || tool.name}
                        </span>
                        <div className="flex items-center gap-2">
                          {tool.category ? <Badge variant="outline">{tool.category}</Badge> : null}
                          {tool.requires_sandbox ? <Badge variant="secondary">需沙箱</Badge> : null}
                        </div>
                      </div>
                      {tool.description ? (
                        <p className="mt-1 text-xs text-muted-foreground">{tool.description}</p>
                      ) : null}
                    </li>
                  ))
                )}
              </ul>
            </CardContent>
          </Card>

          <ToolPermissionForm
            agents={agents ?? []}
            tools={toolList}
            footerNote="已授权清单请到智能体详情核对；撤销能力当前未接线"
          />
        </div>
      </div>
    </PageContainer>
  );
}
