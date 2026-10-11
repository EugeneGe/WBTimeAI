import { api } from "@/lib/api";
import type {
  CreateMCPPermissionRequest,
  MCPPermissionResponse,
  MCPServerResponse,
  MCPToolResponse,
  RegisterMCPServerRequest,
} from "@/types";

/**
 * MCP 服务（`/mcp/*` API，W3 / T2-18；设计 §2.4 / §2.12）。
 *
 * - Server 注册生命周期：注册 / 列表 / 详情 / 删除；
 * - 工具发现（落 `mcp_tool`）+ 工具目录；
 * - 授权（agent × mcp_tool × effect × scope）。
 *
 * 🔴 凭据**仅引用 / 仅掩码**（C-07）：本服务**不传输、不回显**任何明文密钥。
 */
export const mcpService = {
  /** MCP Server 列表（当前租户）。 */
  listServers(): Promise<MCPServerResponse[]> {
    return api.get<MCPServerResponse[]>("/mcp/servers").then((r) => r.data);
  },
  /** MCP Server 详情。 */
  getServer(serverId: string): Promise<MCPServerResponse> {
    return api.get<MCPServerResponse>(`/mcp/servers/${serverId}`).then((r) => r.data);
  },
  /** 注册 MCP Server（凭据**仅引用**）。 */
  registerServer(payload: RegisterMCPServerRequest): Promise<MCPServerResponse> {
    return api.post<MCPServerResponse>("/mcp/servers", payload).then((r) => r.data);
  },
  /** 删除 MCP Server。 */
  deleteServer(serverId: string): Promise<void> {
    return api.delete<void>(`/mcp/servers/${serverId}`).then(() => undefined);
  },
  /** 发现 Server 的工具（落 `mcp_tool` 目录）。 */
  discover(serverId: string): Promise<MCPToolResponse[]> {
    return api.post<MCPToolResponse[]>(`/mcp/servers/${serverId}/discover`).then((r) => r.data);
  },
  /** 工具目录（可按 `serverId` 过滤）。 */
  listTools(serverId?: string): Promise<MCPToolResponse[]> {
    return api
      .get<MCPToolResponse[]>("/mcp/tools", { params: serverId ? { server_id: serverId } : {} })
      .then((r) => r.data);
  },
  /** 某 MCPTool 的授权列表。 */
  listPermissions(mcpToolId: string): Promise<MCPPermissionResponse[]> {
    return api
      .get<MCPPermissionResponse[]>("/mcp/permissions", { params: { mcp_tool_id: mcpToolId } })
      .then((r) => r.data);
  },
  /** 新增一条 MCP Tool 授权。 */
  createPermission(payload: CreateMCPPermissionRequest): Promise<MCPPermissionResponse> {
    return api.post<MCPPermissionResponse>("/mcp/permissions", payload).then((r) => r.data);
  },
};
