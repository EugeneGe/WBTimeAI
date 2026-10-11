import { ToolPermissionForm } from "@/components/tools/ToolPermissionForm";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAgents } from "@/hooks/useAgents";
import { useTools } from "@/hooks/useTools";

/**
 * Tools 页面（W7 / T1-34）。
 *
 * 内置工具浏览器（首批 5 个 Tool）+ 权限配置（agent × tool × effect × scope）。
 */
export function Tools() {
  const { data: tools } = useTools();
  const { data: agents } = useAgents();

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Tools</h1>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>内置工具浏览器</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2" data-testid="tool-browser">
              {(tools ?? []).length === 0 ? (
                <li className="text-sm text-muted-foreground">暂无工具</li>
              ) : (
                (tools ?? []).map((tool) => (
                  <li
                    key={tool.id ?? tool.name}
                    data-testid={`tool-item-${tool.name}`}
                    className="rounded-md border p-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{tool.display_name || tool.name}</span>
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

        <ToolPermissionForm agents={agents ?? []} tools={tools ?? []} />
      </div>
    </div>
  );
}
