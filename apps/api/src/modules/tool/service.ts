/**
 * T3-12 · 工具目录服务（**1 op**：`GET /api/v1/tools`）。
 *
 * 语义（**py oracle：`wbtime_ai_api/routers/v1/tools.py::list_tools`**）
 * ---------------------------------------------------------------
 * py 返回的是**工具注册表**（`services.tool.list()`），即"本平台有哪些工具"，
 * 与租户无关、与权限无关。TS 侧多一步：R3-23 要求把注册表**物化**进 `tool` 表，
 * 因为 `tool_permission.tool_id` 是 FK —— 权限要引用工具，就必须先有行和稳定的 `id`。
 * 所以本服务的 `list` = 「幂等物化」+「读回」：
 *
 *   1. `ensureBuiltinTools()`：按 `(tenant_id, name)` 查，缺什么补什么；第二次调用
 *      **写次数为 0**（`tool-repo.ts` 的 R3-23 口径，测试用 `total_changes()` 锁这条）。
 *   2. 读回本租户的工具行 ⇒ 映射成契约 `ToolResponse`。
 *
 * 为什么每次 `list` 都 ensure 而不是只在启动时做一次
 * ----------------------------------------------
 *   - 装配是**同步**的，`ensureBuiltinTools` 是异步的 —— 放进 `buildApp` 会把整个
 *     同步装配链改成异步（牵动两条并发波的接口面）。
 *   - 幂等 + 单写者约束（R3-23 ③）本来就允许重复调用；成本是 5 次 `findByName`。
 *   - 新租户第一次 `GET /tools` 就能拿到完整目录，不依赖"有人跑过 bootstrap"。
 *
 * 次序
 * ----
 * `tool` 表没有时间列，基类 `findManyWhere` 会跳过排序 ⇒ SQL 无 `ORDER BY`，
 * PG 下次序不保证。而 py 返回的是**注册表顺序**（`filesystem / git / http / shell /
 * code_exec`）。故本层按 {@link BUILTIN_TOOLS} 的下标重排：内置的在前且固定，
 * 非内置（未来的扩展工具）保持读回顺序排在后面。这样"两次调用次序全等"可断言。
 *
 * 不做的事
 * -------
 * 不过滤 `status`：py 的注册表没有禁用态；`tool` 表的 `status` 由物化写入（恒 `active`）。
 * 若将来要支持禁用，那是另一个 op 的事（契约本版没有）。
 */

import {
  BUILTIN_TOOLS,
  Scope,
  TOOL_SOURCE_BUILTIN,
  ToolRepo,
  type DrizzleDatabase,
  type SqlDialect,
  type ToolRow,
} from "@wbtime/db";

/** 对外工具视图（契约 `ToolResponse`，8 键逐字对齐）。 */
export interface ToolView {
  readonly id: string | null;
  readonly name: string;
  readonly display_name: string;
  readonly description: string;
  readonly category: string;
  readonly type: string;
  readonly requires_sandbox: boolean;
  readonly input_schema: Record<string, unknown>;
}

/** 工具目录的取数上限（契约该 op 无分页参数 ⇒ 取仓内允许的最大值）。 */
export const TOOLS_LIST_LIMIT = 500;

/** 工具目录服务的依赖。 */
export interface ToolServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect?: SqlDialect;
}

/** 工具目录服务（1 op）。 */
export class ToolService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;

  constructor(deps: ToolServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect ?? "pg";
  }

  /**
   * 本租户的工具目录（先幂等物化内置注册表，再读回）。
   *
   * @param tenantId 租户（来自主体）。物化**按租户**进行 —— 每个租户各有一份
   *   `tool` 行（R3-23 的 `(tenant_id, name)` 口径），不是全局共享行。
   */
  async list(tenantId: string): Promise<ToolView[]> {
    const repo = new ToolRepo(this.#db, new Scope(tenantId), this.#dialect);
    await repo.ensureBuiltinTools();
    const rows = await repo.list({ limit: TOOLS_LIST_LIMIT });
    return sortByRegistry(rows).map(toToolView);
  }
}

/** 注册表下标（内置工具的顺序真源；不在注册表里的排后面，保持相对次序）。 */
const REGISTRY_ORDER: ReadonlyMap<string, number> = new Map(
  BUILTIN_TOOLS.map((spec, index) => [spec.name, index] as const)
);

/**
 * 按注册表顺序重排。
 *
 * `sort` 是稳定的（ES2019+）⇒ 非内置项之间的相对次序不变，不会因为这条重排
 * 把"读回来的顺序"打乱。
 */
function sortByRegistry(rows: readonly ToolRow[]): ToolRow[] {
  return [...rows].sort((a, b) => registryIndex(a.name) - registryIndex(b.name));
}

function registryIndex(name: string): number {
  return REGISTRY_ORDER.get(name) ?? Number.MAX_SAFE_INTEGER;
}

/** 行 → 契约视图。 */
function toToolView(row: ToolRow): ToolView {
  return {
    id: row.id ?? null,
    name: row.name,
    display_name: row.display_name ?? "",
    description: row.description ?? "",
    category: row.category ?? "",
    // py 取 `spec.tool_type`（缺省 `"builtin"`）；TS 的等价列是 `source`
    // （`TOOL_SOURCE_BUILTIN === "builtin"`）⇒ 两者同为 `"builtin"`。
    type: row.source ?? TOOL_SOURCE_BUILTIN,
    requires_sandbox: row.requires_sandbox === true,
    // 契约 `input_schema` 是 `object`（非可空）⇒ 列值 null 时回落 `{}`。
    input_schema: (row.input_schema ?? {}) as Record<string, unknown>,
  };
}
