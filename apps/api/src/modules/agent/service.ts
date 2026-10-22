/**
 * T3-05 · Agent 服务（7 op 的 6 个主体 + run 入口）。
 *
 * 职责与**刻意不做**（逐条对任务卡验收 ①–④）：
 *   - CRUD 三 op + 列表分页（契约 `?page=&page_size=`）；
 *   - PUT 的 `status` 键**转接 `AgentRepo.transition()`**（矩阵 + CAS —— T3-03
 *     §15.5 偏差 #2 的裁决：服务层不绕过状态机；非法迁移 / 词表外值 ⇒ 422，
 *     `data.reason_code='agent_status_transition_invalid'`，**不新增契约错误码**）；
 *   - `publish` / `versions` 委托 {@link AgentVersioningService}（本文件不碰版本行）；
 *   - `run` 做**入口与前置校验**（R3-13 harness 路由 + R3-06 run_mode + 存在性）
 *     **并把执行交给 {@link RunDriver}**（T3-14 起；此前是 `execution:"deferred"` 的
 *     入口回执 —— 那条偏差已在 T3-14 收口，见 `run/` 的 driver 头注）。
 *
 * run 入口的响应体（T3-14 变更）
 * ---------------------------
 *   改为 `RunResponse`（21 键，与 `GET /runs/{id}` **同一形态**）。理由：run 现在真的
 *   被创建了，"入口回执"这个中间形态已无存在理由；客户端拿到 `id` 后即可
 *   `GET /runs/{id}/events` 收帧。契约该 op 的 `200` schema 是空对象（`{}`），
 *   故形态变更**不动冻结面**（`compare_openapi` 零变化，由 `gate:openapi` 断言）。
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
import { RunDriver } from "../run/driver.js";
import { toRunView, type RunView } from "../run/run-service.js";
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

/**
 * run 入口的旧回执形态（**已删除执行语义**）。
 *
 * T3-05 时期它是 `{agent_id, agent_version_id, conversation_id, harness, run_mode,
 * execution:"deferred"}` —— run 未创建。T3-14 起入口返回 `RunResponse`（见文件头注），
 * 本类型仅作为**历史口径的说明**保留文档价值，不再有代码引用（`grep` 可为证；
 * 若日后有人想"顺手恢复回执"，`routes-agents.test.mjs` 的 D 组断言会立刻红）。
 *
 * @deprecated 用 `RunView`（`run/run-service.ts`）。
 */
export type RunEntryReceiptDeprecated = never;

/** `GET /agents` 的分页口径（契约：`page` 缺省 1；`page_size` 缺省 20、上限 100）。 */
export const AGENTS_PAGE_SIZE_DEFAULT = 20;
export const AGENTS_PAGE_SIZE_MAX = 100;

/** agent 服务的依赖（装配一次，见 `app.ts` 的 `buildIdentityStack`）。 */
export interface AgentServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
  /** 时钟（测试注入；缺省真实时钟）。 */
  readonly now?: () => Date;
  /**
   * run 执行器（T3-14 起；`runEntry` 的前置校验通过后把执行交给它）。
   *
   * 缺省（`undefined`）⇒ `POST /agents/{id}/run` **fail loud**（`CONFIGURATION_ERROR`），
   * 不静默降级成"只回执不执行"—— 那正是 T3-05 遗留的那条假行为。
   */
  readonly driver?: RunDriver;
}

export class AgentService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;
  readonly #now: () => Date;
  readonly #versioning: AgentVersioningService;
  readonly #driver: RunDriver | undefined;

  constructor(deps: AgentServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect;
    this.#now = deps.now ?? (() => new Date());
    this.#versioning = new AgentVersioningService({ db: deps.db, dialect: deps.dialect });
    this.#driver = deps.driver;
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
 * 运行入口（`POST /agents/{id}/run`）—— 前置校验 → **S1 安全闸** → 真建 run → 异步驱动。
 *
 * 校验序（先 404 后 422，与既有族一致）：
 *   1. agent 不可见 ⇒ 404；
 *   2. `run_mode` ≠ INLINE ⇒ 422 `run_mode_unsupported`（R3-06）；
 *   3. `message` 缺失 / 空串 ⇒ 422（py `RunRequest.message` 必填；契约 OpenAPI 的
 *      `required` 为空是生成口径的既有不一致，登记为偏差）；
 *   4. agent 无当前版本 ⇒ 422（py `load_version` 同文案）；
 *   5. 当前版本行不存在 / 归属不符 ⇒ 404（py `load_version` NOT_FOUND 同形）；
 *   6. `runtime_config.harness` 不在白名单 ⇒ 422 `harness_unsupported`（R3-13，
 *      **不静默回落**）；
 *   7. `conversation_id` 给了但不可见 ⇒ 404（续聊自既有会话，I-1 口径）；
 *   8. **S1 `input` 安全闸**（R3-17 第 1 挂点；DENY ⇒ 422 且 **run 不创建** ——
 *      这是"挂点在 run 创建前"的唯一可断言形态：`agent_run` 行数为 0）；
 *   9. 建会话（未给时）/ 落用户消息 / 建 run / 后台驱动（`RunDriver.start`）。
 *
 * 回执 = `RunResponse`（21 键，与 `GET /runs/{id}` 同形 —— 见文件头注）。
 *
 * 审计：`agent.harness_routed` 在 run 创建**之后**落（`run_id` 不再是 null ——
 * T3-05 遗留的接线项，R3-13 ⑤ 的原意）。
 *
 * @throws {HttpException} 见上表 + `CONFIGURATION_ERROR`（未装配 run 驱动 / 模型网关）。
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
  ): Promise<RunView> {
    if (this.#driver === undefined) {
      throw authError(
        ERROR_CODES.CONFIGURATION_ERROR,
        "未装配 run 驱动：POST /agents/{id}/run 不可用（未配置 ≠ 降级）",
        { reason_code: "run_driver_not_configured" },
      );
    }
    const driver = this.#driver;
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

    // ---- S1（run 创建之前；DENY ⇒ 422 且不建 run）-------------------------
    const preflight = await driver.preflight({
      message: input.message,
      requestId,
      conversationId,
    });
    const outbound =
      preflight !== null && preflight.decision === "REDACT" && preflight.redactedContent !== undefined
        ? preflight.redactedContent
        : input.message;

    const started = await driver.start({
      tenantId,
      userId,
      agentId,
      agentVersionId: version.id,
      systemPrompt: version.system_prompt,
      modelConfig: version.model_config,
      runtimeConfig: version.runtime_config,
      conversationId,
      workspaceId: input.workspace_id ?? null,
      agentWorkspaceId: agent.workspace_id,
      message: outbound,
      requestId,
    });

    await writeHarnessAudit({
      db: this.#db,
      dialect: this.#dialect,
      tenantId,
      userId,
      agentId,
      runId: started.run.id,
      routed,
      requestId,
      now: this.#now(),
    });

    return toRunView(started.run);
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
