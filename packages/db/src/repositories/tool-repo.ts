/**
 * T3-03 · `tool` 仓储 + 内置工具注册表 + `ensureBuiltinTools`（**R3-23**）。
 *
 * 三件事写在同一个文件里，因为它们的口径互相绑定：
 *   1. **注册表**（`BUILTIN_TOOLS`）：6 个内置工具的 `input_schema` **唯一真源**（第 6 个 `spawn_agent` 为 V0.3.1 · G031-SPK 新增）；
 *   2. **物化**（{@link ToolRepo.ensureBuiltinTools}）：把注册表按租户写进 `tool` 表，
 *      **幂等**（两次调用 ⇒ 仍 5 行）；
 *   3. **借位读取**（{@link readToolPermissionAction}）：`tool` 表没有
 *      `permission_action` 列（零 DDL ⇒ 不能加），权限动作借 `tool_ref` JSON 承载。
 *
 * 注册表的来源（**不是猜的**）
 * ---------------------------
 * 5 个工具的 `input_schema` / `display_name` / `category` / `description` /
 * `permission.action` / `requires_sandbox` 逐字取自 py 线
 * `packages/tool/src/wbtime_ai_tool/tools/{filesystem,git,http,shell,python}.py`
 * 的 `SPEC`。唯一**没有**真源的是 `code_exec` —— 它是 Q-4 把 py 的 `python` 泛化后的
 * 产物，schema 属新增，由 team-lead 裁定为「`python` 的 schema + `runtime`」（见
 * {@link CODE_EXEC_DEFAULT_RUNTIME} 的注释）。
 *
 * 零 DDL 下的三个已知弱点（都做了兜底，但兜底不是索引）
 * --------------------------------------------------
 * * `tool` **没有 `(tenant_id, name)` 唯一索引** ⇒ 并发多进程首启可能插重复。
 *   裁定 R3-23 ③ 把 `ensureBuiltinTools` 限定为**单写者**（bootstrap 期、进程内串行），
 *   并由 {@link ToolRepo.findDuplicates} 提供查询级自检（重复 ⇒ 判红，人工清理）。
 * * `permission_action` 无列 ⇒ 借位 `tool_ref`（读取封在 {@link readToolPermissionAction}）。
 * * `tool_version` 无 `(tool_id, version)` 唯一索引 ⇒ 同样"先查后插"。
 */

import { randomUUID } from "node:crypto";

import {
  eq,
  getTableColumns,
  type AnyColumn,
  type InferSelectModel,
  type Table,
} from "drizzle-orm";

import { tool as pgTool, tool_version as pgToolVersion } from "../schema/pg/tool.js";
import { tool as sqliteTool, tool_version as sqliteToolVersion } from "../schema/sqlite/tool.js";
import { resolveTable, type SqlDialect } from "./dialect.js";
import {
  ScopedRepo,
  ScopeError,
  type DrizzleDatabase,
  type ListOptions,
  type Scope,
  type TenantScopedInsert,
} from "./scoped-repo.js";

/** `tool` 行。 */
export type ToolRow = InferSelectModel<typeof pgTool>;

/** `tool_version` 行（R3-23 ⑤：本版每工具只登记 1 行 `v1`）。 */
export type ToolVersionRow = InferSelectModel<typeof pgToolVersion>;

/** `tool.source` 的内置工具取值（同时也映射契约 `ToolResponse.type` 的 default）。 */
export const TOOL_SOURCE_BUILTIN = "builtin";

/** 内置工具落库状态（`active`）。 */
export const TOOL_STATUS_ACTIVE = "active";

/** 本版唯一登记的版本号（R3-23 ⑤）。 */
export const BUILTIN_TOOL_VERSION = "v1";

/**
 * `code_exec` 允许的解释器（team-lead 裁定的 3 值）。
 *
 * 顺序即枚举顺序，**改动会改变 `input_schema` 序列化结果** ⇒ 必须同步 `builtin-tools`
 * 的逐字节断言。
 */
