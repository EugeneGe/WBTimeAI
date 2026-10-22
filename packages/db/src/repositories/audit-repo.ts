/**
 * T3-13 · `audit_log` / `feature_flag` 两个薄仓储。
 *
 * 为什么进 db 包而不是在 api 里直接 `pg.audit_log`：`@wbtime/db` 根出口的 schema 走
 * `pg` / `sqlite` **命名空间**，命名空间成员上 drizzle 的类型推断是 `unknown`。
 * 仓储文件可以走 `../schema/pg/*.js` 的**相对路径**拿到完整列类型 —— 既有惯例
 * （`mcp-repo.ts` 同款）。两个类都是**薄**的：不做 scope 谓词（`audit_log` 的租户列
 * 由写入方保证；`feature_flag` 是平台级单行 —— R3-14 ③ 明确本版不做租户键）。
 */

import { and, eq, getTableColumns, type Table } from "drizzle-orm";
import { randomUUID } from "node:crypto";

import { audit_log as pgAuditLog } from "../schema/pg/audit.js";
import { audit_log as sqliteAuditLog } from "../schema/sqlite/audit.js";
import { feature_flag as pgFeatureFlag } from "../schema/pg/identity.js";
import { feature_flag as sqliteFeatureFlag } from "../schema/sqlite/identity.js";
import { instantLiteral, resolveTable, type SqlDialect } from "./dialect.js";
import type { DrizzleDatabase } from "./scoped-repo.js";

/** `audit_log.metadata` 的落库形态（§10.2 清单；键名 snake_case 与文档一致）。 */
export type SafetyAuditMetadata = Record<string, unknown>;

/** 一次安全判定审计的写入入参。 */
export interface InsertAuditInput {
  readonly tenantId: string;
  readonly action: string;
  readonly resourceType: string;
  readonly resourceId: string;
  readonly outcome: string;
  readonly durationMs: number;
  readonly requestId: string;
  readonly runId?: string | null;
  readonly toolCallId?: string | null;
  readonly metadata: SafetyAuditMetadata;
}

/** `audit_log` 薄写入仓储。 */
export class AuditLogRepo {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;

  constructor(db: DrizzleDatabase, dialect: SqlDialect) {
    this.#db = db;
    this.#dialect = dialect;
  }

  /**
   * 插入一行审计。
   *
   * @returns 是否成功（失败**不抛** —— §9.1-6：审计写入失败不阻断业务路径）。
   */
  async create(input: InsertAuditInput): Promise<boolean> {
    // ⚠️ 类型逃逸（登记偏差）：双档表经 `resolveTable` 返回 `Table` 基类，drizzle 的
    // insert/select 泛型在基类上推不出列 ⇒ 仓储内部用 any。运行时行为与具体表对象完全一致。
    /* eslint-disable @typescript-eslint/no-explicit-any */
    const db = this.#db as any;
    const table: Table = auditTable(this.#dialect);
    try {
      await db
        .insert(table)
        .values({
          id: randomUUID(),
          tenant_id: input.tenantId,
          action: input.action,
          resource_type: input.resourceType,
          resource_id: input.resourceId,
          outcome: input.outcome,
          duration_ms: input.durationMs,
          request_id: input.requestId,
          run_id: input.runId ?? null,
          tool_call_id: input.toolCallId ?? null,
          metadata: input.metadata,
        } as never);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * 按 stage 数行数（§16-1 门禁断言用：`resource_id=<stage>` 的行数）。
   *
   * 读全部再过滤（行数小；`metadata.decision` 的值域断言在测试里做）。
   */
  async listByResourceId(tenantId: string, resourceId: string): Promise<Record<string, unknown>[]> {
    const db = this.#db as any;
    const table: Table = auditTable(this.#dialect);
    const columns = getTableColumns(table) as Record<string, never>;
    return await db
      .select()
      .from(table)
      .where(and(eq(columns.tenant_id, tenantId), eq(columns.resource_id, resourceId)));
  }
}

/** 双档表解析（audit）。 */
function auditTable(dialect: SqlDialect): Table {
  return resolveTable(dialect, pgAuditLog, sqliteAuditLog);
}

/** 双档表解析（feature_flag）。 */
function flagTable(dialect: SqlDialect): Table {
  return resolveTable(dialect, pgFeatureFlag, sqliteFeatureFlag);
}

/** `feature_flag` 行。 */
export interface FeatureFlagRow {
  readonly name: string;
  readonly enabled: boolean;
}

/** `feature_flag` 薄读取仓储。 */
export class FeatureFlagRepo {
  readonly #db: DrizzleDatabase;
  readonly #dialect: SqlDialect;

  constructor(db: DrizzleDatabase, dialect: SqlDialect) {
    this.#db = db;
    this.#dialect = dialect;
  }

  /** 按名取行；无行 ⇒ `null`（**无行 = 默认开** 的判定交给调用方）。 */
  async findByName(name: string): Promise<FeatureFlagRow | null> {
    const db = this.#db as any;
    const table: Table = flagTable(this.#dialect);
    const columns = getTableColumns(table) as Record<string, never>;
    const rows = await db
      .select()
      .from(table)
      .where(eq(columns.name, name))
      .limit(1);

    const row = rows[0];
    if (row === undefined) return null;
    return { name: String(row.name), enabled: row.enabled !== false };
  }

  /**
   * 写开关行（测试用；生产经 `GET /settings/features` 既有端点）。
   *
   * 幂等：同 `name` 覆盖 `enabled`。
   */
  async upsert(name: string, enabled: boolean): Promise<void> {
    const db = this.#db as any;
    const table: Table = flagTable(this.#dialect);
    const columns = getTableColumns(table) as Record<string, never>;
    const now = instantLiteral(this.#dialect, new Date());
    await db
      .insert(table)
      .values({ id: randomUUID(), name, enabled, created_at: now, updated_at: now })
      .onConflictDoUpdate({
        target: columns.name,
        set: { enabled, updated_at: now },
      });
  }
}
