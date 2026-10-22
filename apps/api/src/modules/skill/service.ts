/**
 * T3-06 · Skill 服务（7 op 的全部主体 + `resolveSkill` 纯查询）。
 *
 * 7 op 与错误语义（**py oracle：`wbtime_ai_api/routers/v1/skills.py` 逐条对齐**）：
 *   | op | 成功码 | 冲突 / 不可见 |
 *   |---|---|---|
 *   | list   | 200 数组 | ——（跨租户天然不可见：scope 谓词） |
 *   | create | 201 | 重名 ⇒ **409** `CONFLICT`「Skill 名已存在」（py 同文案） |
 *   | get    | 200 | 跨租户 / 不存在 ⇒ **404**（I-1 口径，不是 403） |
 *   | update | 200 | 不可见 ⇒ 404；`status` 词表外 ⇒ 422（repo 校验，见偏差 #3） |
 *   | publish| 200 | 无 DRAFT 版本 ⇒ **409**「无可发布的 Skill 版本」（py 同文案） |
 *   | versions POST | 201 | 版本号重复 ⇒ **409**「Skill 版本已存在」（uq 查重先例） |
 *   | versions GET  | 200 | 不可见 ⇒ 404 |
 *
 * 刻意不做：
 *   - **Skill 执行**（范围红线：Skill 是提示词/资源包，非工具）；
 *   - **`skill.resolved` 事件**：本任务只提供 {@link SkillService.resolveSkill} 纯查询
 *     （验收 ④：事件由 T3-08 的 writer 承载）—— 本方法**零写**（连审计都不写），
 *     测试钉住"调用前后各表计数不变"；
 *   - **清单解析不在 7 op 内**：契约 `CreateSkillVersionRequest.manifest` 是自由对象
 *     （已解析的 dict，py 同口径），`skill.yaml` 的解析/装载走 {@link ./manifest} /
 *     {@link ./loader}，由 `skill-manifest.test.mjs` 直接证明（422 口径）。
 */

import { randomUUID } from "node:crypto";

import { ERROR_CODES } from "@wbtime/core";
import {
  Scope,
  SkillRepo,
  type DrizzleDatabase,
  type SkillRow,
  type SkillVersionRow,
  type SqlDialect,
} from "@wbtime/db";

import { authError } from "../auth/errors.js";
import { toIsoOrNull } from "../agent/versioning.js";

/** 对外 skill 视图（契约 `SkillResponse`，键集合逐字对齐：**11 键**，无 updated_at）。 */
export interface SkillView {
  readonly id: string;
  readonly tenant_id: string | null;
  readonly name: string;
  readonly display_name: string;
  readonly description: string | null;
  readonly category: string;
  readonly status: string;
  readonly current_version_id: string | null;
  /** 当前生效版本号（py `_to_skill_response` 恒不传 ⇒ 恒 `null`，同形登记）。 */
  readonly current_version: null;
  readonly created_by: string;
  readonly created_at: string | null;
}

/** 对外版本视图（契约 `SkillVersionResponse`，键集合逐字对齐：**8 键**）。 */
export interface SkillVersionView {
  readonly id: string;
  readonly skill_id: string;
  readonly version: string;
  readonly instructions: string;
  readonly manifest: Record<string, unknown>;
  readonly status: string;
  readonly created_by: string;
  readonly created_at: string | null;
}

/** `resolveSkill` 的产物（skill 视图 + 当前生效版本视图）。 */
export interface ResolvedSkill {
  readonly skill: SkillView;
  readonly version: SkillVersionView;
}

/** 创建入参（契约 `CreateSkillRequest`：`name` 必填，其余有缺省）。 */
export interface CreateSkillInput {
  readonly name: string;
  readonly display_name?: string;
  readonly description?: string | null;
  readonly category?: string;
}

/** 更新入参（契约 `UpdateSkillRequest`：四键全可空；**显式 null = 不变**，py `is not None` 同口径）。 */
export interface UpdateSkillInput {
  readonly display_name?: string | null;
  readonly description?: string | null;
  readonly category?: string | null;
  readonly status?: string | null;
}

/** 创建版本入参（契约 `CreateSkillVersionRequest`：`version` 必填，`manifest` 自由对象）。 */
export interface CreateSkillVersionInput {
  readonly version: string;
  readonly instructions?: string;
  readonly manifest?: Record<string, unknown>;
}

/** skill 服务的依赖（装配一次，见 `app.ts` 的 `buildIdentityStack`）。 */
export interface SkillServiceDeps {
  readonly db: DrizzleDatabase;
  readonly dialect: SqlDialect;
}

export class SkillService {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;

  constructor(deps: SkillServiceDeps) {
    this.#db = deps.db;
    this.#dialect = deps.dialect;
  }

  /** 本租户的 skill 仓储（每次现建 —— 与 credential / agent 服务同一模式）。 */
  #repo(tenantId: string): SkillRepo {
    return new SkillRepo(this.#db, new Scope(tenantId), this.#dialect);
  }

