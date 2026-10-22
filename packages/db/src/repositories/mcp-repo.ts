/**
 * B2 · `mcp` 族仓储（**三张表 · 三个类**，同文件）。
 *
 * 三族的归属（DDL 实测）
 * --------------------
 * | 表 | 有 `tenant_id`？ | 父 | 基类 |
 * |---|---|---|---|
 * | `mcp_server` | 有（NOT NULL） | — | {@link McpServerRepo} ： `ScopedRepo` |
 * | `mcp_tool` | **没有** | `mcp_server_id` | {@link McpToolRepo} ： `ChildScopedRepo` |
 * | `mcp_permission` | 有（NOT NULL） | — | {@link McpPermissionRepo} ： `ScopedRepo` |
 *
 * 为什么 `mcp_tool` 必须走子表基类：它没有 `tenant_id`，租户归属只能经
 * `mcp_server_id → mcp_server.tenant_id` 回指。`ChildScopedRepo` 把"父谓词恒在"
 * 做成结构约束（`scopedWhere` 永远 and 上父 id），比在方法里手写 where 更硬（R3-22）。
 *
 * 两处**应用层**必须自己兜的不变量（零 DDL 的后果）
 * ---------------------------------------------
 * 1. **删 server 必须先删子表**（裁定 ⑥）：`mcp_tool.mcp_server_id → mcp_server.id`
 *    **没有** `ON DELETE CASCADE`（两档都没有）⇒ 直接删 server 会被外键拒。
 *    {@link McpServerRepo.remove} 因此先 `removeAll()` 子表再删自己。
 * 2. **租户级默认权限会被重复插**（硬约束 B）：`uq_mcp_permission_tool_agent_action`
 *    是 `(mcp_tool_id, agent_id, action)`，而 `agent_id` **可空**；SQL 的唯一约束在
 *    `NULL` 上不成立（NULL ≠ NULL）⇒ "租户级默认权限"（`agent_id IS NULL`）可以插出
 *    两行完全相同语义的记录。{@link McpPermissionRepo.grant} 因此**先查后插**，
 *    命中即幂等返回既有行（不新增行、不递增写次数）。
 *
 * 状态值域（证据）
 * --------------
 * * `status`：`MCPServerResponse.status` / `MCPToolResponse.status` 的 `default` 均为 `"ACTIVE"`；
 *   契约**没有**枚举 ⇒ 本层只定义 `ACTIVE` 一个常量，不编造 INACTIVE/DISABLED 之类对称值。
 * * `transport`：`RegisterMCPServerRequest.transport` 的 `default: "stdio"`，描述原文
 *   「传输（stdio/sse/http）」⇒ 3 值是契约给的，不是猜的。
 * * `action` / `effect`：`CreateMCPPermissionRequest` 描述原文「动作（EXECUTE/READ/WRITE）」
 *   「效果（ALLOW/DENY）」，缺省 `EXECUTE` / `DENY`。
 *
 * 契约面的一处**已知差异**（不动代码，只登记）：`POST /api/v1/mcp/permissions` 的
 * 契约描述写的是「经 `resource_permission` 落库（裁定 §21.4 X1/X2）……写运行期**唯一**
 * 判定源」。也就是说 `mcp_permission` 表**不是**运行期判定源的落点，判定源是
 * `resource_permission`（另一族，已有 `ResourcePermissionRepo`）。本族仍按任务卡实现
 * `mcp_permission` 的读写（表在、唯一约束在、硬约束 B 要求查重），但"谁写哪张表"
 * 属服务层编排，本层不替它决定。
 */

import {
  and,
  asc,
  desc,
  eq,
  isNull,
  type AnyColumn,
  type InferSelectModel,
  type SQL,
  type Table,
} from "drizzle-orm";

