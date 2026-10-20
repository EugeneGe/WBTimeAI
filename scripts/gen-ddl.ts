/**
 * T1-03 · 双档 DDL generator（PostgreSQL / SQLite）。
 *
 * 目的（DoD#1）
 * ------------
 * 把 TS 数据层（``packages/db/src/schema/``）落成**可执行的双档 DDL 文本**，交给
 * ``scripts/check_drizzle_parity.py`` 与冻结oracle-binary（``contracts/schema.v0018.*``）做零差异比对。
 *
 * 两种 source（``--source``）
 * --------------------------
 * * ``model``（默认）：读 ``packages/db/src/schema/model.ts``。该 model 与 pg/ sqlite/ 下的
 *   TS schema 文件由 ``scripts/gen-drizzle-schema.mjs`` **同一次运行**产出 ⇒ 同源。
 *   **零第三方依赖**，安装前即可运行（本仓 T1-03 施工期即为该状态）。
 * * ``drizzle``：动态 import 真正的 drizzle 表对象（``pg/index.ts`` / ``sqlite/index.ts``），
 *   用 drizzle 的 ``getTableConfig()`` + 列的 ``getSQLType()`` **按方言**取结构，再走同一套
 *   emitter。需要 ``pnpm install`` 之后才能跑；依赖不可得时以退出码 **2** 退出并给出原因，
 *   **绝不**退化到另一档去冒充。
 *
 * 为什么 SQLite 侧 emit 类型直接用 model 里那份、而不是 drizzle 的渲染结果
 * ----------------------------------------------------------------------
 * 冻结契约里 SQLite 的 ``CHAR(36)`` / ``DATETIME`` / ``NUMERIC(18, 6)`` 是**旧 ORM 编译结果**，
 * drizzle 的内建列类型会把它们渲染成 ``text(36)`` / ``text`` / ``numeric``。类型不是约定项
 * （parity 明确「类型不要求一致」），但为了让 DDL 与冻结文本**逐字**可比，emitter 统一采用
 * ``contracts/db/type-map.csv`` 的 emit 原文 —— 那份 CSV 才是冻结的类型面 oracle。
 *
 * 文件格式（TS 用 Node ≥22.18 的 type-stripping 直跑，**不依赖 tsc**）：
 *
 *   node scripts/gen-ddl.ts
 *   node scripts/gen-ddl.ts --source drizzle
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  GENERATED_COUNTS,
  INDEX_OBJECTS_TOTAL,
  PG_EXTENSIONS,
  PG_RAW_INDEXES,
  SCHEMA_VERSION,
  SQLITE_DIALECT_ONLY,
  TABLES,
  type ModelRawIndex,
  type ModelTable,
} from "../packages/db/src/schema/model.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..");

/** PG 保留字：需加双引号（SQLite 不需要，故只在 pg 分支生效）。 */
const PG_RESERVED = new Set(["user", "order", "group", "table", "select", "references"]);

interface EmitOptions {
  source: "model" | "drizzle";
  outDir: string;
}

interface ScalarRow {
  tables: ModelTable[];
  rawIndexes: ModelRawIndex[];
}

// ---------------------------------------------------------------------------
// 入口
// ---------------------------------------------------------------------------

function parseArgs(argv: string[]): EmitOptions {
  const opts: EmitOptions = { source: "model", outDir: join(REPO, "output") };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--source") {
      opts.source = argv[i + 1] === "drizzle" ? "drizzle" : "model";
      i += 1;
    } else if (argv[i] === "--out") {
      opts.outDir = resolve(argv[i + 1]);
      i += 1;
    } else if (argv[i] === "--help") {
      printUsage();
      process.exit(0);
    } else {
      throw new Error(`未知参数：${argv[i]}（--help 查看用法）`);
    }
  }
  return opts;
}

function printUsage(): void {
  process.stdout.write(
    [
      "用法: node scripts/gen-ddl.ts [--source model|drizzle] [--out <dir>]",
      "",
      "  --source model    （默认）从 packages/db/src/schema/model.ts 取结构，零第三方依赖",
      "  --source drizzle  动态 import drizzle 表对象并用 getTableConfig/getSQLType 取结构（需 pnpm install）",
      "  --out <dir>       输出目录（默认 output/）",
      "",
      "产物: <out>/ddl.pg.sql, <out>/ddl.sqlite.sql",
      "",
    ].join("\n")
  );
}