export const CODE_EXEC_RUNTIMES = ["python", "node", "bash"] as const;

/**
 * `code_exec.runtime` 的缺省值 —— **全仓唯一定义处**。
 *
 * 为什么缺省 `python`：R3-18 的等价判据是「`runtime=python` 与 py 线 `python` 工具等价」。
 * 若 `runtime` 必填，py 的既有输入 `{code, timeout_ms}` 就不再合法 ⇒ 直接破坏该判据的主语。
 * 因此 `runtime` **不进 `required`**，缺省值只在这里出现，路由/服务层**不得**再写 `?? "python"`。
 */
export const CODE_EXEC_DEFAULT_RUNTIME = CODE_EXEC_RUNTIMES[0];

/** 工具权限动作（py `ToolPermissionRequirement.action` 的三个取值）。 */
export type ToolPermissionAction = "READ" | "WRITE" | "EXECUTE";

/** 内置工具注册表条目。 */
export interface BuiltinToolSpec {
  readonly name: string;
  readonly displayName: string;
  readonly description: string;
  readonly category: string;
  readonly permissionAction: ToolPermissionAction;
  readonly requiresSandbox: boolean;
  /** `input_schema` 的**固定字面量**（键序即序列化顺序，禁止运行时重排）。 */
  readonly inputSchema: Readonly<Record<string, unknown>>;
}

/**
 * `code_exec` 的 `input_schema`。
 *
 * = py `python` 的 `{code, timeout_ms}` **+ `runtime`**（裁定见
 * {@link CODE_EXEC_DEFAULT_RUNTIME}）。`runtime` 放在最后 ⇒ 前两个键的**顺序与名字**
 * 与 py 真源逐字相同，diff 时一眼能看出"只多了一个键"。
 */
const CODE_EXEC_INPUT_SCHEMA = {
  type: "object",
  properties: {
    code: { type: "string", minLength: 1 },
    timeout_ms: { type: "integer", minimum: 1 },
    runtime: { type: "string", enum: ["python", "node", "bash"] },
  },
  required: ["code"],
  additionalProperties: false,
} as const;

/**
 * 6 个内置工具的注册表 —— `input_schema` 的**唯一真源**（R3-23 ①；第 6 个 `spawn_agent` 为 V0.3.1 新增）。
 *
 * 顺序取 R3-23 列举的次序（`filesystem` / `git` / `http` / `shell` / `code_exec`）。
 * 每个 `input_schema` 都是**手写字面量**：不 spread、不排序、不裁剪 ——
 * 「与注册表逐字节一致」这条验收才有意义（一旦运行时重排，断言就只能比深等价）。
 */
