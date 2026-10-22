/**
 * T3-11 · MCP 服务（**8 op** + discover 物化）。
 *
 * | # | op | 成功码 | 错误 |
 * |---|---|---|---|
 * | 1 | GET `/mcp/servers` | 200 数组 | —— |
 * | 2 | POST `/mcp/servers` | **201** | `name` 空 ⇒ 422；transport 非法 ⇒ 422 |
 * | 3 | GET `/mcp/servers/{id}` | 200 | 不可见 ⇒ **404** |
 * | 4 | DELETE `/mcp/servers/{id}` | **204 零字节** | 404 |
 * | 5 | POST `/mcp/servers/{id}/discover` | 200 数组 | 404；被 MCP 端拒绝 ⇒ **502** |
 * | 6 | GET `/mcp/tools?server_id=` | 200 数组 | —— |
 * | 7 | GET `/mcp/permissions?mcp_tool_id=` | 200 数组 | `mcp_tool_id` 必填（契约） |
 * | 8 | POST `/mcp/permissions` | **201** | `mcp_tool_id` 不存在 ⇒ 404 |
 *
 * 三条硬口径
 * --------
 *   ① **`discover` 是幂等的**（验收 ②）：`McpToolRepo.discover` 以 `(server, name)` 为键，
 *      已存在则更新 `input_schema` / `discovered_at`，不产生第二行；
 *   ② **MCP 工具必须经 `ToolExecutor` 执行**（验收 ③ / 反例「直连 ⇒ 必红」）：
 *      本服务**不提供**任何"直接调用 MCP 工具"的方法；执行路径只有
 *      `modules/mcp/adapter.ts` 注册进 `ToolExecutor` 的那一条；
 *   ③ **出网必须过 `EgressPolicy`**（验收 ④）：`client.ts` 在 `http`/`sse` transport 上
 *      调 `checkEgress`，未登记域名一律拒。
 *
 * `DELETE` 为什么是 204 而 `DELETE /models/providers/{id}` 是 200
 * --------------------------------------------------------
 *   契约实测：MCP server 的 DELETE 是 **204 无响应体**（真删行），
 *   模型供应商的 DELETE 是 **200 + 整行**（软删）。两者语义不同，不能套模板。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import {
  MCP_DEFAULT_TRANSPORT,
  MCP_PERMISSION_ACTIONS,
  MCP_PERMISSION_DEFAULT_ACTION,
  MCP_PERMISSION_DEFAULT_EFFECT,
  MCP_PERMISSION_EFFECTS,
  MCP_TRANSPORTS,
  McpPermissionRepo,
  McpServerRepo,
  McpToolRepo,
  Scope,
  type DrizzleDatabase,
  type McpPermissionRow,
  type McpServerRow,
  type McpToolRow,
  type SqlDialect,
} from "@wbtime/db";

import { toIsoOrNull } from "../agent/versioning.js";
import { authError } from "../auth/errors.js";
import { discoverTools, McpTransportError, type CreateClientOptions } from "./client.js";

/** 列表上限（契约这些 op 无分页参数）。 */
export const MCP_LIST_LIMIT = 500;

/** 对外 server 视图（契约 `MCPServerResponse`，12 键）。 */
export interface McpServerView {
  readonly id: string;
  readonly name: string;
  readonly transport: string;
  readonly command: string | null;
  readonly args: readonly string[];
  readonly endpoint: string | null;
  readonly credential_id: string | null;
  readonly env_ref: Record<string, unknown> | null;
  readonly status: string;
  readonly workspace_id: string | null;
  readonly tenant_id: string | null;
  readonly created_at: string | null;
}

/** 对外 tool 视图（契约 `MCPToolResponse`，8 键）。 */
export interface McpToolView {
  readonly id: string;
  readonly mcp_server_id: string;
  readonly name: string;
  readonly description: string | null;
  readonly input_schema: Record<string, unknown>;
  readonly output_schema: Record<string, unknown> | null;
  readonly status: string;
  readonly discovered_at: string | null;
}

/** 对外 permission 视图（契约 `MCPPermissionResponse`，9 键）。 */
export interface McpPermissionView {
  readonly id: string;
  readonly mcp_tool_id: string;
  readonly agent_id: string | null;
  readonly agent_version_id: string | null;
  readonly action: string;
  readonly effect: string;
  readonly scope: Record<string, unknown> | null;
  readonly tenant_id: string | null;
  readonly created_at: string | null;
}

