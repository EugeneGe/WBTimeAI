/**
 * T3-14 · 工具执行面（**唯一**把"模型能请求什么"与"执行器能执行什么"对齐的地方）。
 *
 * 为什么需要这一层（补 T3-10 遗留 #3 与 T3-11 遗留 #1）
 * ------------------------------------------------
 *   实测接线前：`ToolExecutor` 全仓零实例化；`createMcpToolAdapter()` 零调用点；
 *   `resolveTool()` 只查 `BUILTIN_REGISTRY` ⇒ MCP 工具**结构上不可达**。
 *   本文件把三者缝到一起，且**不碰** T3-10 / T3-11 已闭版的文件：
 *
 *   - 内置工具：直接从 `BUILTIN_REGISTRY`（实现）+ `BUILTIN_TOOLS`（`input_schema` 真源，
 *     R3-23 ①）取 —— **不重复注册**，不新造第二份名单；
 *   - MCP 工具：从 `mcp_server` / `mcp_tool` 两表（discover 已幂等物化的结果）读，
 *     逐个包成 `BuiltinTool`（`mcp/adapter.ts::createMcpToolAdapter`），名字带
 *     `mcp:<server>/<tool>` 命名空间 ⇒ 与内置永不撞名；
 *   - 两者合成一张 `Map`，既交给 `ToolExecutor`（`tools` 覆盖项，T3-10 已留的口子），
 *     又折成 `ModelToolSpec[]` 交给 `AgentLoop`（模型这一侧看到的工具清单）。
 *
 * 为什么 MCP 工具**只在 run 装配时读库**而不是启动时缓存
 * --------------------------------------------------
 *   `POST /mcp/servers/{id}/discover` 是运行期 op：用户随时可能注册新的 server。
 *   启动时缓存一份，就等于"新注册的 MCP 工具要重启才生效"，而重启是本版最贵的操作。
 *   每个 run 一次读库的代价可接受（run 本身就有多次 DB 往返）。
 *
 * 分层：本文件属于 **apps/api 的模块层**，允许 import `@wbtime/db` 仓储
 * （`orm-only-in-repositories` 规则只辖 `packages/**`，见 `.dependency-cruiser.cjs`）。
 */

import {
  BUILTIN_TOOLS,
  McpServerRepo,
  McpToolRepo,
  Scope,
  type DrizzleDatabase,
  type McpServerRow,
  type McpToolRow,
  type SqlDialect,
} from "@wbtime/db";
import type { ModelToolSpec } from "@wbtime/domain";

import { createMcpToolAdapter, mcpToolName } from "../mcp/adapter.js";
import { createMcpClient, type McpServerTarget } from "../mcp/client.js";
import { BUILTIN_REGISTRY, type BuiltinTool } from "../tool/registry.js";

/** 一个 run 的工具执行面（`tools` 给执行器，`specs` 给模型）。 */
export interface ToolSurface {
  /** 工具名 → 实现（内置 + MCP；MCP 带 `mcp:` 前缀）。 */
  readonly tools: ReadonlyMap<string, BuiltinTool>;
  /** 模型可见的工具规格（顺序：内置 6 个按注册表顺序，其后 MCP 按名字升序）。 */
  readonly specs: readonly ModelToolSpec[];
  /** MCP 工具的归属表（`name → {server, tool}`），供 `mcp.*` 帧与授权串使用。 */
  readonly mcp: ReadonlyMap<string, { readonly server: string; readonly tool: string }>;
}

/**
 * 内置工具的模型规格（`input_schema` 取 `packages/db` 的真源，不在此处手抄）。
 *
 * @returns 6 条 `ModelToolSpec`（顺序 == `BUILTIN_TOOLS` 的顺序）。
 */
export function builtinToolSpecs(): ModelToolSpec[] {
  return BUILTIN_TOOLS.map((spec) => ({
    name: spec.name,
    description: spec.description,
    inputSchema: spec.inputSchema,
  }));
}

/** MCP 行 → 连接目标（`McpServerTarget` 只取连接字段）。 */
function toServerTarget(row: McpServerRow): McpServerTarget {
  return {
    name: row.name,
    transport: row.transport,
    ...(row.command === null || row.command === undefined ? {} : { command: row.command }),
    ...(row.args === null || row.args === undefined ? {} : { args: row.args as readonly string[] }),
    ...(row.endpoint === null || row.endpoint === undefined ? {} : { endpoint: row.endpoint }),
  };
}

/** 装载选项。 */
export interface LoadMcpToolsOptions {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
  readonly tenantId: string;
  /** 出网白名单（http transport 用；缺省 ⇒ `checkEgress` 拒绝全部）。 */
  readonly egressAllowlist?: readonly string[];
}

