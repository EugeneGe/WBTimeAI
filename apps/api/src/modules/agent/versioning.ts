/**
 * T3-05 · AgentVersion 读写服务（发布 / 版本列表 / 快照视图）。
 *
 * 为什么独立于 {@link ./service.ts} 的 `AgentService`
 * ----------------------------------------------------
 * 「一次发布 = 一个新版本（**不可变快照**）」是一条独立不变量（py
 * `version_repository` 头注原文 + 契约 `GET /agents/{id}/versions` 描述「**不可变快照**」）。
 * 把它单独收在一个文件里，是为了让"本版**没有**任何版本字段级修改入口"这件事
 * **结构性可查**：本模块对 `agent_version` 只有两条路 —— `publishVersion`（经
 * `AgentRepo.publishVersion` 的环状外键三步序插入新行）与只读查询。
 * 没有 update / delete 版本的方法（反例 CE-T5-2 钉死：谁在发布路径上就地改旧版本行，
 * 快照不可变判据必红）。
 *
 * `PublishRequest.tools` 刻意**不承接**：`agent_tool` 绑定归 T3-05 之后的接线
 * （§13.8.7 挂账 #7 —— T3-03 时已登记，本版文件域不含新 db 仓）。py 对 tools
 * 是"发布时按需绑定"；TS 侧收下该字段但**不落库**，登记为遗留（契约字段 vs
 * 仓储能力的缺口，不在服务层臆造绑定语义）。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import {
  AgentRepo,
  Scope,
  type AgentVersionRow,
  type DrizzleDatabase,
  type SqlDialect,
} from "@wbtime/db";

import { authError } from "../auth/errors.js";

/** 对外版本视图（契约 `AgentVersionResponse`，键集合逐字对齐：9 键）。 */
export interface AgentVersionView {
  readonly id: string;
  readonly agent_id: string;
  readonly version: string;
  readonly system_prompt: string;
  readonly model_config: Record<string, unknown>;
  readonly runtime_config: Record<string, unknown>;
  readonly status: string;
  readonly created_by: string;
  readonly created_at: string | null;
}

/** 发布入参（契约 `PublishRequest`；`tools` 见文件头注——收下不落库）。 */
export interface PublishAgentInput {
  readonly version?: string | null;
  readonly system_prompt?: string;
  readonly model_config?: Record<string, unknown>;
  readonly runtime_config?: Record<string, unknown>;
  readonly tools?: readonly { readonly tool_id: string }[];
}

/** 版本服务的依赖（与 `AgentService` 共用同一装配）。 */
export interface VersioningDeps {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
}

