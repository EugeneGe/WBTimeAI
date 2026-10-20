/**
 * T1-03 · Drizzle 运行时自省（门禁的「TS 源」证据，**不靠正则解析 TypeScript**）。
 *
 * 为什么要这个文件
 * ----------------
 * V0.1.0 的 parity 门禁最初用正则扫 ``packages/db/src/schema/{pg,sqlite}/*.ts`` 来证明
 * 「DDL 不是文本拼的、与 TS schema 是同一棵树」。正则解析 TS 是脆弱设计：跨行写法、
 * 嵌套括号、``foreignKey({...})`` 回调形式都会漏识别，2026-10-21 首跑就误报 32 条。
 *
 * 本文件改走 **运行时**：把真实的 drizzle 表对象 import 进来，用 ``getTableConfig()``
 * 读出列 / 主键 / 唯一约束 / 外键 / 索引的**真实结构**，序列化成 JSON。门禁读 JSON
 * 做结构对结构比较 —— 表对象里没有的，JSON 里就不可能有。
 *
 * 产物（``--out`` 目录下）
 * -----------------------
 * * ``drizzle-introspect.pg.json``
 * * ``drizzle-introspect.sqlite.json``
 *
 * 每个 JSON 都带 ``source`` 段：``packages/db/src/schema/**\/*.ts`` 的 sha256 清单。
 * 门禁会用清单重算哈希 —— **改了 schema 却没重跑自省 ⇒ 直接红（source.stale）**，
 * 避免「JSON 是三天前的、门禁照样绿」这种哑真。
 *
 * 用法::
 *
 *     pnpm --filter @wbtime/db run introspect
 *     node packages/db/dist/schema/_introspect.js --out output
 *
 * 🔴 分层说明：本文件 import drizzle-orm 属于**必要例外**（读表结构，不发查询）。
 *    业务查询的 ORM import 只允许出现在 ``src/repositories/``。
 */

import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { getTableConfig as getPgTableConfig } from "drizzle-orm/pg-core";
import { getTableConfig as getSqliteTableConfig } from "drizzle-orm/sqlite-core";
import { getTableName } from "drizzle-orm";

import * as pgSchema from "./pg/index.js";
import * as sqliteSchema from "./sqlite/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
/** dist/schema → packages/db */
const PACKAGE_ROOT = resolve(HERE, "..", "..");
/** packages/db/src/schema */
const SCHEMA_ROOT = resolve(PACKAGE_ROOT, "src", "schema");
const REPO_ROOT = resolve(PACKAGE_ROOT, "..", "..");

// ---------------------------------------------------------------------------
// 结构类型（只声明**用得到**的那几项，避免把 drizzle 的内部类型抄一遍）
// ---------------------------------------------------------------------------

interface ColumnLike {
  readonly name: string;
  readonly notNull: boolean;
  readonly hasDefault: boolean;
  readonly primary: boolean;
  getSQLType(): string;
}

interface IndexLike {
  readonly config: {
    readonly name?: string;
    readonly columns: readonly unknown[];
    readonly unique?: boolean;
    readonly where?: unknown;
  };
}

interface UniqueConstraintLike {
  readonly name?: string;
  readonly columns: readonly ColumnLike[];
}

interface ForeignKeyLike {
  readonly getName?: () => string | undefined;
  reference(): {
    readonly columns: readonly ColumnLike[];
    readonly foreignColumns: readonly ColumnLike[];
    readonly foreignTable: unknown;
  };
}

interface TableConfigLike {
  readonly name: string;
  readonly columns: readonly ColumnLike[];
  readonly primaryKeys: readonly { readonly columns: readonly ColumnLike[] }[];
  readonly uniqueConstraints: readonly UniqueConstraintLike[];
  readonly foreignKeys: readonly ForeignKeyLike[];
  readonly indexes: readonly IndexLike[];
}

interface IntrospectColumn {
  name: string;
  type: string;
  nullable: boolean;
  hasDefault: boolean;
}

interface IntrospectIndex {
  name: string;
  columns: string[];
  unique: boolean;
  /** 条件索引（partial）的 WHERE 子句在不在；具体 SQL 文本由 DDL 侧逐字比对。 */
  where_present: boolean;
}

interface IntrospectTable {
  name: string;
  columns: IntrospectColumn[];
  primary_key: string[];
  unique_constraints: { name: string | null; columns: string[] }[];
  foreign_keys: {
    name: string | null;
    columns: string[];
    referred_table: string;
    referred_columns: string[];
  }[];
  indexes: IntrospectIndex[];
}

