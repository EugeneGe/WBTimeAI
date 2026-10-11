import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDeleteMcpServer, useMcpServers, useRegisterMcpServer } from "@/hooks/useMcp";
import { toApiError } from "@/lib/api";
import type { AgentStudioPanelProps, MCPServerResponse } from "@/types";

/** 传输类型选项（↔ `mcp_server.transport`）。 */
const TRANSPORTS = ["stdio", "sse", "http"] as const;

/**
 * MCP 面板（W8 / T2-41；设计 §2.13）。
 *
 * - **绑定** MCP Server（多选，写入草稿 `mcpServerIds` → 发布落 `runtime_config.mcp_server_ids`）；
 * - **注册 / 删除** MCP Server（复用既有 MCP 服务；动作级守卫）。
 *
 * 🔴 凭据**仅引用 / 仅掩码**（C-07）：本面板**不输入、不回显**任何明文密钥。
 */
export function Mcp({ draft, onDraftChange, onFeedback }: AgentStudioPanelProps) {
  const { data: servers, isLoading } = useMcpServers();
  const registerServer = useRegisterMcpServer();
  const deleteServer = useDeleteMcpServer();

  const [name, setName] = useState("");
  const [transport, setTransport] = useState<string>("stdio");

  const toggle = (serverId: string): void => {
    onDraftChange({
      mcpServerIds: draft.mcpServerIds.includes(serverId)
        ? draft.mcpServerIds.filter((id) => id !== serverId)
        : [...draft.mcpServerIds, serverId],
    });
  };

  const handleRegister = (): void => {
    if (!name.trim()) {
      onFeedback("请填写 Server 名");
      return;
    }
    registerServer.mutate(
      { name: name.trim(), transport },
      {
        onSuccess: (server) => {
          setName("");
          onDraftChange({ mcpServerIds: [...draft.mcpServerIds, server.id] });
          onFeedback("MCP Server 已注册并绑定");
        },
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  const handleDelete = (server: MCPServerResponse): void => {
    deleteServer.mutate(server.id, {
      onSuccess: () => {
        onDraftChange({
          mcpServerIds: draft.mcpServerIds.filter((id) => id !== server.id),
        });
        onFeedback("MCP Server 已删除");
      },
      onError: (error) => onFeedback(toApiError(error).message),
    });
  };

  return (
    <div className="space-y-4" data-testid="panel-mcp">
      <Card>
        <CardHeader>
          <CardTitle>绑定 MCP Server</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : (servers ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无 Server</p>
          ) : (
            <ul className="space-y-2">
              {(servers ?? []).map((server) => (
                <li key={server.id} className="flex items-center gap-2">
                  <input
                    id={`mcp-bind-${server.name}`}
                    data-testid={`mcp-bind-${server.name}`}
                    type="checkbox"
                    checked={draft.mcpServerIds.includes(server.id)}
                    onChange={() => toggle(server.id)}
                  />
                  <label htmlFor={`mcp-bind-${server.name}`} className="text-sm">
                    {server.name}
                  </label>
                  <Badge variant="outline">{server.transport}</Badge>
                  <RequirePermission code="mcp:delete">
                    <Button
                      variant="ghost"
                      size="sm"
                      data-testid={`panel-mcp-delete-${server.name}`}
                      disabled={deleteServer.isPending}
                      onClick={() => handleDelete(server)}
                    >
                      删除
                    </Button>
                  </RequirePermission>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <RequirePermission code="mcp:create">
        <Card>
          <CardHeader>
            <CardTitle>注册 Server</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">
              凭据**仅引用 / 仅掩码**：此处只登记 Server 元数据，**不输入明文密钥**。
            </p>
            <div className="space-y-2">
              <Label htmlFor="panel-mcp-name">名称</Label>
              <Input
                id="panel-mcp-name"
                data-testid="panel-mcp-name-input"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="panel-mcp-transport">传输</Label>
              <select
                id="panel-mcp-transport"
                data-testid="panel-mcp-transport-select"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={transport}
                onChange={(event) => setTransport(event.target.value)}
              >
                {TRANSPORTS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </div>
            <Button
              size="sm"
              data-testid="panel-mcp-register"
              onClick={handleRegister}
              disabled={registerServer.isPending}
            >
              注册并绑定
            </Button>
          </CardContent>
        </Card>
      </RequirePermission>
    </div>
  );
}
