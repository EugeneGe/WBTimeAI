/**
 * T2-05 · `permission` 字典的 **bootstrap 种子**（5 行 + 通配 `*`）。
 *
 * 为什么是「种子」而不是「迁移」
 * ----------------------------
 * 这张表的**结构**早就由 DDL 冻结（`output/ddl.sqlite.sql` / 契约
 * `contracts/db/schema.v0018.*.sql`），本文件只往里灌**数据行**：
 * **零 DDL**（不建表、不加列、不加索引、不新建迁移文件）。
 * 依据：计划 `01-身份与授权.md` §4.1「字典内容属 bootstrap 种子，不产生 DDL/schema 变更」。
 *
 * 幂等（本文件的核心语义）
 * ----------------------
 * `permission.code` 上有唯一索引 `ix_permission_code`，因此「按 code 去重」是数据库
 * 层保证的；本文件在**应用层**再做一次 pre-check，目的是让**重复执行不产生第二行**
 * 这件事可测、`inserted` / `skipped` 可审计，而不是靠捕获异常来猜。
 * 两处都保留的原因见 {@link seedPermissions} 的注释（并发下的唯一键冲突必须被吞成 skip，
 * 否则一次并发 bootstrap 就会以「启动失败」告终）。
 *
 * 范围（本版只落 6 行）
 * -------------------
 * `marketplace:import` · `marketplace:export` · `evaluation:read` · `evaluation:write` ·
 * `evaluation:run` · `*`。其余权限码按 `<resource>:<action>` 形态**登记但不落行**
 * —— 字典内容属种子，逐版追加，不在本版猜。
 */

import { randomUUID } from "node:crypto";

import { permission as pgPermission } from "../schema/pg/index.js";
import { permission as sqlitePermission } from "../schema/sqlite/index.js";
import { resolveTable, type SqlDialect } from "../repositories/dialect.js";
import {
  ADMIN_PERMISSION,
  PermissionCatalog,
  type PermissionRow,
} from "../repositories/permission-catalog.js";
import type { DrizzleDatabase } from "../repositories/scoped-repo.js";
import { UNSCOPED_WHITELIST, UnscopedTableRepo } from "../repositories/unscoped-repo.js";

/** 通配权限码（`ADMIN_PERMISSION`）：此处**再导出**而非另立常量，避免出现两个 `*`。 */
export { ADMIN_PERMISSION };

/**
 * 本版落地的 5 个具体权限码（不含通配）。
 *
 * 顺序即种子写入顺序（稳定，便于 diff 与审计）。前 5 码的路由族在 V0.5.0 / V0.7.0，
 * 本版只落「字典行 + 守卫单测」（计划 §8 J-6b）。
 */
export const PERMISSION_CODES = Object.freeze([
  "marketplace:import",
  "marketplace:export",
  "evaluation:read",
  "evaluation:write",
  "evaluation:run",
] as const);

/** 5 个具体权限码的联合类型（守卫工厂可用它把「码写错」挡在编译期）。 */
export type SeedPermissionCode = (typeof PERMISSION_CODES)[number];

/** 种子里的一行。`description` 可空（DDL 允许 NULL）。 */
export interface PermissionSeedEntry {
  readonly code: string;
  readonly name: string;
  readonly description: string | null;
}

/**
 * 种子数据（6 行 = 5 具体码 + 1 通配）。
 *
 * `name` / `description` 是给人看的字典说明；`code` 才是判定的唯一依据。
 * 通配行的 `name` 与 `description` 与旧线 `ADMIN_PERMISSION` 口径一致。
 */
export const PERMISSION_SEED: readonly PermissionSeedEntry[] = Object.freeze([
  {
    code: "marketplace:import",
    name: "市场包导入",
    description: "把市场包导入当前工作空间（市场侧 M-04 明文凭据扫描在此前置）",
  },
  {
    code: "marketplace:export",
    name: "市场包导出",
    description: "把本地资产导出为市场包并发布",
  },
  {
    code: "evaluation:read",
    name: "评测读取",
    description: "查看评测集与评测结果",
  },
  {
    code: "evaluation:write",
    name: "评测写入",
    description: "创建 / 修改评测集与评测配置",
  },
  {
    code: "evaluation:run",
    name: "评测执行",
    description: "触发一次评测运行（会消耗执行资源）",
  },
  {
    code: ADMIN_PERMISSION,
    name: "平台管理员（通配）",
    description: "ADMIN_PERMISSION：命中即视为拥有全部权限码（判定见 hasPermission）",
  },
]);