async function main(argv: string[]): Promise<void> {
  const opts = parseArgs(argv);
  const tables = opts.source === "drizzle" ? await loadFromDrizzle() : { tables: [...TABLES], rawIndexes: [...PG_RAW_INDEXES] };

  const pg = emitPg(tables, opts.source);
  const sqlite = emitSqlite(tables, opts.source);

  mkdirSync(opts.outDir, { recursive: true });
  const pgPath = join(opts.outDir, "ddl.pg.sql");
  const sqlitePath = join(opts.outDir, "ddl.sqlite.sql");
  writeFileSync(pgPath, pg, "utf8");
  writeFileSync(sqlitePath, sqlite, "utf8");

  process.stdout.write(
    [
      "=".repeat(78),
      "gen-ddl · 实跑输出",
      "=".repeat(78),
      `source                : ${opts.source}`,
      `schema_version        : ${SCHEMA_VERSION}`,
      `表                    : ${tables.tables.length}`,
      `列                    : ${tables.tables.reduce((n, t) => n + t.columns.length, 0)}`,
      `metadata 索引         : ${tables.tables.reduce((n, t) => n + t.indexes.length, 0)}`,
      `raw 索引（PG）        : ${tables.rawIndexes.length}（hnsw ${tables.rawIndexes.filter((i) => i.method === "hnsw").length}）`,
      `索引对象合计           : PG ${INDEX_OBJECTS_TOTAL.pg} / SQLite ${INDEX_OBJECTS_TOTAL.sqlite}`,
      `SQLite 专属对象        : ${SQLITE_DIALECT_ONLY.length}`,
      `输出                  : ${rel(pgPath)} (${pg.length} bytes)`,
      `                        ${rel(sqlitePath)} (${sqlite.length} bytes)`,
      `下一步                : python scripts/check_drizzle_parity.py`,
      "",
    ].join("\n")
  );
}

function rel(p: string): string {
  return p.replace(`${REPO}\\`, "").replace(`${REPO}/`, "").replace(/\\/g, "/");
}

/**
 * ``--source drizzle``：把真正的 drizzle 表对象 introspect 回结构。
 * 依赖不可得时**就地失败**（退出 2），不回退到 model —— 回退会让「已用 drizzle 验证」变成谎言。
 */
async function loadFromDrizzle(): Promise<ScalarRow> {
  let pgCore: any;
  let pgTables: any;
  try {
    pgCore = await import("drizzle-orm/pg-core");
    pgTables = await import("../packages/db/src/schema/pg/index.ts");
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    process.stderr.write(
      [
        "",
        "x --source drizzle 依赖不可得：drizzle-orm / drizzle schema 模块无法加载。",
        `  原因：${reason}`,
        "  处置：先执行 `pnpm install`（由 team-lead 统一安装），再重跑本命令；",
        "        或改用默认 `--source model`（零第三方依赖，可立即运行）。",
        "  纪律：本分支不回退到 model 冒充 drizzle 结果，故以退出码 2 退出。",
        "",
      ].join("\n")
    );
    process.exit(2);
  }
  const raw: ModelTable[] = [];
  for (const table of Object.values(pgTables.ALL_PG_TABLES) as any[]) {
    const cfg = pgCore.getTableConfig(table);
    raw.push({
      name: cfg.name,
      primaryKey: cfg.primaryKeys.map((pk: any) => pk.columns.map((c: any) => c.name)).flat(),
      columns: cfg.columns.map((c: any) => ({
        name: c.name,
        pgType: c.getSQLType(),
        sqliteType: "",
        nullable: !c.notNull,
        pgDefault: c.default === undefined ? null : String(c.default),
        sqliteDefault: null,
      })),
      indexes: cfg.indexes.map((i: any) => ({
        name: i.config.name,
        columns: i.config.columns.map((c: any) => c.name ?? c.value),
        unique: Boolean(i.config.unique),
        where: i.config.where ? String(i.config.where) : null,
      })),
      uniqueConstraints: cfg.uniqueConstraints.map((u: any) => ({
        name: u.name ?? "",
        columns: u.columns.map((c: any) => c.name),
      })),
      foreignKeys: cfg.foreignKeys.map((f: any) => ({
        name: f.getName(),
        columns: f.reference().columns.map((c: any) => c.name),
        referredTable: f.reference().foreignTable[pgCore.getTableName](),
        referredColumns: f.reference().foreignColumns.map((c: any) => c.name),
        ondelete: null,
        onupdate: null,
      })),
    });
  }
  return { tables: raw, rawIndexes: [...PG_RAW_INDEXES] };
}

