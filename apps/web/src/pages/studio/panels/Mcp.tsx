import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDeleteMcpServer, useMcpServers, useRegisterMcpServer } from "@/hooks/useMcp";
import { useTranslation } from "@/i18n";
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
  const { t } = useTranslation();
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
      onFeedback(t("studio.panel.mcp.nameRequired"));
      return;
    }
    registerServer.mutate(
      { name: name.trim(), transport },
      {
        onSuccess: (server) => {
          setName("");
          onDraftChange({ mcpServerIds: [...draft.mcpServerIds, server.id] });
          onFeedback(t("studio.panel.mcp.registered"));
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
        onFeedback(t("studio.panel.mcp.deleted"));
      },
      onError: (error) => onFeedback(toApiError(error).message),
    });
  };

  return (
    <div className="space-y-4" data-testid="panel-mcp">
      <Card>
        <CardHeader>
          <CardTitle>{t("studio.panel.mcp.bindTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
          ) : (servers ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("studio.panel.mcp.empty")}</p>
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
                      {t("common.delete")}
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
            <CardTitle>{t("studio.panel.mcp.registerTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">{t("studio.panel.mcp.credentialsNote")}</p>
            <div className="space-y-2">
              <Label htmlFor="panel-mcp-name">{t("common.name")}</Label>
              <Input
                id="panel-mcp-name"
                data-testid="panel-mcp-name-input"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="panel-mcp-transport">{t("studio.panel.mcp.transport")}</Label>
              <Select value={transport} onValueChange={setTransport}>
                <SelectTrigger id="panel-mcp-transport" data-testid="panel-mcp-transport-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TRANSPORTS.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              size="sm"
              data-testid="panel-mcp-register"
              onClick={handleRegister}
              disabled={registerServer.isPending}
            >
              {t("studio.panel.mcp.register")}
            </Button>
          </CardContent>
        </Card>
      </RequirePermission>
    </div>
  );
}