/** 注册入参（契约 `RegisterMCPServerRequest`，required 仅 `name`）。 */
export interface RegisterMcpServerInput {
  readonly name: string;
  readonly transport?: string;
  readonly command?: string | null;
  readonly args?: readonly string[];
  readonly endpoint?: string | null;
  readonly credentialId?: string | null;
  readonly envRef?: Record<string, unknown> | null;
  readonly workspaceId?: string | null;
}

/** 授权入参（契约 `CreateMCPPermissionRequest`，required 仅 `mcp_tool_id`）。 */
export interface CreateMcpPermissionInput {
  readonly mcpToolId: string;
  readonly agentId?: string | null;
  readonly agentVersionId?: string | null;
  readonly action?: string;
  readonly effect?: string;
  readonly scope?: Record<string, unknown> | null;
}

/** 服务依赖。 */
export interface McpServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
  readonly tenantId: string;
  /** 出网白名单（`http` transport 的 discover 用）。 */
  readonly egressAllowlist?: readonly string[];
  /** client 注入（测试用 fake；缺省真 SDK）。 */
  readonly discoverer?: (server: McpServerRow, scope: Scope) => Promise<readonly McpToolDescriptorLike[]>;
}

/** discover 的返回形态（与 `client.McpToolDescriptor` 同形；此处避免 import 环）。 */
export interface McpToolDescriptorLike {
  readonly name: string;
  readonly description?: string;
  readonly inputSchema: Record<string, unknown>;
  readonly outputSchema?: Record<string, unknown>;
}