interface IntrospectDoc {
  dialect: "pg" | "sqlite";
  generatedBy: string;
  schemaVersion: string;
  source: { root: string; files: { path: string; sha256: string }[] };
  counts: {
    tables: number;
    columns: number;
    metadata_indexes: number;
    unique_indexes: number;
    partial_indexes: number;
    unique_constraints: number;
    foreign_keys: number;
    primary_keys: number;
  };
  tables: IntrospectTable[];
}

// ---------------------------------------------------------------------------
// 入口
// ---------------------------------------------------------------------------

function parseOut(argv: string[]): string {
  const i = argv.indexOf("--out");
  if (i >= 0 && argv[i + 1]) return resolve(argv[i + 1]);
  return join(REPO_ROOT, "output");
}

function main(argv: string[]): void {
  const outDir = parseOut(argv);
  mkdirSync(outDir, { recursive: true });

  const source = collectSourceDigests();

  const pg = buildDoc("pg", pgSchema.ALL_PG_TABLES as Record<string, unknown>, getPgTableConfig as never, source);
  const sqlite = buildDoc(
    "sqlite",
    sqliteSchema.ALL_SQLITE_TABLES as Record<string, unknown>,
    getSqliteTableConfig as never,
    source
  );

  const pgPath = join(outDir, "drizzle-introspect.pg.json");
  const sqlitePath = join(outDir, "drizzle-introspect.sqlite.json");
  writeFileSync(pgPath, `${JSON.stringify(pg, null, 2)}\n`, "utf8");
  writeFileSync(sqlitePath, `${JSON.stringify(sqlite, null, 2)}\n`, "utf8");

  const lines = [
    "=".repeat(78),
    "drizzle-introspect · 实跑输出（运行时 getTableConfig，非正则解析）",
    "=".repeat(78),
  ];
  for (const doc of [pg, sqlite]) {
    lines.push(
      `  ${doc.dialect.padEnd(6)}: 表 ${doc.counts.tables} / 列 ${doc.counts.columns}` +
        ` / metadata 索引 ${doc.counts.metadata_indexes}（unique ${doc.counts.unique_indexes} / partial ${doc.counts.partial_indexes}）`
    );
    lines.push(
      `          外键 ${doc.counts.foreign_keys} / unique 约束 ${doc.counts.unique_constraints}` +
        ` / 主键 ${doc.counts.primary_keys}`
    );
  }
  lines.push(`  溯源文件 : ${source.files.length} 个 .ts（含 sha256 清单）`);
  lines.push(`  输出     : ${relative(REPO_ROOT, pgPath)}`);
  lines.push(`             ${relative(REPO_ROOT, sqlitePath)}`);
  lines.push("");
  process.stdout.write(lines.join("\n"));
}

// ---------------------------------------------------------------------------
// 结构抽取
// ---------------------------------------------------------------------------

function buildDoc(
  dialect: "pg" | "sqlite",
  tables: Record<string, unknown>,
  getConfig: (table: never) => TableConfigLike,
  source: IntrospectDoc["source"]
): IntrospectDoc {
  const names = Object.keys(tables);
  if (names.length === 0) {
    throw new Error(`INVALID(EMPTY)：${dialect} 侧 ALL_*_TABLES 为空，自省无从谈起`);
  }

  const out: IntrospectTable[] = [];
  for (const name of names.sort()) {
    const table = tables[name];
    if (!table) throw new Error(`INVALID(EMPTY)：${dialect}.${name} 表对象为 undefined`);
    const cfg = getConfig(table as never);
    out.push(extractTable(cfg));
  }

  const counts = {
    tables: out.length,
    columns: out.reduce((n, t) => n + t.columns.length, 0),
    metadata_indexes: out.reduce((n, t) => n + t.indexes.length, 0),
    unique_indexes: out.reduce((n, t) => n + t.indexes.filter((i) => i.unique).length, 0),
    partial_indexes: out.reduce((n, t) => n + t.indexes.filter((i) => i.where_present).length, 0),
    unique_constraints: out.reduce((n, t) => n + t.unique_constraints.length, 0),
    foreign_keys: out.reduce((n, t) => n + t.foreign_keys.length, 0),
    primary_keys: out.filter((t) => t.primary_key.length > 0).length,
  };

  return {
    dialect,
    generatedBy: "packages/db/dist/schema/_introspect.js",
    schemaVersion: "v0018",
    source,
    counts,
    tables: out,
  };
}