// ---------------------------------------------------------------------------
// PostgreSQL emitter
// ---------------------------------------------------------------------------

function quotePg(name: string): string {
  return PG_RESERVED.has(name) ? `"${name}"` : name;
}

function emitPg(data: ScalarRow, source: string): string {
  const tables = data.tables;
  const totalColumns = tables.reduce((n, t) => n + t.columns.length, 0);
  const totalIndexes = tables.reduce((n, t) => n + t.indexes.length, 0);
  const uniqueIndexes = tables.reduce((n, t) => n + t.indexes.filter((i) => i.unique).length, 0);
  const partialIndexes = tables.reduce((n, t) => n + t.indexes.filter((i) => i.where).length, 0);
  const uniqueConstraints = tables.reduce((n, t) => n + t.uniqueConstraints.length, 0);
  const foreignKeys = tables.reduce((n, t) => n + t.foreignKeys.length, 0);

  const out: string[] = [];
  out.push("-- ==============================================================================");
  out.push("-- WBTimeAI DDL · PostgreSQL（由 scripts/gen-ddl.ts 生成，禁止手改）");
  out.push("-- ==============================================================================");
  out.push(`-- 生成者   : scripts/gen-ddl.ts --source ${source}（TS 线 V0.1.0 · T1-03）`);
  out.push(`-- 契约版本 : schema_version = ${SCHEMA_VERSION}（对应迁移链 0018 收敛态）`);
  out.push("-- 源① TS schema 结构 : packages/db/src/schema/pg/**.ts（61 张表）");
  out.push("-- 源② 类型 oracle    : contracts/db/type-map.csv 的 pg_emit_type（禁手填）");
  out.push("-- 源③ raw 索引       : packages/db/src/schema/model.ts 的 PG_RAW_INDEXES（ORM 编译不出来）");
  out.push("--");
  out.push(
    `-- 计数     : ${tables.length} 表 / ${totalColumns} 列 / ${totalIndexes} metadata 索引（unique ${uniqueIndexes} / partial ${partialIndexes}）`
  );
  out.push(`--            ${uniqueConstraints} unique 约束 / ${foreignKeys} 外键 / ${data.rawIndexes.length} raw 索引`);
  out.push(`--            索引对象合计 ${totalIndexes} + ${data.rawIndexes.length} = ${INDEX_OBJECTS_TOTAL.pg}`);
  out.push("--");
  out.push("-- 段落顺序：1) 扩展 → 2) 表 + 所属索引（按表名排序）→ 3) 外键 → 4) raw 索引");
  out.push("-- ==============================================================================");
  out.push("");

  out.push("-- ===== 1. 扩展（源③：迁移 0013 / 0014 的幂等语句）=====");
  for (const ext of PG_EXTENSIONS) {
    for (const src of ext.sources) out.push(`-- source: ${src}`);
    out.push(`${ext.sql}`);
  }
  out.push("");

  out.push("-- ===== 2. 表与所属索引（按表名排序）=====");
  for (const table of tables) {
    const body: string[] = [];
    for (const col of table.columns) {
      const parts = [col.pgType];
      if (col.pgDefault) parts.push(`DEFAULT ${col.pgDefault}`);
      if (!col.nullable) parts.push("NOT NULL");
      body.push(`\t${col.name} ${parts.join(" ")}, `);
    }
    body.push(`\tPRIMARY KEY (${table.primaryKey.join(", ")})`);
    for (const uq of table.uniqueConstraints) {
      body.push(`,\tCONSTRAINT ${uq.name} UNIQUE (${uq.columns.join(", ")})`);
    }
    out.push(`CREATE TABLE ${quotePg(table.name)} (`);
    out.push(body.join("\n"));
    out.push(");");
    for (const ix of table.indexes) {
      const uniq = ix.unique ? "UNIQUE " : "";
      const tail = ix.where ? ` WHERE ${ix.where}` : "";
      out.push(
        `CREATE ${uniq}INDEX ${ix.name} ON ${quotePg(table.name)} (${ix.columns.join(", ")})${tail};`
      );
    }
  }
  out.push("");

  out.push("-- ===== 3. 外键约束（延后到建表之后）=====");
  for (const table of tables) {
    for (const fk of table.foreignKeys) {
      const named = fk.name ? `CONSTRAINT ${fk.name} ` : "";
      out.push(
        `ALTER TABLE ${quotePg(table.name)} ADD ${named}FOREIGN KEY (${fk.columns.join(
          ", "
        )}) REFERENCES ${quotePg(fk.referredTable)} (${fk.referredColumns.join(", ")});`
      );
    }
  }
  out.push("");

  out.push("-- ===== 4. 迁移 raw DDL 索引（源③，ORM 无法表达）=====");
  out.push("-- 🔴 这一段是「纯 ORM 编译路线会静默漏掉」的部分（旧线已知缺陷）：");
  out.push("--    scripts/check_drizzle_parity.py 对这里有「恰好 2 个 hnsw」的硬断言。");
  for (const raw of data.rawIndexes) {
    out.push(`-- source: ${raw.source}`);
    out.push(raw.sql);
  }
  out.push("");
  return `${out.join("\n")}`;
}