/** AgentVersion 服务：发布是唯一写入口，其余只读。 */
export class AgentVersioningService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;

  constructor(deps: VersioningDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect;
  }

  /** 本租户某个 agent 的仓储（每次现建 —— 与 credential 服务同一模式）。 */
  #repo(tenantId: string, workspaceId?: string | null): AgentRepo {
    return new AgentRepo(this.#db, new Scope(tenantId, workspaceId ?? undefined), this.#dialect);
  }

  /**
   * 发布一个新版本（一次发布 = 一个新行；旧版本行**不变**）。
   *
   * @param tenantId 租户（来自主体）。
   * @param agentId 路径参数。
   * @param createdBy 发布者（当前登录用户 id，py 同口径）。
   * @param input 契约 `PublishRequest`。
   * @returns 新发布的版本视图（`status` 恒 `PUBLISHED`）。
   * @throws {HttpException} agent 不可见 ⇒ 404 `NOT_FOUND`（跨租户 / 不存在同形）。
   */
  async publish(
    tenantId: string,
    agentId: string,
    createdBy: string,
    input: PublishAgentInput,
  ): Promise<AgentVersionView> {
    const repo = this.#repo(tenantId);
    const ref = new Scope(tenantId).ref(agentId);
    const row = await repo.publishVersion(ref, {
      id: randomUUID(),
      createdBy,
      ...(input.version === undefined || input.version === null
        ? {}
        : { version: input.version }),
      systemPrompt: input.system_prompt ?? "",
      modelConfig: input.model_config ?? {},
      runtimeConfig: input.runtime_config ?? {},
    });
    return toVersionView(row);
  }

  /**
   * 列出某 agent 的全部版本（**不可变快照**；created_at 升序 + id 兜底）。
   *
   * @throws {HttpException} agent 不可见 ⇒ 404（repo 对不可见父一律抛 `ScopeError`）。
   */
  async listVersions(tenantId: string, agentId: string): Promise<AgentVersionView[]> {
    const repo = this.#repo(tenantId);
    try {
      const rows = await repo.listVersions(new Scope(tenantId).ref(agentId));
      return rows.map(toVersionView);
    } catch (error) {
      throw mapScopeError(error, agentId);
    }
  }

  /** 按版本 id 取（agent 必须可见；版本不存在或归属不符 ⇒ 404 —— py `load_version` 同形）。 */
  async findVersion(tenantId: string, agentId: string, versionId: string): Promise<AgentVersionView> {
    const repo = this.#repo(tenantId);
    try {
      const row = await repo.findVersion(new Scope(tenantId).ref(agentId), versionId);
      if (row === null) {
        throw authError(ERROR_CODES.NOT_FOUND, "AgentVersion 不存在或归属不符", {
          agent_id: agentId,
          version_id: versionId,
        });
      }
      return toVersionView(row);
    } catch (error) {
      throw mapScopeError(error, agentId);
    }
  }
}

/**
 * 行 → 契约视图（键集合逐字对齐 `AgentVersionResponse`：9 键）。
 *
 * `created_at` 经 `toIsoOrNull` 规整 —— SQLite 档是 `YYYY-MM-DD HH:MM:SS` 文本，
 * 契约示例是 ISO-8601，同一接口不能因部署档不同给出两种时间形状（T2-07 既有口径）。
 */
export function toVersionView(row: AgentVersionRow): AgentVersionView {
  return {
    id: row.id,
    agent_id: row.agent_id,
    version: row.version,
    system_prompt: row.system_prompt,
    model_config: (row.model_config ?? {}) as Record<string, unknown>,
    runtime_config: (row.runtime_config ?? {}) as Record<string, unknown>,
    status: row.status,
    created_by: row.created_by,
    created_at: toIsoOrNull(row.created_at),
  };
}

/**
 * 时间 → 契约要求的 `string | null`（PG 档 `Date` / SQLite 档秒粒度文本 → ISO-8601）。
 * 与 `credential/service.ts` 的 `toIsoOrNull` 同型 —— 各服务局部重复是既有取舍
 * （T2-07：基类闭版不许动，公共 util 未立项，不为此扩公共面）。
 */
export function toIsoOrNull(value: unknown): string | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.toISOString();
  if (typeof value !== "string" || value.trim() === "") return null;
  const text = value.trim();
  const sqliteShape =
    /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$/.exec(text);
  if (sqliteShape) {
    const [, y, mo, d, h, mi, s, ms] = sqliteShape;
    return new Date(Date.UTC(+y, +mo - 1, +d, +h, +mi, +s, ms ? +ms.padEnd(3, "0") : 0)).toISOString();
  }
  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

/**
 * 把仓储层的 `ScopeError`（父不可见）翻成 404 `NOT_FOUND`。
 *
 * ⚠️ 只翻"父不可见"这一种：service 层对 ref 的铸造恒用本租户 scope，
 * `assertOwnRef` 的"铸造来源不同租户"分支在此不可达；跨租户行在
 * `findById`（带租户谓词）处表现为查不到 ⇒ 404（I-1 口径：跨租户 404，不是 403）。
 */
export function mapScopeError(error: unknown, agentId: string): Error {
  if (error instanceof Error && error.name === "ScopeError") {
    return authError(ERROR_CODES.NOT_FOUND, "Agent 不存在", { agent_id: agentId });
  }
  return error as Error;
}
