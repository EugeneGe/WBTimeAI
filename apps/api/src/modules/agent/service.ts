/**
 * T3-05 · Agent 服务（7 op 的 6 个主体 + run 前置校验；执行归 T3-08）。
 *
 * 职责与**刻意不做**（逐条对任务卡验收 ①–④）：
 *   - CRUD 三 op + 列表分页（契约 `?page=&page_size=`）；
 *   - PUT 的 `status` 键**转接 `AgentRepo.transition()`**（矩阵 + CAS —— T3-03
 *     §15.5 偏差 #2 的裁决：服务层不绕过状态机；非法迁移 / 词表外值 ⇒ 422，
 *     `data.reason_code='agent_status_transition_invalid'`，**不新增契约错误码**）；
 *   - `publish` / `versions` 委托 {@link AgentVersioningService}（本文件不碰版本行）；
 *   - `run` 只做**入口与前置校验**（R3-13 harness 路由 + R3-06 run_mode + 存在性），
 *     **不创建 run、不执行** —— `agent_run` 计数在本任务恒为装配前值；
 *     响应体是"入口回执"（非 `RunResponse`），T3-08 落执行后替换，登记为偏差。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import {
  AgentRepo,
  ConversationRepo,
  Scope,
  type AgentRow,
  type DrizzleDatabase,
  type SqlDialect,
} from "@wbtime/db";

import { authError } from "../auth/errors.js";
import {
  assertInlineRunMode,
  routeHarness,
  writeHarnessAudit,
} from "./policy.js";
import {
  AgentVersioningService,
  toIsoOrNull,
} from "./versioning.js";

/** 对外 agent 视图（契约 `AgentResponse`，键集合逐字对齐：10 键）。 */
export interface AgentView {
  readonly id: string;
  readonly tenant_id: string | null;
  readonly name: string;
  readonly workspace_id: string | null;
  readonly description: string | null;
  readonly type: string;
  readonly status: string;
  readonly current_version_id: string | null;
  readonly created_by: string;
  readonly created_at: string | null;
  readonly updated_at: string | null;
}

/** 创建入参（契约 `CreateAgentRequest`：name 必填，type 缺省 PRIMARY）。 */
export interface CreateAgentInput {
  readonly name: string;
  readonly description?: string | null;
  readonly type?: string;
  readonly workspace_id?: string | null;
}

/** 更新入参（契约 `UpdateAgentRequest`：缺省字段不变；三键均可空，`status` 走状态机）。 */
export interface UpdateAgentInput {
  readonly name?: string | null;
  readonly description?: string | null;
  readonly status?: string | null;
}

/** run 入口回执（**非** `RunResponse` —— run 未创建，见文件头注；T3-08 替换）。 */
export interface RunEntryReceipt {
  readonly agent_id: string;
  readonly agent_version_id: string;
  readonly conversation_id: string | null;
  readonly harness: string;
  readonly run_mode: "INLINE";
  /** 恒 `"deferred"`：执行归 T3-08（RunCoordinator + RunEventWriter）。 */
  readonly execution: "deferred";
}

/** `GET /agents` 的分页口径（契约：`page` 缺省 1；`page_size` 缺省 20、上限 100）。 */
export const AGENTS_PAGE_SIZE_DEFAULT = 20;
export const AGENTS_PAGE_SIZE_MAX = 100;

/** agent 服务的依赖（装配一次，见 `app.ts` 的 `buildIdentityStack`）。 */
export interface AgentServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
  /** 时钟（测试注入；缺省真实时钟）。 */
  readonly now?: () => Date;
}