/** 一次种子的执行结果（可审计：谁被写入、谁因已存在被跳过）。 */
export interface SeedPermissionsResult {
  /** 本次真正插入的码（按种子顺序）。 */
  readonly inserted: readonly string[];
  /** 本次跳过的码（已存在，或并发插入被唯一键挡下）。 */
  readonly skipped: readonly string[];
  /** 种子总行数（恒等于 {@link PERMISSION_SEED}.length）。 */
  readonly total: number;
}

/**
 * 种子写入通道：**只加写能力**，读仍走 {@link PermissionCatalog}。
 *
 * 为什么不在 `PermissionCatalog` 上直接加 `create`：那个类是 T2-03 的成品，且它是
 * 「只读字典」通道（白名单 #1 的理由写的就是「只读字典，不含任何租户私有数据」）。
 * 给只读通道加写方法会让那句白名单理由失真；改为在种子侧继承同一基类
 * （`UnscopedTableRepo`，构造期仍受白名单闸门约束、仍走同一套 limit / 列快照纪律），
 * 既没有绕过纪律，也没有改动他人成品。
 */
class PermissionSeedWriter extends UnscopedTableRepo<PermissionRow> {
  constructor(db: DrizzleDatabase, dialect: SqlDialect) {
    super(
      db,
      resolveTable(dialect, pgPermission, sqlitePermission),
      UNSCOPED_WHITELIST.permission,
    );
  }

  /** 插入一行字典。`id` 由本方法生成（DDL 无默认值）。 */
  insert(entry: PermissionSeedEntry): Promise<PermissionRow> {
    return this.insertRow({
      id: randomUUID(),
      code: entry.code,
      name: entry.name,
      description: entry.description,
    });
  }
}

/**
 * 幂等灌入权限码字典。
 *
 * 幂等的三层保障（缺一层都不够）：
 *  1. **数据库**：`ix_permission_code` 唯一索引 —— 真正的最终裁决；
 *  2. **应用层 pre-check**（逐码 `findByCode`）：让「已存在 ⇒ skipped」成为**可观测结果**，
 *     而不是靠异常反推；也让重复执行的结果稳定可测（第二次 `inserted=[]`）。
 *     刻意不用 `listCodes()` 做批量预判：那个方法有 1..500 的 limit 上限，字典一旦超过
 *     500 行，超出的码会被**静默漏判**成「不存在」→ 重复插入 → 唯一键冲突。逐码查询没有这个上限。
 *  3. **唯一键冲突吞成 skip**：两次 bootstrap 并发时，pre-check 会同时判「不存在」，
 *     此时后到的那次插入必然撞唯一键；这是**预期的并发结果**，不是错误。
 *     只吞唯一键冲突，其它约束错误（NOT NULL 等）照样抛 —— 否则真 bug 会被静默吃掉。
 *
 * @param db drizzle 实例
 * @param dialect 方言（缺省 `"pg"` = 生产档；测试传 `"sqlite"`）
 * @returns `{ inserted, skipped, total }`
 * @throws 非唯一键类错误（如 NOT NULL / 列长超限）原样抛出。
 */
export async function seedPermissions(
  db: DrizzleDatabase,
  dialect: SqlDialect = "pg",
): Promise<SeedPermissionsResult> {
  const catalog = new PermissionCatalog(db, dialect);
  const writer = new PermissionSeedWriter(db, dialect);

  const inserted: string[] = [];
  const skipped: string[] = [];

  for (const entry of PERMISSION_SEED) {
    const existing = await catalog.findByCode(entry.code);
    if (existing !== null) {
      skipped.push(entry.code);
      continue;
    }
    try {
      await writer.insert(entry);
      inserted.push(entry.code);
    } catch (error) {
      if (isUniqueViolation(error)) {
        // 并发 bootstrap：另一次 seed 抢先插入。语义上等价于「已存在」。
        skipped.push(entry.code);
        continue;
      }
      throw error;
    }
  }

  return { inserted, skipped, total: PERMISSION_SEED.length };
}

/**
 * 判定一个错误是否是**唯一键冲突**（跨方言）。
 *
 * SQLite 报文形如 `UNIQUE constraint failed: permission.code`；
 * PG 报文形如 `duplicate key value violates unique constraint "ix_permission_code"`
 * （`code === "23505"`）。两种都要认，否则同一段 seed 在两种档上行为不同。
 */
function isUniqueViolation(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as { code?: unknown; message?: unknown };
  if (candidate.code === "23505") return true; // PG unique_violation
  if (typeof candidate.message !== "string") return false;
  return /unique constraint|duplicate key value|UNIQUE constraint failed/i.test(candidate.message);
}