import {
  mcp_permission as pgMcpPermission,
  mcp_server as pgMcpServer,
  mcp_tool as pgMcpTool,
} from "../schema/pg/conversation.js";
import {
  mcp_permission as sqliteMcpPermission,
  mcp_server as sqliteMcpServer,
  mcp_tool as sqliteMcpTool,
} from "../schema/sqlite/conversation.js";
import {
  ChildScopedRepo,
  type ChildRepoOptions,
  type ChildScopedInsert,
} from "./child-scoped-repo.js";
import { instantLiteral, resolveTable, type SqlDialect } from "./dialect.js";
import {
  resolveListLimit,
  ScopedRepo,
  ScopeError,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type ScopedRef,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `mcp_server` 行。 */
export type McpServerRow = InferSelectModel<typeof pgMcpServer>;
/** `mcp_tool` 行。 */
export type McpToolRow = InferSelectModel<typeof pgMcpTool>;
/** `mcp_permission` 行。 */
export type McpPermissionRow = InferSelectModel<typeof pgMcpPermission>;

// ---------------------------------------------------------------------------
// 值域（证据见文件头注）
// ---------------------------------------------------------------------------

/** server 状态：启用（契约 default）。 */
export const MCP_SERVER_STATUS_ACTIVE = "ACTIVE";
/** tool 状态：启用（契约 default）。 */
export const MCP_TOOL_STATUS_ACTIVE = "ACTIVE";

/** 传输方式全集（契约 `RegisterMCPServerRequest.transport` 描述原文）。 */
export const MCP_TRANSPORTS = ["stdio", "sse", "http"] as const;
/** 缺省传输方式（契约 default）。 */
export const MCP_DEFAULT_TRANSPORT = "stdio";

/** 权限动作全集（契约 `CreateMCPPermissionRequest.action` 描述原文）。 */
export const MCP_PERMISSION_ACTIONS = ["EXECUTE", "READ", "WRITE"] as const;
/** 缺省动作（契约 default）。 */
export const MCP_PERMISSION_DEFAULT_ACTION = "EXECUTE";

/** 权限效果全集（契约 `CreateMCPPermissionRequest.effect` 描述原文）。 */
export const MCP_PERMISSION_EFFECTS = ["ALLOW", "DENY"] as const;
/** 缺省效果（契约 default）。 */
export const MCP_PERMISSION_DEFAULT_EFFECT = "DENY";

/** 是否合法传输方式。 */
export function isMcpTransport(value: string): boolean {
  return (MCP_TRANSPORTS as readonly string[]).includes(value);
}

/** 是否合法权限动作。 */
export function isMcpPermissionAction(value: string): boolean {
  return (MCP_PERMISSION_ACTIONS as readonly string[]).includes(value);
}

/** 是否合法权限效果。 */
export function isMcpPermissionEffect(value: string): boolean {
  return (MCP_PERMISSION_EFFECTS as readonly string[]).includes(value);
}

/** 注册 server 的入参（`status` / `tenant_id` / 时间戳**故意不在**）。 */
export interface RegisterMcpServerInput {
  readonly id: string;
  readonly name: string;
  /** 缺省 {@link MCP_DEFAULT_TRANSPORT}；非法值抛。 */
  readonly transport?: string;
  readonly endpoint?: string | null;
  readonly command?: string | null;
  /** 契约 `args` 是 array ⇒ 缺省 `[]`。 */
  readonly args?: readonly string[];
  /** 契约 `env_ref` 是 object ⇒ 缺省 `{}`。 */
  readonly envRef?: Record<string, unknown>;
  readonly credentialId?: string | null;
  readonly organizationId?: string | null;
  readonly workspaceId?: string | null;
  /** 缺省 {@link MCP_SERVER_STATUS_ACTIVE}（契约 default）。 */
  readonly status?: string;
  readonly capabilities?: Record<string, unknown> | null;
}

/** 落库一条发现到的工具（`discover` 的仓储面）。 */
export interface DiscoverMcpToolInput {
  readonly id: string;
  readonly name: string;
  readonly description?: string | null;
  readonly inputSchema?: Record<string, unknown> | null;
  readonly outputSchema?: Record<string, unknown> | null;
  /** 缺省 {@link MCP_TOOL_STATUS_ACTIVE}（契约 default）。 */
  readonly status?: string;
}

/** 新增权限的入参（`tenant_id` / 时间戳**故意不在**）。 */
export interface GrantMcpPermissionInput {
  readonly id: string;
  /** 目标 MCP 工具 id（列 NOT NULL）。 */
  readonly mcpToolId: string;
  /** 适用 agent；`null`/缺省 = **租户级默认权限**（硬约束 B 的重复插入点）。 */
  readonly agentId?: string | null;
  readonly agentVersionId?: string | null;
  /** 缺省 {@link MCP_PERMISSION_DEFAULT_ACTION}；非法值抛。 */
  readonly action?: string;
  /** 缺省 {@link MCP_PERMISSION_DEFAULT_EFFECT}；非法值抛。 */
  readonly effect?: string;
  readonly scope?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// mcp_server
// ---------------------------------------------------------------------------

export class McpServerRepo extends ScopedRepo<McpServerRow> {
  readonly #dialect: SqlDialect;
  readonly #table: Table;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    const table = resolveTable(dialect, pgMcpServer, sqliteMcpServer);
    super(db, table, scope);
    this.#dialect = dialect;
    this.#table = table;
  }

  /** 本租户的 server 列表（最近更新在前；`updated_at` 秒粒度 ⇒ `id` 兜底）。 */
  list(options: ListOptions = {}): Promise<McpServerRow[]> {
    return this.#ordered(undefined, options);
  }

  /** 按名字取（`uq_mcp_server_tenant_name`：租户内唯一）。 */
  findByName(name: string): Promise<McpServerRow | null> {
    return this.findOneWhere(eq(this.columns.name, name));
  }

  /**
   * 注册 server：`status` 缺省 `ACTIVE`、`transport` 缺省 `stdio`（都是契约 default）。
   *
   * @throws {ScopeError} `transport` 不在 `stdio/sse/http`。
   */
  create(input: RegisterMcpServerInput): Promise<McpServerRow> {
    const transport = input.transport ?? MCP_DEFAULT_TRANSPORT;
    if (!isMcpTransport(transport)) {
      throw new ScopeError(
        `mcpServer.create：transport 必须是 ${MCP_TRANSPORTS.join(" | ")}，实测 ${JSON.stringify(transport)}`,
      );
    }
    const now = instantLiteral(this.#dialect, new Date());
    const row: Record<string, unknown> = {
      id: input.id,
      organization_id: input.organizationId ?? null,
      workspace_id: input.workspaceId ?? null,
      name: input.name,
      transport,
      endpoint: input.endpoint ?? null,
      command: input.command ?? null,
      args: input.args ?? [],
      env_ref: input.envRef ?? {},
      credential_id: input.credentialId ?? null,
      status: input.status ?? MCP_SERVER_STATUS_ACTIVE,
      capabilities: input.capabilities ?? null,
      updated_at: now,
    };
    return this.insertRow(row as unknown as TenantScopedInsert<McpServerRow>);
  }

  /**
   * 删除 server（契约有 `DELETE /mcp/servers/{id}`，裁定 ⑥）。
   *
   * **必须先删子表**：`mcp_tool.mcp_server_id` 的外键没有 `ON DELETE CASCADE`（两档都没有），
   * 直接删 server 会被数据库拒。顺序：子表全删 → 删自己。
   *
   * @returns `false` = 本 scope 内没有这行（404 口径，**不**抛）。
   */
  async remove(serverRef: ScopedRef): Promise<boolean> {
    this.assertOwnRef(serverRef, "serverRef");
    const existing = await this.findById(serverRef);
    if (existing === null) return false;
    const tools = new McpToolRepo(
      this.db as unknown as DrizzleDatabase,
      this.scope,
      serverRef,
      this.#dialect,
    );
    await tools.removeAll();
    return super.remove(serverRef);
  }

  /** server 列表（`updated_at` 倒序 + `id` 兜底）。 */
  async #ordered(condition: SQL | undefined, options: ListOptions): Promise<McpServerRow[]> {
    const limit = resolveListLimit(this.tableName, options.limit);
    const orderColumn = this.columns[options.orderBy ?? "updated_at"];
    const primary: SQL[] =
      orderColumn === undefined
        ? []
        : [options.descending === false ? asc(orderColumn) : desc(orderColumn)];
    const chain = this.db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(condition))
      .orderBy(...primary, asc(this.columns.id))
      .limit(limit);
    return (await chain).slice() as McpServerRow[];
  }
}