export class AgentService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #now: () => Date;
  readonly #versioning: AgentVersioningService;

  constructor(deps: AgentServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect;
    this.#now = deps.now ?? (() => new Date());
    this.#versioning = new AgentVersioningService({ db: deps.db, dialect: deps.dialect });
  }

  /** 版本族入口（路由的 publish / versions 直接透传）。 */
  get versioning(): AgentVersioningService {
    return this.#versioning;
  }

  /** 本租户的 agent 仓储（每次现建 —— 与 credential 服务同一模式）。 */
  #repo(tenantId: string, workspaceId?: string | null): AgentRepo {
    return new AgentRepo(this.#db, new Scope(tenantId, workspaceId ?? undefined), this.#dialect);
  }

  /**
   * 列出本租户 agent（`GET /agents`：`page` / `page_size` 分页；排序 created_at 升序）。
   *
   * @throws {HttpException} `page` / `page_size` 非法 ⇒ 422（repo 抛 `ScopeError`，
   *   这里统一翻 `VALIDATION_ERROR` —— 不静默夹取）。
   */
  async list(
    tenantId: string,
    page: number | undefined,
    pageSize: number | undefined,
  ): Promise<AgentView[]> {
    try {
      const rows = await this.#repo(tenantId).list({
        ...(page === undefined ? {} : { page }),
        ...(pageSize === undefined ? {} : { pageSize }),
      });
      return rows.map(toAgentView);
    } catch (error) {
      throw this.#mapValidation(error);
    }
  }

  /**
   * 创建 agent（`POST /agents`：`DRAFT`，无当前版本 —— 契约描述原文）。
   *
   * @param createdBy 当前登录用户 id（列 NOT NULL；py 同口径取 `user.id`）。
   * @throws {HttpException} 非法 type ⇒ 422；workspace 不存在 ⇒ FK 500（py 同病，登记遗留）。
   */
  async create(
    tenantId: string,
    createdBy: string,
    input: CreateAgentInput,
  ): Promise<AgentView> {
    const workspaceId = input.workspace_id ?? null;
    try {
      const row = await this.#repo(tenantId, workspaceId).create({
        id: randomUUID(),
        name: input.name,
        createdBy,
        ...(input.type === undefined ? {} : { type: input.type }),
        ...(input.description === undefined ? {} : { description: input.description }),
      });
      return toAgentView(row);
    } catch (error) {
      // workspace_id 是入参而不是 scope 语义：这里给 create 单独带了 workspace scope
      //（insertRow 据此注入 workspace_id），于是 ScopeError 不可能是"父不可见"，
      // 只可能是值域校验（type）—— 翻 422。
      throw this.#mapValidation(error);
    }
  }

  /**
   * 取 agent（跨租户 / 不存在 ⇒ 404 `NOT_FOUND` —— 契约描述原文，I-1 口径）。
   */
  async get(tenantId: string, agentId: string): Promise<AgentView> {
    const row = await this.#repo(tenantId).findById(new Scope(tenantId).ref(agentId));
    if (row === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "Agent 不存在", { agent_id: agentId });
    }
    return toAgentView(row);
  }

  /**
   * 更新 agent（`PUT /agents/{id}`：缺省字段不变）。
   *
   * `status` 键**只**走 `transition()`（矩阵 + CAS）：
   *   - 词表外值 / 矩阵外迁移（含 CAS 未命中）⇒ 422 + `agent_status_transition_invalid`；
   *   - 目标 `DRAFT`（矩阵无指向它的边）⇒ 同上 422；
   *   - agent 不存在 ⇒ 404（先于一切状态操作）。
   *
   * `name` / `description` 走 `updateMetadata`（status 键被 repo 层封死，后门不存在）。
   * 先迁状态、后改元数据：状态迁移失败时元数据**一字未动**（请求级 all-or-nothing
   * 的次序保证；两写非同事务的残余窗口登记为遗留）。
   */
  async update(
    tenantId: string,
    agentId: string,
    input: UpdateAgentInput,
  ): Promise<AgentView> {
    const repo = this.#repo(tenantId);
    const ref = new Scope(tenantId).ref(agentId);
    const current = await repo.findById(ref);
    if (current === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "Agent 不存在", { agent_id: agentId });
    }

    if (input.status !== undefined) {
      // 词表外值（含显式 null）也走 transition：repo 的词表校验会抛 ScopeError，
      // 统一翻 422 —— 服务层不复制第二份词表（单一真相源）。
      let moved: AgentRow | null = null;
      try {
        moved = await repo.transition(ref, input.status as string);
      } catch (error) {
        // 词表外值 / 目标无来源：repo 抛 ScopeError ⇒ 统一 422（不新增契约错误码）。
        if (error instanceof Error && error.name === "ScopeError") {
          throw this.#transitionInvalid(current.status, input.status);
        }
        throw error;
      }
      if (moved === null) {
        // CAS 未命中：当前状态不在目标的合法来源集合里 —— 非法迁移。
        throw this.#transitionInvalid(current.status, input.status);
      }
    }

    const patch: { name?: string | null; description?: string | null } = {};
    if (input.name !== undefined) patch.name = input.name;
    if (input.description !== undefined) patch.description = input.description;
    if (Object.keys(patch).length > 0) {
      // 显式 `name: null` 与 py 同病：会撞 `name` 的 NOT NULL 列 ⇒ 500（登记为
      // 契约可空 vs 列约束的既有不一致，不在服务层臆造"静默忽略"）。
      await repo.updateMetadata(ref, patch as { name?: string; description?: string | null });
    }

    const updated = await repo.findById(ref);
    return toAgentView(updated ?? current);
  }

  /** 发布（委托 {@link AgentVersioningService.publish}；agent 不可见 ⇒ 404）。 */
  async publish(
    tenantId: string,
    agentId: string,
    createdBy: string,
    input: Parameters<AgentVersioningService["publish"]>[3],
  ) {
    // 先验可见性（404 语义由 get 给出），再进版本服务。
    await this.get(tenantId, agentId);
    return this.#versioning.publish(tenantId, agentId, createdBy, input);
  }

  /** 版本列表（委托；agent 不可见 ⇒ 404）。 */
  async listVersions(tenantId: string, agentId: string) {
    await this.get(tenantId, agentId);
    return this.#versioning.listVersions(tenantId, agentId);
  }

  /**
   * 运行入口（`POST /agents/{id}/run`）—— **只做入口与前置校验，不创建 run、不执行**。
   *
   * 校验序（先 404 后 422，与既有族一致）：
   *   1. agent 不可见 ⇒ 404；
   *   2. `run_mode` ≠ INLINE ⇒ 422 `run_mode_unsupported`（R3-06）；
   *   3. agent 无当前版本 ⇒ 422（py `load_version` 同文案："Agent 无当前版本且未显式
   *      指定 version_id"；`RunRequest` 无版本字段，本版不支持请求级指定）；
   *   4. 当前版本行不存在 / 归属不符 ⇒ 404（py `load_version` NOT_FOUND 同形）；
   *   5. `runtime_config.harness` 不在白名单 ⇒ 422 `harness_unsupported`（R3-13，
   *      **不静默回落**；`agent_run` 计数不变 —— 本方法压根不写 run）；
   *   6. `conversation_id` 给了但不可见 ⇒ 404（续聊自既有会话，I-1 口径）；
   *      未给 ⇒ **不创建**（会话创建是 run 装配的一部分，归 T3-08）；
   *   7. `message` 缺失 / 空串 ⇒ 422（py RunRequest.message 是必填；契约 OpenAPI 的
   *      `required` 为空是生成口径的既有不一致，登记为偏差）。
   *
   * 全部通过 ⇒ 落一行 `agent.harness_routed` 审计（R3-13 ⑤，`run_id` 恒 null ——
   * T3-08 接线补齐）并返回入口回执。
   */
  async runEntry(
    tenantId: string,
    agentId: string,
    userId: string,
    requestId: string,
    input: {
      readonly message?: string;
      readonly conversation_id?: string | null;
      readonly workspace_id?: string | null;
      readonly run_mode?: string;
    },
  ): Promise<RunEntryReceipt> {
    const agent = await this.get(tenantId, agentId);

    const runMode = input.run_mode ?? "INLINE";
    assertInlineRunMode(runMode);

    if (typeof input.message !== "string" || input.message.trim() === "") {
      throw authError(ERROR_CODES.VALIDATION_ERROR, "message 必填（且不得为空串）", {
        field: "message",
      });
    }

    if (agent.current_version_id === null) {
      throw authError(
        ERROR_CODES.VALIDATION_ERROR,
        "Agent 无当前版本且未显式指定 version_id",
        { agent_id: agentId },
      );
    }
    const version = await this.#versioning.findVersion(
      tenantId,
      agentId,
      agent.current_version_id,
    );

    const routed = routeHarness(version.runtime_config);

    const conversationId = input.conversation_id ?? null;
    if (conversationId !== null) {
      const conversations = new ConversationRepo(this.#db, new Scope(tenantId), this.#dialect);
      const conversation = await conversations.findById(new Scope(tenantId).ref(conversationId));
      if (conversation === null) {
        throw authError(ERROR_CODES.NOT_FOUND, "会话不存在", {
          conversation_id: conversationId,
        });
      }
    }

    await writeHarnessAudit({
      db: this.#db,
      dialect: this.#dialect,
      tenantId,
      userId,
      agentId,
      runId: null,
      routed,
      requestId,
      now: this.#now(),
    });

    return {
      agent_id: agentId,
      agent_version_id: version.id,
      conversation_id: conversationId,
      harness: routed.harness,
      run_mode: "INLINE",
      execution: "deferred",
    };
  }

  /** 非法迁移的 422（复用 `VALIDATION_ERROR` 壳 + 内部 reason_code，不新增契约错误码）。 */
  #transitionInvalid(from: string, to: string | null): Error {
    return authError(
      ERROR_CODES.VALIDATION_ERROR,
      `非法 agent 状态迁移：${from} → ${JSON.stringify(to)}（矩阵外或词表外）`,
      { reason_code: "agent_status_transition_invalid", from, to },
    );
  }

  /** repo 的 `ScopeError`（分页 / 值域校验）→ 422 `VALIDATION_ERROR`。 */
  #mapValidation(error: unknown): Error {
    if (error instanceof Error && error.name === "ScopeError") {
      return authError(ERROR_CODES.VALIDATION_ERROR, error.message);
    }
    return error as Error;
  }
}

/** 行 → 契约视图（键集合逐字对齐 `AgentResponse`：10 键）。 */
export function toAgentView(row: AgentRow): AgentView {
  return {
    id: row.id,
    tenant_id: row.tenant_id ?? null,
    name: row.name,
    workspace_id: row.workspace_id ?? null,
    description: row.description ?? null,
    type: row.type,
    status: row.status,
    current_version_id: row.current_version_id ?? null,
    created_by: row.created_by,
    created_at: toIsoOrNull(row.created_at),
    updated_at: toIsoOrNull(row.updated_at),
  };
}