  /**
   * 列出本租户 skill（`GET /skills`；py `list_by_tenant` 无分页参数，契约同）。
   *
   * @throws {HttpException} repo 值域校验 ⇒ 422（分页参数契约里没有，正常流不触发）。
   */
  async list(tenantId: string): Promise<SkillView[]> {
    try {
      const rows = await this.#repo(tenantId).list();
      return rows.map(toSkillView);
    } catch (error) {
      throw this.#mapValidation(error);
    }
  }

  /**
   * 创建 skill（`POST /skills`：`status = DRAFT`，无当前版本 —— 契约描述原文）。
   *
   * 重名**先查后插**（py `get_by_name` 同序）：`uq_skill_tenant_name` 在库，但把
   * 驱动层的唯一约束报错抛给调用方不可读 —— 先查后插给出 409 `CONFLICT`。
   *
   * `display_name` 缺省回落 `name`（py `payload.display_name or payload.name` 同口径，
   * **不是**契约字面的 `""` —— py 实测优先，登记偏差 #4）。
   *
   * @param createdBy 当前登录用户 id（列 NOT NULL ⇒ 必填；py 取 `user.id` 同口径）。
   * @throws {HttpException} 重名 ⇒ 409；`name` 非法由 schema 层 422 挡在路由前。
   */
  async create(tenantId: string, createdBy: string, input: CreateSkillInput): Promise<SkillView> {
    const repo = this.#repo(tenantId);
    const existing = await repo.findByName(input.name);
    if (existing !== null) {
      throw authError(ERROR_CODES.CONFLICT, "Skill 名已存在", { name: input.name });
    }
    const row = await repo.create({
      id: randomUUID(),
      name: input.name,
      createdBy,
      displayName: input.display_name === undefined || input.display_name === ""
        ? input.name
        : input.display_name,
      description: input.description ?? null,
      category: input.category ?? "",
    });
    return toSkillView(row);
  }