// ---------------------------------------------------------------------------
// SQLite emitter
// ---------------------------------------------------------------------------

function emitSqlite(data: ScalarRow, source: string): string {
  const tables = data.tables;
  const totalColumns = tables.reduce((n, t) => n + t.columns.length, 0);
  const totalIndexes = tables.reduce((n, t) => n + t.indexes.length, 0);
  const uniqueIndexes = tables.reduce((n, t) => n + t.indexes.filter((i) => i.unique).length, 0);
  const partialIndexes = tables.reduce((n, t) => n + t.indexes.filter((i) => i.where).length, 0);
  const uniqueConstraints = tables.reduce((n, t) => n + t.uniqueConstraints.length, 0);
  const foreignKeys = tables.reduce((n, t) => n + t.foreignKeys.length, 0);
  const virtual = SQLITE_DIALECT_ONLY.filter((o) => o.kind === "virtual_table");
  const shadow = SQLITE_DIALECT_ONLY.filter((o) => o.kind === "shadow_table");
  const triggers = SQLITE_DIALECT_ONLY.filter((o) => o.kind === "trigger");

  const out: string[] = [];
  out.push("-- ==============================================================================");
  out.push("-- WBTimeAI DDL · SQLite（由 scripts/gen-ddl.ts 生成，禁止手改）");
  out.push("-- ==============================================================================");
  out.push(`-- 生成者   : scripts/gen-ddl.ts --source ${source}（TS 线 V0.1.0 · T1-03）`);
  out.push(`-- 契约版本 : schema_version = ${SCHEMA_VERSION}（对应迁移链 0018 收敛态）`);
  out.push("-- 源① TS schema 结构 : packages/db/src/schema/sqlite/**.ts（61 张表）");
  out.push("-- 源② 类型 oracle    : contracts/db/type-map.csv 的 sqlite_emit_type（禁手填）");
  out.push("-- 源③ SQLite 专属    : packages/db/src/schema/model.ts 的 SQLITE_DIALECT_ONLY（8 个对象）");
  out.push("--");
  out.push(
    `-- 计数     : ${tables.length} 表 / ${totalColumns} 列 / ${totalIndexes} metadata 索引（unique ${uniqueIndexes} / partial ${partialIndexes}）`
  );
  out.push(`--            ${uniqueConstraints} unique 约束 / ${foreignKeys} 外键 / raw 索引 ${0}（hnsw 系 PG 专属，SQLite 侧合法缺失）`);
  out.push(`--            索引对象合计 ${INDEX_OBJECTS_TOTAL.sqlite}`);
  out.push("--");
  out.push("-- 🔴 hnsw 是 PG 专属（pgvector USING hnsw），SQLite 侧**不存在** —— 合法 dialect_only 差异，不是遗漏。");
  out.push("-- 段落顺序：1) 表 + 所属索引（按表名排序）→ 2) FTS5 虚表 → 3) 影子表 → 4) 同步触发器");
  out.push("-- ==============================================================================");
  out.push("");

  out.push("-- ===== 1. 表与所属索引（按表名排序）=====");
  for (const table of tables) {
    const body: string[] = [];
    for (const col of table.columns) {
      const parts = [col.sqliteType];
      if (col.sqliteDefault) parts.push(`DEFAULT ${col.sqliteDefault}`);
      if (!col.nullable) parts.push("NOT NULL");
      body.push(`\t${col.name} ${parts.join(" ")}, `);
    }
    body.push(`\tPRIMARY KEY (${table.primaryKey.join(", ")}), `);
    for (const uq of table.uniqueConstraints) {
      body.push(`\tCONSTRAINT ${uq.name} UNIQUE (${uq.columns.join(", ")}), `);
    }
    for (const fk of table.foreignKeys) {
      // 命名外键必须带上 CONSTRAINT 名：契约的 sqlite 档 foreign_keys[].name 记了
      // fk_agent_current_version_id 这类名字，SQLite 本身支持命名表约束，丢掉它
      // 就是 DDL 相对契约的**信息损失**（T1-03 首轮 parity 在此报 4 条差异）。
      const named = fk.name ? `CONSTRAINT ${fk.name} ` : "";
      body.push(
        `\t${named}FOREIGN KEY(${fk.columns.join(", ")}) REFERENCES ${fk.referredTable} (${fk.referredColumns.join(
          ", "
        )}), `
      );
    }
    // 去掉最后一行的尾随逗号（SQLite 不接受行尾悬空逗号）。
    if (body.length > 0) {
      body[body.length - 1] = body[body.length - 1].replace(/, $/, "");
    }
    out.push(`CREATE TABLE ${table.name} (`);
    out.push(body.join("\n"));
    out.push(");");
    for (const ix of table.indexes) {
      const uniq = ix.unique ? "UNIQUE " : "";
      const tail = ix.where ? ` WHERE ${ix.where}` : "";
      out.push(`CREATE ${uniq}INDEX ${ix.name} ON ${table.name} (${ix.columns.join(", ")})${tail};`);
    }
  }
  out.push("");

  out.push("-- ===== 2. FTS5 虚表（源③）=====");
  for (const obj of virtual) {
    out.push(`-- source: ${obj.source}`);
    out.push(`${obj.sql}`);
  }
  out.push("");
  out.push("-- ===== 3. FTS5 影子表（源③：sqlite_master 回读，**不可重放**）=====");
  out.push("-- 🔴 这 4 张是 FTS5 的内部影子表，**由 CREATE VIRTUAL TABLE 自动创建**。");
  out.push("--    手工 CREATE 会被 SQLite 拒绝：object name reserved for internal use（实测）。");
  out.push("--    故本段只**登记**它们（parity 要对齐契约的 8 个方言专属对象），不产出可执行语句。");
  for (const obj of shadow) {
    out.push(`-- shadow-table: ${obj.name} | source: ${obj.source}`);
    out.push(`--   readback: ${obj.sql}`);
  }
  out.push("");
  out.push("-- ===== 4. FTS5 同步触发器（源③：ai / ad / au）=====");
  out.push("-- 🔴 功能性对象：external content 模式下缺这三个触发器，FTS 索引不随基表更新。");
  for (const obj of triggers) {
    out.push(`-- source: ${obj.source}`);
    out.push(`${obj.sql}`);
  }
  out.push("");
  out.push(
    `-- 汇总：方言专属对象 ${SQLITE_DIALECT_ONLY.length} 个（虚表 ${virtual.length} + 影子表 ${shadow.length} + 触发器 ${triggers.length}；PG DDL 里 0 处）`
  );
  out.push("");
  return `${out.join("\n")}`;
}

void main(process.argv.slice(2)).catch((error: unknown) => {
  const reason = error instanceof Error ? `${error.message}\n${error.stack ?? ""}` : String(error);
  process.stderr.write(`gen-ddl 失败：${reason}\n`);
  process.exit(2);
});