/** 剥掉 drizzle 的自动外键名：匹配 `<table>_<cols>_<refTable>_<refCols>_fk` 即视为匿名。 */
function normalizeFkName(
  table: string,
  name: string | null,
  columns: string[],
  referredTable: string,
  referredColumns: string[]
): string | null {
  if (!name) return null;
  const auto = `${table}_${columns.join("_")}_${referredTable}_${referredColumns.join("_")}_fk`;
  return name === auto ? null : name;
}

function extractTable(cfg: TableConfigLike): IntrospectTable {
  const pkColumns: string[] = [];
  for (const pk of cfg.primaryKeys) {
    for (const col of pk.columns) pkColumns.push(col.name);
  }
  // 单列主键在 drizzle 里是列上的 .primaryKey()，不出现在 primaryKeys[] 里
  if (pkColumns.length === 0) {
    for (const col of cfg.columns) {
      if (col.primary) pkColumns.push(col.name);
    }
  }

  return {
    name: cfg.name,
    columns: cfg.columns.map((col) => ({
      name: col.name,
      type: col.getSQLType(),
      nullable: !col.notNull,
      hasDefault: col.hasDefault,
    })),
    primary_key: pkColumns,
    // 列顺序必须**保持声明顺序**：契约里的 uq 是 (tenant_id, name) 这种业务顺序，
    // 排序会把它变成 (name, tenant_id)，制造纯表示噪声。
    unique_constraints: cfg.uniqueConstraints.map((uq) => ({
      name: uq.name ?? null,
      columns: uq.columns.map((c) => c.name),
    })),
    foreign_keys: cfg.foreignKeys
      .map((fk) => {
        const ref = fk.reference();
        const columns = ref.columns.map((c) => c.name);
        const referredTable = getTableName(ref.foreignTable as never) as string;
        const referredColumns = ref.foreignColumns.map((c) => c.name);
        return {
          // drizzle 对匿名外键会自动取名 `<表>_<列>_<引用表>_<引用列>_fk`。
          // 契约里这些外键的 name 是 null（旧线没命名），自动名属于**表示噪声**，
          // 必须剥掉还成 null；否则 155 条 FK 会被误判成「名字不一致」。
          name: normalizeFkName(cfg.name, fk.getName?.() ?? null, columns, referredTable, referredColumns),
          columns,
          referred_table: referredTable,
          referred_columns: referredColumns,
        };
      })
      .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))),
    indexes: cfg.indexes
      .map((idx) => {
        const name = idx.config.name;
        if (!name) throw new Error("索引对象没有名字：drizzle 的 index() 必须显式命名");
        const columns = idx.config.columns
          .map((c) => (c as { name?: string }).name)
          .filter((c): c is string => typeof c === "string");
        if (columns.length !== idx.config.columns.length) {
          throw new Error(`索引 ${name} 的列里有非列对象（表达式索引），自省无法忠实还原`);
        }
        return { name, columns, unique: Boolean(idx.config.unique), where_present: Boolean(idx.config.where) };
      })
      .sort((a, b) => a.name.localeCompare(b.name)),
  };
}

// ---------------------------------------------------------------------------
// 溯源清单
// ---------------------------------------------------------------------------

function collectSourceDigests(): IntrospectDoc["source"] {
  const files: { path: string; sha256: string }[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.isFile() && entry.name.endsWith(".ts")) {
        const digest = createHash("sha256").update(readFileSync(full)).digest("hex");
        files.push({ path: relative(REPO_ROOT, full).replace(/\\/g, "/"), sha256: digest });
      }
    }
  };
  walk(SCHEMA_ROOT);
  files.sort((a, b) => a.path.localeCompare(b.path));
  if (files.length === 0) {
    throw new Error(`INVALID(EMPTY)：${SCHEMA_ROOT} 下没有 .ts，自省结果无法溯源`);
  }
  return { root: relative(REPO_ROOT, SCHEMA_ROOT).replace(/\\/g, "/"), files };
}

// 只有「被当作脚本直接执行」时才跑；被 `src/index.ts` re-export 时保持静默。
const invokedDirectly =
  typeof process.argv[1] === "string" && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (invokedDirectly) main(process.argv.slice(2));