export const BUILTIN_TOOLS: readonly BuiltinToolSpec[] = [
  {
    name: "filesystem",
    displayName: "文件系统",
    description: "在 Workspace 目录内 read / list / write / delete 文件",
    category: "system",
    permissionAction: "READ",
    requiresSandbox: false,
    inputSchema: {
      type: "object",
      properties: {
        action: { type: "string", enum: ["read", "list", "write", "delete"] },
        path: { type: "string", minLength: 1 },
        content: { type: "string" },
        encoding: { type: "string" },
      },
      required: ["action", "path"],
      additionalProperties: false,
    },
  },
  {
    name: "git",
    displayName: "Git",
    description: "在沙箱内执行 git clone / status / diff / commit / branch",
    category: "vcs",
    permissionAction: "WRITE",
    requiresSandbox: true,
    inputSchema: {
      type: "object",
      properties: {
        action: { type: "string", enum: ["clone", "status", "diff", "commit", "branch"] },
        args: { type: "array", items: { type: "string" } },
        timeout_ms: { type: "integer", minimum: 1 },
      },
      required: ["action"],
      additionalProperties: false,
    },
  },
  {
    name: "http",
    displayName: "HTTP",
    description: "发起 HTTP 请求（出网默认拒绝，需显式白名单）",
    category: "network",
    permissionAction: "EXECUTE",
    requiresSandbox: false,
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", minLength: 1 },
        method: { type: "string" },
        headers: { type: "object" },
        body: { type: "string" },
        timeout_ms: { type: "integer", minimum: 1 },
      },
      required: ["url"],
      additionalProperties: false,
    },
  },
  {
    name: "shell",
    displayName: "Shell",
    description: "在沙箱内执行 shell 命令（禁 Host 直执行）",
    category: "system",
    permissionAction: "EXECUTE",
    requiresSandbox: true,
    inputSchema: {
      type: "object",
      properties: {
        // py 真源这里是 `{"type": ["string", "array"]}`，**没有** minLength —— 保持同形。
        command: { type: ["string", "array"] },
        timeout_ms: { type: "integer", minimum: 1 },
      },
      required: ["command"],
      additionalProperties: false,
    },
  },
  {
    name: "code_exec",
    displayName: "代码执行",
    description: "在沙箱内执行代码片段（runtime 缺省 python，与 py 线 python 工具语义等价）",
    category: "system",
    permissionAction: "EXECUTE",
    requiresSandbox: true,
    inputSchema: CODE_EXEC_INPUT_SCHEMA,
  },
  {
    // V0.3.1 · G031-SPK 新增的第 6 个内置工具。schema 形状 = 裁定书 R8 ① 的签名
    // `spawn_agent(target_agent_id, task, budget_hint?)`；`input_schema` 仍是
    // **手写字面量**（键序即序列化顺序，禁止运行时重排）。
    name: "spawn_agent",
    displayName: "子 Agent 委派",
    description: "派生一个子 agent_run 执行子任务（深度上限缺省 1，超限必拒）",
    category: "agent",
    permissionAction: "EXECUTE",
    requiresSandbox: false,
    inputSchema: {
      type: "object",
      properties: {
        target_agent_id: { type: "string", minLength: 1 },
        task: { type: "string", minLength: 1 },
        budget_hint: { type: "integer", minimum: 1 },
      },
      required: ["target_agent_id", "task"],
      additionalProperties: false,
    },
  },
];

/**
 * 把 `input_schema` 序列化成**确定性字符串**（R3-23 ②「逐字节一致」的比较基准）。
 *
 * 因为注册表是固定字面量，`JSON.stringify` 的键序 = 字面量书写顺序，
 * 两次调用必然逐字节相同；落库再读回后（SQLite 档）也应当相同。
 */
export function serializeBuiltinInputSchema(spec: BuiltinToolSpec): string {
  return JSON.stringify(spec.inputSchema);
}

/**
 * 把整条注册表条目序列化（写进 `tool_version.spec`）。
 *
 * 键序固定：契约面叫 `type` 的那个值在库里叫 `source`，这里用库侧名字 `source`，
 * 避免注册表与表结构两套词。
 */
export function serializeBuiltinToolSpec(spec: BuiltinToolSpec): string {
  return JSON.stringify({
    name: spec.name,
    display_name: spec.displayName,
    description: spec.description,
    category: spec.category,
    source: TOOL_SOURCE_BUILTIN,
    permission_action: spec.permissionAction,
    requires_sandbox: spec.requiresSandbox,
    input_schema: spec.inputSchema,
  });
}

/** `ensureBuiltinTools` 的结果（幂等：第二次 `inserted` 恒为空）。 */
export interface BuiltinToolsSummary {
  /** 本次真正插入的工具名（第二次调用 ⇒ 空数组）。 */
  readonly inserted: readonly string[];
  /** 本次已存在、未动的工具名。 */
  readonly existing: readonly string[];
  /** 注册表条目数（恒 6 = `BUILTIN_TOOLS.length`；**不是**表里的行数 —— 行数异常由 `findDuplicates` 暴露）。 */
  readonly registered: number;
}

/** 契约 `ToolResponse` 的字段（`type` ↔ DB `source` 的映射封在 {@link toToolCatalogEntry}）。 */
export interface ToolCatalogEntry {
  readonly id: string;
  readonly name: string;
  readonly display_name: string;
  readonly description: string;
  readonly category: string;
  readonly input_schema: unknown;
  readonly requires_sandbox: boolean;
  readonly type: string;
}