/** MCP 装载结果（工具实现 + 归属 + 描述符行，一次读库产出三样）。 */
export interface LoadedMcpTools {
  readonly tools: Map<string, BuiltinTool>;
  readonly owned: Map<string, { readonly server: string; readonly tool: string }>;
  readonly descriptors: Map<string, McpToolRow>;
}

/** 单次读库的行数上界（与 `ListOptions` 的 500 上限一致）。 */
const MCP_LIST_LIMIT = 500;

/**
 * 从库里的 MCP 注册表装载工具（**幂等、只读、不 discover**）。
 *
 * 只读已物化的行：`discover` 是显式 op（`POST /mcp/servers/{id}/discover`），run 装配
 * 不该偷偷替用户去连一遍 server —— 那会让"跑一次 agent"隐式产生网络副作用。
 *
 * @returns `{tools, owned, descriptors}`（空库 ⇒ 三个空 Map，不是错误）。
 */
export async function loadMcpTools(options: LoadMcpToolsOptions): Promise<LoadedMcpTools> {
  const scope = new Scope(options.tenantId);
  const servers = await new McpServerRepo(options.db, scope, options.dialect).list({
    limit: MCP_LIST_LIMIT,
  });
  const tools = new Map<string, BuiltinTool>();
  const owned = new Map<string, { server: string; tool: string }>();
  const descriptors = new Map<string, McpToolRow>();

  for (const server of servers) {
    // 只装 ACTIVE 的 server：停用的 server 其工具不该被模型看见（否则模型会请求一个
    // 必然失败的调用，把"运维停用"变成"模型反复重试"）。
    if (server.status !== "ACTIVE") continue;
    const rows: McpToolRow[] = await new McpToolRepo(
      options.db,
      scope,
      scope.ref(server.id),
      options.dialect
    ).list({ limit: MCP_LIST_LIMIT });
    const target = toServerTarget(server);
    for (const row of rows) {
      const name = mcpToolName(server.name, row.name);
      // 已存在（同 server 同名工具）⇒ 不覆盖：首个胜出，避免插入顺序决定行为。
      if (tools.has(name)) continue;
      tools.set(
        name,
        createMcpToolAdapter({
          server: target,
          tool: {
            name: row.name,
            inputSchema: (row.input_schema ?? { type: "object" }) as Record<string, unknown>,
            ...(row.description === null || row.description === undefined
              ? {}
              : { description: row.description }),
          },
          createClient: createMcpClient,
          ...(options.egressAllowlist === undefined
            ? {}
            : { egressAllowlist: options.egressAllowlist }),
        })
      );
      owned.set(name, { server: server.name, tool: row.name });
      descriptors.set(name, row);
    }
  }

  return { tools, owned, descriptors };
}

/**
 * 组装一个 run 的工具执行面。
 *
 * @param options `db` / `dialect` / `tenantId` + 可选出网白名单。
 * @returns 见 {@link ToolSurface}（内置 6 个恒在；MCP 按库里有几个装几个）。
 */
export async function buildToolSurface(options: LoadMcpToolsOptions): Promise<ToolSurface> {
  const tools = new Map<string, BuiltinTool>(BUILTIN_REGISTRY);
  const loaded = await loadMcpTools(options);
  for (const [name, tool] of loaded.tools) {
    // 命名空间已由 `mcp:` 前缀保证不撞名；这里再守一道 —— 万一有人给内置工具起名
    // `mcp:xxx`，宁可让 MCP 不生效，也不让外部 server 顶掉内置实现。
    if (tools.has(name)) continue;
    tools.set(name, tool);
  }

  const specs: ModelToolSpec[] = [...builtinToolSpecs()];
  for (const name of [...loaded.descriptors.keys()].sort()) {
    if (!tools.has(name)) continue;
    const row = loaded.descriptors.get(name);
    if (row === undefined) continue;
    specs.push({
      name,
      description: row.description ?? `MCP 工具 ${name}`,
      inputSchema: (row.input_schema ?? { type: "object" }) as Record<string, unknown>,
    });
  }

  return { tools, specs, mcp: loaded.owned };
}

/**
 * 工具名 → `tool_call.tool_type`（列 NOT NULL）。
 *
 * MCP 工具归 `mcp`，内置归 `builtin`；未知工具（模型幻觉出的名字）归 `unknown`
 * —— 它本来就不会走到执行器（`ToolExecutor` 段 1 就返回 `FAILED`），这里给一个
 * 诚实值而不是猜一个"看起来对"的。
 */
export function toolTypeOf(toolName: string, surface: ToolSurface): string {
  if (surface.mcp.has(toolName)) return "mcp";
  return BUILTIN_REGISTRY.has(toolName) ? "builtin" : "unknown";
}