/** MCP 服务（8 op）。 */
export class McpService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #tenantId: string;
  readonly #discoverer: NonNullable<McpServiceDeps["discoverer"]>;
  readonly #egressAllowlist: readonly string[] | undefined;

  constructor(deps: McpServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
    this.#tenantId = deps.tenantId;
    this.#egressAllowlist = deps.egressAllowlist;
    this.#discoverer =
      deps.discoverer ??
      ((server) =>
        discoverTools(
          {
            name: server.name,
            transport: server.transport,
            command: server.command,
            args: (server.args ?? []) as string[],
            endpoint: server.endpoint,
          },
          this.#clientOptions()
        ));
  }

  /** 1 · 本租户全部 MCP server。 */
  async listServers(): Promise<McpServerView[]> {
    const rows = await this.#servers().list({ limit: MCP_LIST_LIMIT });
    return rows.map(toServerView);
  }

  /**
   * 2 · 注册 server（201）。
   *
   * @throws {HttpException} 422（`name` 空 / transport 非法）。
   */
  async registerServer(input: RegisterMcpServerInput): Promise<McpServerView> {
    const name = (input.name ?? "").trim();
    if (name === "") {
      throw authError(ERROR_CODES.VALIDATION_ERROR, "MCP server 名称不能为空", { field: "name" });
    }
    const transport = (input.transport ?? MCP_DEFAULT_TRANSPORT).trim();
    if (!(MCP_TRANSPORTS as readonly string[]).includes(transport)) {
      throw authError(ERROR_CODES.VALIDATION_ERROR, `MCP transport 非法：${JSON.stringify(input.transport)}`, {
        field: "transport",
        allowed: [...MCP_TRANSPORTS],
      });
    }

    const row = await this.#servers().create({
      id: randomUUID(),
      name,
      transport,
      command: input.command ?? null,
      args: (input.args ?? []) as never,
      endpoint: input.endpoint ?? null,
      credentialId: input.credentialId ?? null,
      envRef: input.envRef ?? {},
      workspaceId: input.workspaceId ?? null,
    });
    return toServerView(row);
  }

  /**
   * 3 · server 详情。
   *
   * @throws {HttpException} 404。
   */
  async getServer(serverId: string): Promise<McpServerView> {
    return toServerView(await this.#requireServer(serverId));
  }

  /**
   * 4 · 删除 server（**204 真删**）。
   *
   * @throws {HttpException} 404。
   */
  async deleteServer(serverId: string): Promise<void> {
    const scope = new Scope(this.#tenantId);
    const removed = await this.#servers().remove(scope.ref(serverId));
    if (!removed) {
      throw notFoundServer(serverId);
    }
  }

  /**
   * 5 · 发现工具并**幂等物化**（200 返回物化后的行）。
   *
   * @throws {HttpException} 404（server 不可见）/ **502**（MCP 端拒绝或连不上）。
   */
  async discover(serverId: string): Promise<McpToolView[]> {
    const server = await this.#requireServer(serverId);
    const scope = new Scope(this.#tenantId);

    let descriptors: readonly McpToolDescriptorLike[];
    try {
      descriptors = await this.#discoverer(server, scope);
    } catch (error) {
      if (error instanceof McpTransportError) {
        throw authError(
          // 502 在 core 的码表里映射为 INTERNAL_ERROR（无独立 upstream 码）；
          // 不为此新增错误码（卡面红线：不新增错误码）。
          ERROR_CODES.INTERNAL_ERROR,
          `MCP discover 失败：${error.message}`,
          { server_id: serverId, reason: error.code }
        );
      }
      throw error;
    }

    const repo = new McpToolRepo(this.#db, scope, scope.ref(serverId), this.#dialect);
    const materialized: McpToolView[] = [];
    for (const descriptor of descriptors) {
      const row = await repo.discover({
        id: randomUUID(),
        name: descriptor.name,
        description: descriptor.description ?? null,
        inputSchema: descriptor.inputSchema,
        outputSchema: descriptor.outputSchema ?? null,
      });
      materialized.push(toToolView(row));
    }
    return materialized;
  }

  /**
   * 6 · 工具列表（`server_id` 可选：给了按 server 列，缺省聚合本租户全部）。
   */
  async listTools(serverId?: string | null): Promise<McpToolView[]> {
    const scope = new Scope(this.#tenantId);
    if (serverId !== undefined && serverId !== null && serverId !== "") {
      // 先验 server 可见（否则 `ensureParent` 会抛 ScopeError ⇒ 500）
      await this.#requireServer(serverId);
      const rows = await new McpToolRepo(this.#db, scope, scope.ref(serverId), this.#dialect).list({
        limit: MCP_LIST_LIMIT,
      });
      return rows.map(toToolView);
    }

    // 缺省聚合：按 server 逐个列（server 数量有上限，N+1 可接受；不新开跨父查询通道）
    const servers = await this.#servers().list({ limit: MCP_LIST_LIMIT });
    const all: McpToolView[] = [];
    for (const server of servers) {
      const rows = await new McpToolRepo(this.#db, scope, scope.ref(server.id), this.#dialect).list({
        limit: MCP_LIST_LIMIT,
      });
      all.push(...rows.map(toToolView));
    }
    return all;
  }

  /**
   * 7 · 某 MCP 工具的授权条目（契约 `mcp_tool_id` **必填**）。
   */
  async listPermissions(mcpToolId: string): Promise<McpPermissionView[]> {
    const rows = await this.#permissions().listByTool(mcpToolId, { limit: MCP_LIST_LIMIT });
    return rows.map(toPermissionView);
  }

  /**
   * 8 · 新增授权（201；幂等：同 `(tool, agent, action)` 已存在 ⇒ 返回既有行）。
   *
   * @throws {HttpException} 404（`mcp_tool_id` 不存在 / 不可见）。
   */
  async createPermission(input: CreateMcpPermissionInput): Promise<McpPermissionView> {
    const action = input.action ?? MCP_PERMISSION_DEFAULT_ACTION;
    const effect = input.effect ?? MCP_PERMISSION_DEFAULT_EFFECT;
    if (!(MCP_PERMISSION_ACTIONS as readonly string[]).includes(action)) {
      throw authError(ERROR_CODES.VALIDATION_ERROR, `action 非法：${JSON.stringify(input.action)}`, {
        field: "action",
        allowed: [...MCP_PERMISSION_ACTIONS],
      });
    }
    if (!(MCP_PERMISSION_EFFECTS as readonly string[]).includes(effect)) {
      throw authError(ERROR_CODES.VALIDATION_ERROR, `effect 非法：${JSON.stringify(input.effect)}`, {
        field: "effect",
        allowed: [...MCP_PERMISSION_EFFECTS],
      });
    }

    // 先验工具可见（FK 只查存在不查租户 ⇒ 必须由 scope 查询兜住）
    await this.#requireTool(input.mcpToolId);

    const row = await this.#permissions().grant({
      id: randomUUID(),
      mcpToolId: input.mcpToolId,
      agentId: input.agentId ?? null,
      agentVersionId: input.agentVersionId ?? null,
      action,
      effect,
      scope: input.scope ?? null,
    });
    return toPermissionView(row);
  }

  // -------------------------------------------------------------------------

  #servers(): McpServerRepo {
    return new McpServerRepo(this.#db, new Scope(this.#tenantId), this.#dialect);
  }

  #permissions(): McpPermissionRepo {
    return new McpPermissionRepo(this.#db, new Scope(this.#tenantId), this.#dialect);
  }

  #clientOptions(): CreateClientOptions {
    return this.#egressAllowlist === undefined ? {} : { egressAllowlist: this.#egressAllowlist };
  }

  /** scope 内取 server；不可见 ⇒ 404。 */
  async #requireServer(serverId: string): Promise<McpServerRow> {
    const scope = new Scope(this.#tenantId);
    const row = await this.#servers().findById(scope.ref(serverId));
    if (row === null) throw notFoundServer(serverId);
    return row;
  }

  /**
   * 找一个 mcp_tool 行（跨 server）。
   *
   * 为什么遍历而不是"直接按 id 查"：`McpToolRepo` 是子表仓储，父谓词恒在 ⇒ 没有
   * "只给 tool id" 的入口。遍历本租户的 server、逐个查子表，是**唯一**不新开跨父通道的
   * 做法（工具数量小，代价可接受）。
   */
  async #requireTool(mcpToolId: string): Promise<McpToolRow> {
    const scope = new Scope(this.#tenantId);
    const servers = await this.#servers().list({ limit: MCP_LIST_LIMIT });
    for (const server of servers) {
      const repo = new McpToolRepo(this.#db, scope, scope.ref(server.id), this.#dialect);
      const row = await repo.findById(mcpToolId);
      if (row !== null) return row;
    }
    throw notFoundTool(mcpToolId);
  }
}