/**
 * 读「权限动作」的**唯一入口**（借位 `tool_ref` 的读侧封装）。
 *
 * 为什么借位：`tool` 表**没有** `permission_action` 列，而零 DDL 红线不许加列；
 * 同时 `tool_ref` 在 `openapi.v1.frozen.v0019.json` 里出现 **0 次** ⇒
 * 把内部字段塞进去不会污染 API 响应面（team-lead 已核实）。
 *
 * @throws {ScopeError} 缺失或取值非法（宁可红，也不返回一个"猜"出来的动作）。
 */
export function readToolPermissionAction(row: ToolRow): ToolPermissionAction {
  const ref = row.tool_ref as { permission_action?: unknown } | null;
  const action = ref?.permission_action;
  if (action === "READ" || action === "WRITE" || action === "EXECUTE") return action;
  throw new ScopeError(
    `tool ${row.name}：tool_ref.permission_action 缺失或非法（实测 ${JSON.stringify(action)}）—— ` +
      "合法值 READ | WRITE | EXECUTE（该字段借位 tool_ref，见 tool-repo 文件头注）",
  );
}

/**
 * `tool` 行 → 契约 `ToolResponse` 形状（**`source` ↔ `type` 的唯一映射点**）。
 *
 * 只做字段搬运，不做权限/策略判断 —— 那是 T3-12 的事。
 */
export function toToolCatalogEntry(row: ToolRow): ToolCatalogEntry {
  return {
    id: row.id,
    name: row.name,
    display_name: row.display_name,
    description: row.description ?? "",
    category: row.category,
    input_schema: row.input_schema ?? {},
    requires_sandbox: row.requires_sandbox,
    type: row.source,
  };
}

export class ToolRepo extends ScopedRepo<ToolRow> {
  readonly #versionTable: Table;
  readonly #versionColumns: Record<string, AnyColumn>;

  constructor(db: DrizzleDatabase, scope: Scope, dialect: SqlDialect = "pg") {
    super(db, resolveTable(dialect, pgTool, sqliteTool), scope);
    this.#versionTable = resolveTable(dialect, pgToolVersion, sqliteToolVersion);
    // 基类的 `columns` 是 `tool` 的；`tool_version` 要自己取 —— 两表同名列传错会静默错配，
    // 所以只在这里取一次，所有版本查询共用。
    this.#versionColumns = getTableColumns(this.#versionTable) as Record<string, AnyColumn>;
  }

  /** 本租户的工具目录（`tool` 表没有时间列 ⇒ 基类自动跳过排序）。 */
  list(options: ListOptions = {}): Promise<ToolRow[]> {
    return this.findManyWhere(undefined, options);
  }

  /** 按名字取（`(tenant_id, name)` 无唯一索引 ⇒ 可能有多行，见 {@link findDuplicates}）。 */
  findByName(name: string): Promise<ToolRow | null> {
    return this.findOneWhere(eq(this.columns.name, name));
  }