// ---------------------------------------------------------------------------
// mcp_tool（子表：父 = mcp_server）
// ---------------------------------------------------------------------------

export class McpToolRepo extends ChildScopedRepo<McpToolRow, "mcp_server_id"> {
  readonly #table: Table;

  constructor(
    db: DrizzleDatabase,
    scope: Scope,
    serverRef: ScopedRef,
    dialect: SqlDialect = "pg",
  ) {
    const servers = new McpServerRepo(db, scope, dialect);
    const options: ChildRepoOptions = {
      parentColumn: "mcp_server_id",
      parentLabel: "mcp_server",
      parentExists: (ref) => servers.findById(ref).then((row) => row !== null),
    };
    const table = resolveTable(dialect, pgMcpTool, sqliteMcpTool);
    super(db, table, scope, serverRef, options);
    // 基类把表对象藏在真私有字段里（V0.1.0 闭版不给口子，裁定 ①）⇒ 子类自己留一份。
    this.#table = table;
  }

  /** 本 server 的工具目录（`discovered_at` 倒序 + `id` 兜底）。 */
  async list(options: ListOptions = {}): Promise<McpToolRow[]> {
    await this.ensureParent();
    const limit = resolveListLimit(this.tableName, options.limit);
    const chain = this.db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(undefined))
      .orderBy(desc(this.columns.discovered_at), asc(this.columns.id))
      .limit(limit);
    return (await chain).slice() as McpToolRow[];
  }

  /** 按名字取（`uq_mcp_tool_server_name`：同一 server 内唯一）。 */
  async findByName(name: string): Promise<McpToolRow | null> {
    return this.findOneWhere(eq(this.columns.name, name));
  }

  /**
   * 记录一条发现到的工具（`POST /mcp/servers/{id}/discover` 的落库面）。
   *
   * `(mcp_server_id, name)` 有唯一索引 ⇒ 应用层**先查后插**，重复时幂等返回既有行
   * （发现是"刷新目录"，重复发现同一工具不该报错，也不该插出第二行）。
   */
  async discover(input: DiscoverMcpToolInput): Promise<McpToolRow> {
    await this.ensureParent();
    const existing = await this.findByName(input.name);
    if (existing !== null) return existing;
    const row: Record<string, unknown> = {
      id: input.id,
      name: input.name,
      description: input.description ?? null,
      input_schema: input.inputSchema ?? null,
      output_schema: input.outputSchema ?? null,
      status: input.status ?? MCP_TOOL_STATUS_ACTIVE,
    };
    return this.insertRow(row as unknown as ChildScopedInsert<McpToolRow, "mcp_server_id">);
  }

  /**
   * 删掉本 server 的**全部**工具（供 `McpServerRepo.remove` 清场，裁定 ⑥）。
   *
   * @returns 删掉的行数。
   */
  async removeAll(): Promise<number> {
    await this.ensureParent();
    const rows = await (this.db
      .delete(this.#table)
      .where(this.scopedWhere(undefined))
      .returning() as unknown as PromiseLike<McpToolRow[]>);
    return rows.length;
  }

}