  /** 取 skill（跨租户 / 不存在 ⇒ 404 `NOT_FOUND`「Skill 不存在」—— py 同文案，I-1 口径）。 */
  async get(tenantId: string, skillId: string): Promise<SkillView> {
    const row = await this.#repo(tenantId).findById(new Scope(tenantId).ref(skillId));
    if (row === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "Skill 不存在", { skill_id: skillId });
    }
    return toSkillView(row);
  }

  /**
   * 更新元数据（`PUT /skills/{id}`：仅提供需变更字段）。
   *
   * py 语义逐键对齐：`if payload.x is not None` ⇒ **显式 `null` = 不变**（不是清空）。
   * `status` 键走 `updateMetadata`，词表外值被 repo 的值域校验挡下（ScopeError ⇒ 422，
   * 偏差 #3：py 侧无词表校验，TS 侧更严）。
   *
   * @throws {HttpException} 不可见 ⇒ 404；`status` 词表外 ⇒ 422。
   */
  async update(tenantId: string, skillId: string, input: UpdateSkillInput): Promise<SkillView> {
    const repo = this.#repo(tenantId);
    const ref = new Scope(tenantId).ref(skillId);
    const current = await repo.findById(ref);
    if (current === null) {
      throw authError(ERROR_CODES.NOT_FOUND, "Skill 不存在", { skill_id: skillId });
    }

    // py `is not None` 逐键转写：undefined（未提供）与 null（显式空）都不进 patch。
    const patch: {
      display_name?: string;
      description?: string | null;
      category?: string;
      status?: string;
    } = {};
    if (input.display_name !== undefined && input.display_name !== null) {
      patch.display_name = input.display_name;
    }
    if (input.description !== undefined && input.description !== null) {
      patch.description = input.description;
    }
    if (input.category !== undefined && input.category !== null) {
      patch.category = input.category;
    }
    if (input.status !== undefined && input.status !== null) {
      patch.status = input.status;
    }
    if (Object.keys(patch).length > 0) {
      try {
        await repo.updateMetadata(ref, patch);
      } catch (error) {
        throw this.#mapValidation(error);
      }
    }

    const updated = await repo.findById(ref);
    return toSkillView(updated ?? current);
  }

  /**
   * 发布**最新** DRAFT 版本（`POST /skills/{id}/publish`：发布即冻结 + 指针回写）。
   *
   * @returns 被发布的版本视图（`status` 恒 `PUBLISHED`）。
   * @throws {HttpException} 不可见 ⇒ 404（先于一切）；无 DRAFT 版本 ⇒ 409 `CONFLICT`
   *   「无可发布的 Skill 版本」（py 同文案同码）。
   */
  async publish(tenantId: string, skillId: string): Promise<SkillVersionView> {
    // 先 404 后 409：不可见一律按"不存在"报，不泄漏存在性（I-1）。
    await this.get(tenantId, skillId);
    const published = await this.#repo(tenantId).publish(new Scope(tenantId).ref(skillId));
    if (published === null) {
      throw authError(ERROR_CODES.CONFLICT, "无可发布的 Skill 版本", { skill_id: skillId });
    }
    return toVersionView(published);
  }

  /**
   * 为某 skill 建一个 DRAFT 版本（`POST /skills/{id}/versions`）。
   *
   * 版本号重复 ⇒ 409（repo 的 `createVersion` 先查后插，ScopeError 在"父已确认可见"
   * 之后只剩"版本已存在"一种 ⇒ 统一翻 `CONFLICT`，py 同文案）。
   *
   * @throws {HttpException} 不可见 ⇒ 404；版本号重复 ⇒ 409。
   */
  async createVersion(
    tenantId: string,
    skillId: string,
    createdBy: string,
    input: CreateSkillVersionInput,
  ): Promise<SkillVersionView> {
    // 先 404（可见性），再让 repo 做查重 —— 与 publish 同序。
    await this.get(tenantId, skillId);
    let row: SkillVersionRow;
    try {
      row = await this.#repo(tenantId).createVersion(new Scope(tenantId).ref(skillId), {
        id: randomUUID(),
        version: input.version,
        createdBy,
        instructions: input.instructions ?? "",
        manifest: input.manifest ?? {},
      });
    } catch (error) {
      // 父可见性已在 get() 确认 ⇒ 此处 ScopeError 只能是版本号重复（uq 查重先查后插）。
      if (error instanceof Error && error.name === "ScopeError") {
        throw authError(ERROR_CODES.CONFLICT, "Skill 版本已存在", {
          skill_id: skillId,
          version: input.version,
        });
      }
      throw error;
    }
    return toVersionView(row);
  }

  /** 列出某 skill 的全部版本（`GET /skills/{id}/versions`；不可见 ⇒ 404）。 */
  async listVersions(tenantId: string, skillId: string): Promise<SkillVersionView[]> {
    // 先 404（与 py `_require_owned_skill` 同序），再读版本（repo 会再验一次父可见性）。
    await this.get(tenantId, skillId);
    const rows = await this.#repo(tenantId).listVersions(new Scope(tenantId).ref(skillId));
    return rows.map(toVersionView);
  }

  /**
   * 按名字解析当前生效 Skill（**纯查询** —— 验收 ④：`skill.resolved` 事件由 T3-08
   * 的 writer 承载，本方法零写、零审计、零副作用）。
   *
   * 解析序：按名取 skill（`uq_skill_tenant_name`，租户内唯一）→ `current_version_id`
   * 非空 → 按 id 取版本行（T3-06 补的 `SkillRepo.findVersionById`，登记偏差 #5）。
   *
   * @returns skill + 版本视图；skill 不存在 / 跨租户 / 无当前版本 / 版本行缺失 ⇒ `null`
   *   （**不抛**：调用方是 run 装配路径，"无技能"是正常分支，不是错误）。
   */
  async resolveSkill(tenantId: string, name: string): Promise<ResolvedSkill | null> {
    const repo = this.#repo(tenantId);
    const skill = await repo.findByName(name);
    if (skill === null || skill.current_version_id === null) {
      return null;
    }
    const ref = new Scope(tenantId).ref(skill.id);
    const version = await repo.findVersionById(ref, skill.current_version_id);
    if (version === null) {
      return null;
    }
    return { skill: toSkillView(skill), version: toVersionView(version) };
  }

  /** repo 的 `ScopeError`（值域校验）→ 422 `VALIDATION_ERROR`（同 agent 服务口径）。 */
  #mapValidation(error: unknown): Error {
    if (error instanceof Error && error.name === "ScopeError") {
      return authError(ERROR_CODES.VALIDATION_ERROR, error.message);
    }
    return error as Error;
  }
}

/**
 * 行 → 契约视图（键集合逐字对齐 `SkillResponse`：11 键）。
 *
 * `current_version` 恒 `null`：py `_to_skill_response` 的关键字参数从不被传 ⇒ 恒 None
 * （同形登记，偏差 #6）；解析真实版本号需按 id 反查版本行，py 也没做，本版不替它猜。
 */
export function toSkillView(row: SkillRow): SkillView {
  return {
    id: row.id,
    tenant_id: row.tenant_id ?? null,
    name: row.name,
    display_name: row.display_name ?? "",
    description: row.description ?? null,
    category: row.category ?? "",
    status: row.status,
    current_version_id: row.current_version_id ?? null,
    current_version: null,
    created_by: row.created_by ?? "",
    created_at: toIsoOrNull(row.created_at),
  };
}

/** 行 → 契约视图（键集合逐字对齐 `SkillVersionResponse`：8 键）。 */
export function toVersionView(row: SkillVersionRow): SkillVersionView {
  return {
    id: row.id,
    skill_id: row.skill_id,
    version: row.version,
    instructions: row.instructions ?? "",
    manifest: (row.manifest ?? {}) as Record<string, unknown>,
    status: row.status,
    created_by: row.created_by ?? "",
    created_at: toIsoOrNull(row.created_at),
  };
}