  /**
   * **R3-23 幂等物化**：把注册表按本 scope 的租户写进 `tool` 表。
   *
   * 口径：
   *   * 先按 `(tenant_id, name)` 查（`tenant_id` 谓词由 `ScopedRepo` 自动 and 上），缺失才插；
   *   * 每条同时登记 `tool_version` 的 `v1` 行（`spec` = 注册表条目序列化）；
   *   * 第二次调用 ⇒ `inserted` 为空、**写次数为 0**（测试用 `total_changes()` 锁这一条）。
   *
   * 单写者约束（R3-23 ③）：只在 bootstrap 期调用、进程内串行。
   * 并发多进程首启仍可能插重复（无唯一索引）——{@link findDuplicates} 负责把它暴露成红。
   *
   * @returns 本次插入 / 已存在的名字清单（顺序 == 注册表顺序）。
   */
  async ensureBuiltinTools(): Promise<BuiltinToolsSummary> {
    const inserted: string[] = [];
    const existing: string[] = [];

    for (const spec of BUILTIN_TOOLS) {
      const found = await this.findByName(spec.name);
      if (found !== null) {
        this.#assertTenantBound(found);
        await this.#ensureVersionRow(found, spec);
        existing.push(spec.name);
        continue;
      }

      const created = await this.insertRow({
        id: randomUUID(),
        organization_id: null,
        name: spec.name,
        display_name: spec.displayName,
        description: spec.description,
        category: spec.category,
        source: TOOL_SOURCE_BUILTIN,
        input_schema: spec.inputSchema as never,
        output_schema: null,
        requires_sandbox: spec.requiresSandbox,
        status: TOOL_STATUS_ACTIVE,
        tool_ref: { permission_action: spec.permissionAction } as never,
      } as TenantScopedInsert<ToolRow>);

      this.#assertTenantBound(created);
      await this.#ensureVersionRow(created, spec);
      inserted.push(spec.name);
    }

    return { inserted, existing, registered: BUILTIN_TOOLS.length };
  }

  /** 本租户该工具的版本行（R3-23 ⑤：本版只有 `v1`）。 */
  listVersions(toolId: string): Promise<ToolVersionRow[]> {
    return this.#selectVersions(toolId);
  }

  /**
   * 查询级不变量：本租户内同名工具出现多次 ⇒ 返回全部重复行（R3-23 ④ 的自检口）。
   *
   * 「跨租户同名」是**允许**的（内置工具按租户物化）—— 这里比的是本租户内的重名。
   */
  async findDuplicates(): Promise<ToolRow[]> {
    const rows = await this.list({ limit: 500 });
    const counts = new Map<string, number>();
    for (const row of rows) counts.set(row.name, (counts.get(row.name) ?? 0) + 1);
    return rows.filter((row) => (counts.get(row.name) ?? 0) > 1);
  }

  // -------------------------------------------------------------------------
  // 私有
  // -------------------------------------------------------------------------

  /**
   * `tool.tenant_id` **必须有值且等于本 scope**。
   *
   * 列本身可空（DDL 允许平台级共享工具），但 R3-23 ① 裁定内置工具按租户物化 ⇒
   * 任何 `tenant_id` 为空 / 不等于本 scope 的行都是**脏数据**，宁可当场抛。
   * 这样"必须有 tenant_id"是断言而不是隐式约定。
   */
  #assertTenantBound(row: ToolRow): void {
    if (row.tenant_id === null || row.tenant_id !== this.scope.tenantId) {
      throw new ScopeError(
        `tool ${row.name}：tenant_id 必须等于本 scope（实测 ${String(row.tenant_id)}，` +
          `scope=${this.scope.tenantId}）—— 内置工具按租户物化（R3-23 ①）`,
      );
    }
  }

  /** 该工具的 `v1` 版本行存在则不动，不存在则插入（幂等）。 */
  async #ensureVersionRow(toolRow: ToolRow, spec: BuiltinToolSpec): Promise<void> {
    const existing = await this.#selectVersions(toolRow.id);
    if (existing.some((row) => row.version === BUILTIN_TOOL_VERSION)) return;

    const values: Record<string, unknown> = {
      id: randomUUID(),
      tool_id: toolRow.id,
      version: BUILTIN_TOOL_VERSION,
      spec: JSON.parse(serializeBuiltinToolSpec(spec)) as Record<string, unknown>,
    };
    await (this.db
      .insert(this.#versionTable)
      .values(values)
      .returning() as unknown as PromiseLike<ToolVersionRow[]>);
  }

  /** 取某 `tool_id` 的全部版本行。 */
  async #selectVersions(toolId: string): Promise<ToolVersionRow[]> {
    const rows = await (this.db
      .select()
      .from(this.#versionTable)
      .where(eq(this.#versionColumns.tool_id, toolId)) as unknown as PromiseLike<
      ToolVersionRow[]
    >);
    return rows.slice();
  }
}