// ---------------------------------------------------------------------------
// mcp_permission
// ---------------------------------------------------------------------------

export class McpPermissionRepo extends ScopedRepo<McpPermissionRow> {
  readonly #dialect: SqlDialect;
  readonly #table: Table;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    const table = resolveTable(dialect, pgMcpPermission, sqliteMcpPermission);
    super(db, table, scope);
    this.#dialect = dialect;
    this.#table = table;
  }

  /** 某 MCP 工具的全部授权条目（契约 `GET /mcp/permissions?mcp_tool_id=`）。 */
  async listByTool(toolId: string, options: ListOptions = {}): Promise<McpPermissionRow[]> {
    const limit = resolveListLimit(this.tableName, options.limit);
    const chain = this.db
      .select()
      .from(this.#table)
      .where(this.scopedWhere(eq(this.columns.mcp_tool_id, toolId)))
      .orderBy(desc(this.columns.created_at), asc(this.columns.id))
      .limit(limit);
    return (await chain).slice() as McpPermissionRow[];
  }

  /**
   * 新增一条授权（**幂等**：同一 `(tool, agent|null, action)` 已存在时直接返回既有行）。
   *
   * 为什么必须应用层查重：唯一索引是 `(mcp_tool_id, agent_id, action)`，而 `agent_id`
   * 可空 —— SQL 里 `NULL` 互不相等，唯一约束对"租户级默认权限"完全失效。不查重就会
   * 插出两行语义相同的记录，判定时先命中哪行取决于物理顺序（**不可判定**）。
   *
   * @throws {ScopeError} `action` / `effect` 不在契约值域内。
   */
  async grant(input: GrantMcpPermissionInput): Promise<McpPermissionRow> {
    const action = input.action ?? MCP_PERMISSION_DEFAULT_ACTION;
    const effect = input.effect ?? MCP_PERMISSION_DEFAULT_EFFECT;
    if (!isMcpPermissionAction(action)) {
      throw new ScopeError(
        `mcpPermission.grant：action 必须是 ${MCP_PERMISSION_ACTIONS.join(" | ")}，实测 ${JSON.stringify(action)}`,
      );
    }
    if (!isMcpPermissionEffect(effect)) {
      throw new ScopeError(
        `mcpPermission.grant：effect 必须是 ${MCP_PERMISSION_EFFECTS.join(" | ")}，实测 ${JSON.stringify(effect)}`,
      );
    }

    const agentId = input.agentId ?? null;
    // 幂等键 = (mcp_tool_id, agent_id, action)；`agent_id IS NULL` 必须用 isNull 精确匹配，
    // 不能用 `eq(..., null)`（生成的 SQL 会是 `= NULL`，永远不成立）。
    const existing = await this.findOneWhere(
      and(
        eq(this.columns.mcp_tool_id, input.mcpToolId),
        agentId === null ? isNull(this.columns.agent_id) : eq(this.columns.agent_id, agentId),
        eq(this.columns.action, action),
      ),
    );
    if (existing !== null) return existing;

    const now = instantLiteral(this.#dialect, new Date());
    const row: Record<string, unknown> = {
      id: input.id,
      agent_id: agentId,
      agent_version_id: input.agentVersionId ?? null,
      mcp_tool_id: input.mcpToolId,
      action,
      effect,
      scope: input.scope ?? null,
      updated_at: now,
    };
    return this.insertRow(row as unknown as TenantScopedInsert<McpPermissionRow>);
  }

  /** 某工具的"租户级默认权限"（`agent_id IS NULL` 的全部行；查重正确性的观测口）。 */
  listTenantDefaults(toolId: string): Promise<McpPermissionRow[]> {
    return this.findManyWhere(
      and(eq(this.columns.mcp_tool_id, toolId), isNull(this.columns.agent_id)),
      { orderBy: "created_at", descending: false, limit: 500 },
    );
  }
}
