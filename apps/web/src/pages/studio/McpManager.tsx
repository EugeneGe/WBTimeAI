import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateMcpPermission,
  useDeleteMcpServer,
  useDiscoverMcpTools,
  useMcpPermissions,
  useMcpServers,
  useMcpTools,
  useRegisterMcpServer,
} from "@/hooks/useMcp";
import { usePermissionCheck } from "@/hooks/usePermissionCheck";
import { toApiError } from "@/lib/api";
import type { MCPServerResponse } from "@/types";

/** 传输类型选项。 */
const TRANSPORTS = ["stdio", "sse", "http"] as const;
/** MCP 授权动作。 */
const ACTIONS = ["EXECUTE", "READ", "WRITE"] as const;
/** MCP 授权效果。 */
const EFFECTS = ["ALLOW", "DENY"] as const;

/**
 * 把凭据**引用**渲染为掩码（**绝不**回显明文；C-07）。
 *
 * MCP Server 的 `credential_id` / `env_ref` 均为引用，不含明文；此处仅以掩码
 * 呈现引用尾部，避免任何明文泄露。
 */
function maskReference(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  return value.length <= 4 ? "••••" : `••••${value.slice(-4)}`;
}

/**
 * MCP Manager（W3 / T2-18；设计 §2.4 / §2.12）。
 *
 * - Server 注册（transport / endpoint / **凭据掩码**）；
 * - 工具发现（落 `mcp_tool`）+ 工具目录；
 * - 授权配置（agent × mcp_tool × effect × scope）。
 *
 * 🔴 动作级守卫经 {@link RequirePermission}（`can()`）；另以
 *    {@link usePermissionCheck} 展示**后端** capability 判定（前端不做本地推断）。
 */