/** 404（server）。 */
function notFoundServer(serverId: string) {
  return authError(ERROR_CODES.NOT_FOUND, "MCP server 不存在", { server_id: serverId });
}

/** 404（tool）。 */
function notFoundTool(toolId: string) {
  return authError(ERROR_CODES.NOT_FOUND, "MCP 工具不存在", { mcp_tool_id: toolId });
}

/** 行 → 视图（12 键）。 */
function toServerView(row: McpServerRow): McpServerView {
  return {
    id: row.id,
    name: row.name,
    transport: row.transport,
    command: row.command ?? null,
    args: (row.args ?? []) as readonly string[],
    endpoint: row.endpoint ?? null,
    credential_id: row.credential_id ?? null,
    env_ref: (row.env_ref ?? null) as Record<string, unknown> | null,
    status: row.status,
    workspace_id: row.workspace_id ?? null,
    tenant_id: row.tenant_id ?? null,
    created_at: toIsoOrNull(row.created_at),
  };
}

/** 行 → 视图（8 键）。 */
function toToolView(row: McpToolRow): McpToolView {
  return {
    id: row.id,
    mcp_server_id: row.mcp_server_id,
    name: row.name,
    description: row.description ?? null,
    input_schema: (row.input_schema ?? {}) as Record<string, unknown>,
    output_schema: (row.output_schema ?? null) as Record<string, unknown> | null,
    status: row.status,
    discovered_at: toIsoOrNull(row.discovered_at),
  };
}

/** 行 → 视图（9 键）。 */
function toPermissionView(row: McpPermissionRow): McpPermissionView {
  return {
    id: row.id,
    mcp_tool_id: row.mcp_tool_id,
    agent_id: row.agent_id ?? null,
    agent_version_id: row.agent_version_id ?? null,
    action: row.action,
    effect: row.effect,
    scope: (row.scope ?? null) as Record<string, unknown> | null,
    tenant_id: row.tenant_id ?? null,
    created_at: toIsoOrNull(row.created_at),
  };
}