export function McpManager() {
  const { data: servers, isLoading } = useMcpServers();
  const [selectedServerId, setSelectedServerId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const registerServer = useRegisterMcpServer();
  const deleteServer = useDeleteMcpServer();
  const discoverTools = useDiscoverMcpTools();

  // 后端 capability 判定（`can()` 数据源）：删除动作。
  const deleteCheck = usePermissionCheck("mcp:delete");

  // 注册表单。
  const [name, setName] = useState("");
  const [transport, setTransport] = useState<string>("stdio");
  const [endpoint, setEndpoint] = useState("");
  const [command, setCommand] = useState("");
  const [credentialId, setCredentialId] = useState("");

  const handleRegister = (): void => {
    if (!name.trim()) {
      setFeedback("请填写 Server 名");
      return;
    }
    registerServer.mutate(
      {
        name: name.trim(),
        transport,
        endpoint: endpoint.trim() || null,
        command: command.trim() || null,
        // 凭据**仅引用**（不回传明文）。
        credential_id: credentialId.trim() || null,
      },
      {
        onSuccess: (server) => {
          setName("");
          setEndpoint("");
          setCommand("");
          setCredentialId("");
          setSelectedServerId(server.id);
          setFeedback("Server 已注册");
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const handleDelete = (server: MCPServerResponse): void => {
    deleteServer.mutate(server.id, {
      onSuccess: () => {
        if (selectedServerId === server.id) {
          setSelectedServerId(null);
        }
        setFeedback("Server 已删除");
      },
      onError: (error) => setFeedback(toApiError(error).message),
    });
  };

  const handleDiscover = (server: MCPServerResponse): void => {
    discoverTools.mutate(server.id, {
      onSuccess: (tools) => setFeedback(`发现 ${tools.length} 个工具`),
      onError: (error) => setFeedback(toApiError(error).message),
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">MCP Manager</h1>
        <div className="flex items-center gap-2">
          {deleteCheck.data ? (
            <Badge variant={deleteCheck.data.allowed ? "default" : "secondary"}>
              mcp:delete {deleteCheck.data.allowed ? "允许" : "拒绝"}
            </Badge>
          ) : null}
          {feedback ? (
            <span className="text-xs text-muted-foreground" data-testid="mcp-feedback">
              {feedback}
            </span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        {/* 左：Server 列表 + 工具目录 + 授权 */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>MCP Servers</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>传输</TableHead>
                    <TableHead>端点 / 命令</TableHead>
                    <TableHead>凭据（掩码）</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {isLoading ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-muted-foreground">
                        加载中…
                      </TableCell>
                    </TableRow>
                  ) : (servers ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-muted-foreground">
                        暂无 Server
                      </TableCell>
                    </TableRow>
                  ) : (
                    (servers ?? []).map((server) => (
                      <TableRow
                        key={server.id}
                        data-testid={`mcp-server-${server.name}`}
                        className={selectedServerId === server.id ? "bg-accent/40" : ""}
                      >
                        <TableCell className="font-medium">{server.name}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{server.transport}</Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {server.endpoint || server.command || "—"}
                        </TableCell>
                        <TableCell
                          className="font-mono text-xs"
                          data-testid={`mcp-credential-${server.name}`}
                        >
                          {maskReference(server.credential_id)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setSelectedServerId(server.id)}
                            >
                              工具
                            </Button>
                            <RequirePermission code="mcp:discover">
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={discoverTools.isPending}
                                onClick={() => handleDiscover(server)}
                              >
                                发现
                              </Button>
                            </RequirePermission>
                            <RequirePermission code="mcp:delete">
                              <Button
                                variant="ghost"
                                size="sm"
                                data-testid={`mcp-delete-${server.name}`}
                                disabled={deleteServer.isPending}
                                onClick={() => handleDelete(server)}
                              >
                                删除
                              </Button>
                            </RequirePermission>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {selectedServerId ? (
            <ToolCatalog serverId={selectedServerId} onFeedback={setFeedback} />
          ) : (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                选择 Server 以查看工具目录 / 配置授权
              </CardContent>
            </Card>
          )}
        </div>

        {/* 右：注册表单 */}
        <RequirePermission code="mcp:create">
          <Card>
            <CardHeader>
              <CardTitle>注册 Server</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground" data-testid="mcp-credential-note">
                凭据**仅引用 / 仅掩码**：填写凭证标识（引用），**不输入明文密钥**。
              </p>
              <div className="space-y-2">
                <Label htmlFor="mcp-name">名称</Label>
                <Input
                  id="mcp-name"
                  data-testid="mcp-name-input"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="mcp-transport">传输</Label>
                <select
                  id="mcp-transport"
                  data-testid="mcp-transport-select"
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
              <div className="space-y-2">
                <Label htmlFor="mcp-endpoint">端点（http/sse）</Label>
                <Input
                  id="mcp-endpoint"
                  value={endpoint}
                  onChange={(event) => setEndpoint(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="mcp-command">命令（stdio）</Label>
                <Input
                  id="mcp-command"
                  value={command}
                  onChange={(event) => setCommand(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="mcp-credential">凭证引用（仅标识）</Label>
                <Input
                  id="mcp-credential"
                  data-testid="mcp-credential-input"
                  value={credentialId}
                  onChange={(event) => setCredentialId(event.target.value)}
                />
              </div>
              <Button
                size="sm"
                data-testid="mcp-register-submit"
                onClick={handleRegister}
                disabled={registerServer.isPending}
              >
                注册
              </Button>
            </CardContent>
          </Card>
        </RequirePermission>
      </div>
    </div>
  );
}

/** 工具目录 + 授权配置（按 Server 维度）。 */
function ToolCatalog({
  serverId,
  onFeedback,
}: {
  serverId: string;
  onFeedback: (message: string) => void;
}) {
  const { data: tools } = useMcpTools(serverId);
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);

  const effectiveToolId = selectedToolId ?? tools?.[0]?.id ?? null;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>工具目录</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>工具</TableHead>
                <TableHead>描述</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">授权</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(tools ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    暂无工具（可点击「发现」）
                  </TableCell>
                </TableRow>
              ) : (
                (tools ?? []).map((tool) => (
                  <TableRow key={tool.id} data-testid={`mcp-tool-${tool.name}`}>
                    <TableCell className="font-medium">{tool.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {tool.description || "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{tool.status}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => setSelectedToolId(tool.id)}>
                        配置
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {effectiveToolId ? (
        <PermissionConfig mcpToolId={effectiveToolId} onFeedback={onFeedback} />
      ) : null}
    </div>
  );
}

/** MCP Tool 授权配置（agent × mcp_tool × effect × scope）。 */
function PermissionConfig({
  mcpToolId,
  onFeedback,
}: {
  mcpToolId: string;
  onFeedback: (message: string) => void;
}) {
  const { data: permissions } = useMcpPermissions(mcpToolId);
  const createPermission = useCreateMcpPermission();

  const [agentId, setAgentId] = useState("");
  const [action, setAction] = useState<string>("EXECUTE");
  const [effect, setEffect] = useState<string>("ALLOW");
  const [scopeText, setScopeText] = useState("{}");

  const handleGrant = (): void => {
    let scope: Record<string, unknown> = {};
    try {
      const parsed: unknown = JSON.parse(scopeText || "{}");
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        onFeedback("scope 需为 JSON 对象");
        return;
      }
      scope = parsed as Record<string, unknown>;
    } catch {
      onFeedback("scope JSON 解析失败");
      return;
    }
    createPermission.mutate(
      {
        mcp_tool_id: mcpToolId,
        agent_id: agentId.trim() || null,
        action,
        effect,
        scope,
      },
      {
        onSuccess: () => onFeedback("授权已写入"),
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>授权配置</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="mcp-agent">Agent（可空）</Label>
            <Input
              id="mcp-agent"
              value={agentId}
              onChange={(event) => setAgentId(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="mcp-action">动作</Label>
            <select
              id="mcp-action"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={action}
              onChange={(event) => setAction(event.target.value)}
            >
              {ACTIONS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="mcp-effect">效果</Label>
          <select
            id="mcp-effect"
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={effect}
            onChange={(event) => setEffect(event.target.value)}
          >
            {EFFECTS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="mcp-scope">scope（JSON）</Label>
          <textarea
            id="mcp-scope"
            className="min-h-[72px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
            value={scopeText}
            onChange={(event) => setScopeText(event.target.value)}
          />
        </div>
        <RequirePermission code="mcp:permission">
          <Button
            size="sm"
            data-testid="mcp-permission-submit"
            onClick={handleGrant}
            disabled={createPermission.isPending}
          >
            写入授权
          </Button>
        </RequirePermission>

        <ul className="space-y-1 text-xs" data-testid="mcp-permission-list">
          {(permissions ?? []).length === 0 ? (
            <li className="text-muted-foreground">暂无授权</li>
          ) : (
            (permissions ?? []).map((permission) => (
              <li key={permission.id} className="flex items-center justify-between">
                <span>
                  {permission.agent_id || "租户级"} · {permission.action}
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
  );
}
