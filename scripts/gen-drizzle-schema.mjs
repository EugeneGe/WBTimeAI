#!/usr/bin/env node
/**
 * T1-03 · Drizzle schema 生成器（Node ESM，标准库 only，零第三方依赖）。
 *
 * 职责
 * ----
 * 把冻结契约的三份 oracle **机械地**翻译成 TS 数据层代码 —— 禁止手抄 61 张表：
 *
 *   oracle ①  contracts/schema.v0018.pg.normalized.json     —— 结构权威（表/列/可空/索引/外键/PK）
 *   oracle ②  contracts/schema.v0018.sqlite.normalized.json —— 同上（SQLite 档），用于交叉验证
 *   oracle ③  contracts/db/type-map.csv                     —— **类型权威**（逐列 pg/sqlite emit 类型）
 *
 * 产物
 * ----
 *   packages/db/src/schema/pg/<domain>.ts        61 张表的 pgTable 定义
 *   packages/db/src/schema/sqlite/<domain>.ts    61 张表的 sqliteTable 定义
 *   packages/db/src/schema/{pg,sqlite}/index.ts  方言内汇总
 *   packages/db/src/schema/index.ts              双方言命名空间出口
 *   packages/db/src/schema/model.ts              DDL emitter 的唯一输入（同一次运行产出 ⇒ 同源）
 *   output/gen-drizzle-schema.report.json        实跑计数，供施工记录引用（禁手填）
 *
 * 为什么 model.ts 不算「第二份手抄真相」
 * --------------------------------------
 * DDL 由 ``scripts/gen-ddl.ts`` 从 model.ts 发出；model.ts 与上面两棵 TS 树是**同一次脚本
 * 运行、读同一份 normalized json** 的产物，故「TS schema → DDL」链条内部不可能漂移。
 * 而「== 冻结契约」这一步由 ``scripts/check_drizzle_parity.py`` 独立断言：它既把发出的 DDL
 * 文本归一化后比对，也直接扫描落盘的 TS 源文件（该脚本 §硬断言组 B）。
 *
 * 用法
 * ----
 *   node scripts/gen-drizzle-schema.mjs
 *   node scripts/gen-drizzle-schema.mjs --check     # 只校验产物是否与当前生成结果逐字节一致
 */

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");

const PATHS = {
  pg: path.join(REPO, "contracts", "schema.v0018.pg.normalized.json"),
  sqlite: path.join(REPO, "contracts", "schema.v0018.sqlite.normalized.json"),
  typeMap: path.join(REPO, "contracts", "db", "type-map.csv"),
  pgDir: path.join(REPO, "packages", "db", "src", "schema", "pg"),
  sqliteDir: path.join(REPO, "packages", "db", "src", "schema", "sqlite"),
  schemaDir: path.join(REPO, "packages", "db", "src", "schema"),
  report: path.join(REPO, "output", "gen-drizzle-schema.report.json"),
};

/** 领域分组：61 张表按业务域切分。值域必须与 oracle 表集合**完全相等**（脚本内断言）。 */
const DOMAINS = {
  identity: [
    "tenant", "organization", "workspace", "workspace_environment", "user", "membership",
    "role", "permission", "role_permission", "refresh_token", "login_attempt", "session",
    "resource_permission", "feature_flag",
  ],
  agent: [
    "agent", "agent_version", "agent_event", "agent_run", "agent_skill", "agent_tool",
    "agent_knowledge",
  ],
  model: ["credential", "model_provider", "model_provider_credential", "model"],
  tool: ["tool", "tool_version", "tool_call", "tool_permission"],
  skill: ["skill", "skill_version", "skill_resource", "plugin"],
  knowledge: [
    "knowledge_base", "document", "document_chunk", "embedding", "memory", "memory_relation",
  ],
  conversation: [
    "conversation", "message", "approval", "sandbox_session", "mcp_server", "mcp_tool",
    "mcp_permission",
  ],
  workflow: [
    "workflow", "workflow_version", "workflow_node", "workflow_edge", "workflow_run",
    "workflow_node_run",
  ],
  task: ["project", "task", "task_execution", "schedule"],
  evaluation: ["evaluation_dataset", "evaluation_case", "evaluation_run", "evaluation_result"],
  audit: ["audit_log"],
};

// ---------------------------------------------------------------------------
// 输入读取
// ---------------------------------------------------------------------------

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

/** RFC4180 兼容的最小 CSV 解析（去 BOM，保留字段原样）。 */
function parseCsv(text) {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.length > 0);
  const header = splitCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const cells = splitCsvLine(line);
    const row = {};
    header.forEach((key, i) => {
      row[key] = cells[i] ?? "";
    });
    return row;
  });
}

function splitCsvLine(line) {
  const out = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (inQuotes) {
      if (ch !== '"') {
        cur += ch;
      } else if (line[i + 1] === '"') {
        cur += '"';
        i += 1;
      } else {
        inQuotes = false;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      out.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  out.push(cur);
  return out;
}

// ---------------------------------------------------------------------------
// 列构造器：oracle emit 类型 → drizzle schema 定义函数
// ---------------------------------------------------------------------------

/**
 * PG 侧映射。这里只用 drizzle-orm/pg-core 的**列定义函数**，不引任何运行时 ORM 助手
 * （分层铁律 R2：ORM 只能在 repositories/）。
 *
 * 注：``FLOAT`` → ``doublePrecision``：PostgreSQL 里无精度限定的 ``float`` **就是**
 * ``double precision``（PG 文档 §8.1.3），而 DDL 文本仍由 model.ts 原样 emit 为 ``FLOAT``。
 */
function pgBuilder(emit, colName) {
  const n = JSON.stringify(colName);
  const table = {
    UUID: { call: `uuid(${n})`, imports: ["uuid"] },
    "TIMESTAMP WITH TIME ZONE": {
      call: `timestamp(${n}, { withTimezone: true })`,
      imports: ["timestamp"],
    },
    TEXT: { call: `text(${n})`, imports: ["text"] },
    INTEGER: { call: `integer(${n})`, imports: ["integer"] },
    BOOLEAN: { call: `boolean(${n})`, imports: ["boolean"] },
    FLOAT: { call: `doublePrecision(${n})`, imports: ["doublePrecision"] },
    JSONB: { call: `jsonb(${n})`, imports: ["jsonb"] },
    JSON: { call: `json(${n})`, imports: ["json"] },
  };
  if (table[emit]) return table[emit];
  if (emit.startsWith("VARCHAR(")) {
    const len = emit.slice("VARCHAR(".length, -1);
    return { call: `varchar(${n}, { length: ${len} })`, imports: ["varchar"] };
  }
  if (emit.startsWith("NUMERIC(")) {
    const [precision, scale] = emit.slice("NUMERIC(".length, -1).split(",").map((s) => s.trim());
    return {
      call: `numeric(${n}, { precision: ${precision}, scale: ${scale} })`,
      imports: ["numeric"],
    };
  }
  if (emit.startsWith("VECTOR(")) {
    const dim = emit.slice("VECTOR(".length, -1);
    if (dim !== "1536") throw new Error(`未登记的向量维度：${emit}`);
    return { call: `vector1536(${n})`, imports: ["vector1536"], fromLocalTypes: true };
  }
  throw new Error(`PG emit 类型未登记映射：${emit}`);
}

/**
 * SQLite 侧映射。
 *
 * 注 1：``text(col, { length: n })`` 只是 TS 侧长度提示，SQLite 并不强制；DDL 里的
 *       ``CHAR(36)`` / ``VARCHAR(n)`` 由 gen-ddl.ts 按 type-map.csv **原样** emit。
 * 注 2：SQLite 的 DDL 默认值**不在这里编码** —— drizzle 列级 ``.default()`` 只接受字面量，
 *       表达 ``CURRENT_TIMESTAMP`` 必须引 ORM 的 ``sql`` 助手，而 ``schema/`` 层禁用它（R2）。
 *       故 92 个时间戳默认值只在 DDL 档出现，TS 侧缺省由应用层赋值（施工记录已登记）。
 */
function sqliteBuilder(emit, colName) {
  const n = JSON.stringify(colName);
  const table = {
    "CHAR(36)": { call: `text(${n}, { length: 36 })`, imports: ["text"] },
    DATETIME: { call: `text(${n})`, imports: ["text"] },
    TEXT: { call: `text(${n})`, imports: ["text"] },
    INTEGER: { call: `integer(${n})`, imports: ["integer"] },
    BOOLEAN: { call: `integer(${n}, { mode: "boolean" })`, imports: ["integer"] },
    FLOAT: { call: `real(${n})`, imports: ["real"] },
    JSON: { call: `text(${n}, { mode: "json" })`, imports: ["text"] },
  };
  if (table[emit]) return table[emit];
  if (emit.startsWith("VARCHAR(")) {
    const len = emit.slice("VARCHAR(".length, -1);
    return { call: `text(${n}, { length: ${len} })`, imports: ["text"] };
  }
  if (emit.startsWith("NUMERIC(")) {
    // drizzle 0.45 的 sqlite `numeric` 只接受 { mode }，**没有** precision / scale
    // （硬塞会编译报 TS2353）。精度只在 DDL 文本里体现（NUMERIC(18, 6)），
    // 这与「类型不是 parity 判定项」的口径一致；差异已登记在施工记录 D-04。
    return { call: `numeric(${n})`, imports: ["numeric"] };
  }
  throw new Error(`SQLite emit 类型未登记映射：${emit}`);
}

function safeKey(name) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name) ? name : JSON.stringify(name);
}

function refColumnExpr(fromTable, refTable, col, namespace) {
  if (refTable === fromTable) return `t.${col}`;
  // 跨领域时必须走**命名空间访问**，不能提前 `const x = ns.x` 别名：
  // 两个领域互相 import（conversation ↔ agent、knowledge ↔ agent …）时，
  // 模块求值期的别名会撞上 TDZ（Cannot access 'agent' before initialization，实测）。
  // ExtraConfig 回调是 getTableConfig 时才求值的，命名空间访问天然安全。
  return namespace ? `${namespace}.${refTable}.${col}` : `${refTable}.${col}`;
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

function main(argv) {
  const checkOnly = argv.includes("--check");

  const pgDoc = readJson(PATHS.pg);
  const sqliteDoc = readJson(PATHS.sqlite);
  const typeRows = parseCsv(fs.readFileSync(PATHS.typeMap, "utf8"));

  if (pgDoc.schema_version !== sqliteDoc.schema_version) {
    throw new Error("双档 normalized json 的 schema_version 不一致");
  }
  const version = pgDoc.schema_version;

  const typeMap = new Map();
  for (const row of typeRows) typeMap.set(`${row.table}.${row.column}`, row);

  crossCheckStructure(pgDoc, sqliteDoc);

  const tableOrder = pgDoc.tables.map((t) => t.name);
  const domainOfTable = assignDomains(tableOrder);

  // type-map 覆盖面：629 列逐列必须有映射（DoD#2 前置）。
  const unmapped = [];
  for (const table of pgDoc.tables) {
    for (const col of table.columns) {
      if (!typeMap.has(`${table.name}.${col.name}`)) unmapped.push(`${table.name}.${col.name}`);
    }
  }
  if (unmapped.length > 0) {
    throw new Error(`type-map.csv 漏列 ${unmapped.length} 个：${unmapped.slice(0, 5).join(", ")}…`);
  }

  // 先把 model 算出来，两个方言共用（保证 TS 树与 model 同源）。
  const sqliteByName = new Map(sqliteDoc.tables.map((t) => [t.name, t]));
  const modelTables = pgDoc.tables.map((t) => toModelTable(t, sqliteByName.get(t.name), typeMap));

  const stats = {
    tables: pgDoc.tables.length,
    columns: modelTables.reduce((n, t) => n + t.columns.length, 0),
    metadataIndexes: modelTables.reduce((n, t) => n + t.indexes.length, 0),
    uniqueIndexes: modelTables.reduce((n, t) => n + t.indexes.filter((i) => i.unique).length, 0),
    partialIndexes: modelTables.reduce((n, t) => n + t.indexes.filter((i) => i.where).length, 0),
    uniqueConstraints: modelTables.reduce((n, t) => n + t.uniqueConstraints.length, 0),
    foreignKeys: modelTables.reduce((n, t) => n + t.foreignKeys.length, 0),
    namedForeignKeys: modelTables.reduce(
      (n, t) => n + t.foreignKeys.filter((f) => f.name).length,
      0
    ),
    primaryKeys: modelTables.length,
    rawIndexes: pgDoc.raw_indexes.length,
    hnswIndexes: pgDoc.raw_indexes.filter((i) => i.method === "hnsw").length,
    extensions: pgDoc.extensions.length,
    sqliteDialectOnlyObjects: sqliteDoc.dialect_only.length,
    sqliteVirtualTables: sqliteDoc.dialect_only.filter((o) => o.kind === "virtual_table").length,
    sqliteShadowTables: sqliteDoc.dialect_only.filter((o) => o.kind === "shadow_table").length,
    sqliteTriggers: sqliteDoc.dialect_only.filter((o) => o.kind === "trigger").length,
    domainGroups: Object.keys(DOMAINS).length,
  };
  const indexObjectsTotal = {
    pg: stats.metadataIndexes + stats.rawIndexes,
    sqlite: stats.metadataIndexes,
  };

  const files = [];
  for (const [domain, tableNames] of Object.entries(DOMAINS)) {
    const tables = tableNames.map((n) => pgDoc.tables.find((t) => t.name === n));
    files.push(renderDomain("pg", domain, tables, typeMap));
    files.push(renderDomain("sqlite", domain, tables, typeMap));
  }
  files.push(renderPgTypes());
  files.push(renderDialectIndex("pg", tableOrder, domainOfTable));
  files.push(renderDialectIndex("sqlite", tableOrder, domainOfTable));
  files.push(renderSchemaIndex());
  files.push(renderModel(version, modelTables, pgDoc, sqliteDoc, stats, indexObjectsTotal));

  if (checkOnly) {
    let drift = 0;
    for (const file of files) {
      const abs = path.join(REPO, file.rel);
      if (!fs.existsSync(abs)) {
        console.error(`x 缺失产物 ${file.rel}`);
        drift += 1;
        continue;
      }
      if (fs.readFileSync(abs, "utf8") !== file.text) {
        console.error(`x 产物与生成结果不一致（需重跑生成器）：${file.rel}`);
        drift += 1;
      }
    }
    console.log(
      drift > 0
        ? `\n--check 结论：DRIFT(${drift})`
        : "\n--check 结论：OK（全部产物与生成结果逐字节一致）"
    );
    if (drift > 0) process.exit(1);
    return;
  }

  for (const file of files) {
    const abs = path.join(REPO, file.rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, file.text, "utf8");
  }

  const report = {
    generated_by: "scripts/gen-drizzle-schema.mjs",
    schema_version: version,
    oracle: {
      pg: rel(PATHS.pg),
      sqlite: rel(PATHS.sqlite),
      type_map: rel(PATHS.typeMap),
    },
    counts: stats,
    index_objects_total: indexObjectsTotal,
    domain_groups: Object.fromEntries(Object.entries(DOMAINS).map(([k, v]) => [k, v.length])),
    files: files.map((f) => ({
      path: f.rel,
      bytes: Buffer.byteLength(f.text, "utf8"),
      sha256: createHash("sha256").update(f.text, "utf8").digest("hex"),
    })),
  };
  fs.mkdirSync(path.dirname(PATHS.report), { recursive: true });
  fs.writeFileSync(PATHS.report, `${JSON.stringify(report, null, 2)}\n`, "utf8");

  console.log("=".repeat(78));
  console.log("gen-drizzle-schema · 实跑输出");
  console.log("=".repeat(78));
  console.log(`oracle 结构面          : ${rel(PATHS.pg)} (+ ${rel(PATHS.sqlite)} 交叉校验)`);
  console.log(`oracle 类型面          : ${rel(PATHS.typeMap)}`);
  console.log(`schema_version         : ${version}`);
  console.log(`表                     : ${stats.tables}（领域分组 ${stats.domainGroups} 个）`);
  console.log(`列                     : ${stats.columns}`);
  console.log(
    `metadata 索引          : ${stats.metadataIndexes}（unique ${stats.uniqueIndexes} / partial ${stats.partialIndexes}）`
  );
  console.log(`unique 约束            : ${stats.uniqueConstraints}`);
  console.log(`外键                   : ${stats.foreignKeys}（具名 ${stats.namedForeignKeys}）`);
  console.log(`raw 索引               : ${stats.rawIndexes}（其中 hnsw ${stats.hnswIndexes}）`);
  console.log(`索引对象合计           : PG ${indexObjectsTotal.pg} / SQLite ${indexObjectsTotal.sqlite}`);
  console.log(`PG 扩展                : ${stats.extensions}`);
  console.log(
    `SQLite 专属对象        : ${stats.sqliteDialectOnlyObjects}（虚表 ${stats.sqliteVirtualTables} / 影子表 ${stats.sqliteShadowTables} / 触发器 ${stats.sqliteTriggers}）`
  );
  console.log(`写入文件数             : ${files.length}`);
  console.log(`report                 : ${rel(PATHS.report)}`);
}

function rel(abs) {
  return path.relative(REPO, abs).replace(/\\/g, "/");
}

/** 双档结构面交叉校验：除类型与默认值外，一切必须一致。 */
function crossCheckStructure(pgDoc, sqliteDoc) {
  const diff = [];
  if (pgDoc.tables.map((t) => t.name).join(",") !== sqliteDoc.tables.map((t) => t.name).join(",")) {
    diff.push("表名集合/顺序不一致");
  }
  const sqliteByName = new Map(sqliteDoc.tables.map((t) => [t.name, t]));
  for (const table of pgDoc.tables) {
    const other = sqliteByName.get(table.name);
    if (!other) {
      diff.push(`SQLite 缺表 ${table.name}`);
      continue;
    }
    if (table.columns.map((c) => c.name).join(",") !== other.columns.map((c) => c.name).join(",")) {
      diff.push(`列集合不一致：${table.name}`);
    }
    if (
      table.columns.map((c) => `${c.name}:${c.nullable}`).join(",") !==
      other.columns.map((c) => `${c.name}:${c.nullable}`).join(",")
    ) {
      diff.push(`可空性不一致：${table.name}`);
    }
    if (JSON.stringify(table.indexes) !== JSON.stringify(other.indexes)) {
      diff.push(`索引不一致：${table.name}`);
    }
    if (JSON.stringify(table.foreign_keys) !== JSON.stringify(other.foreign_keys)) {
      diff.push(`外键不一致：${table.name}`);
    }
    if (JSON.stringify(table.unique_constraints) !== JSON.stringify(other.unique_constraints)) {
      diff.push(`唯一约束不一致：${table.name}`);
    }
    if (JSON.stringify(table.primary_key) !== JSON.stringify(other.primary_key)) {
      diff.push(`主键不一致：${table.name}`);
    }
  }
  if (diff.length > 0) {
    throw new Error(`双档结构面交叉校验失败：\n  - ${diff.join("\n  - ")}`);
  }
}

/** 领域分组必须精确覆盖 oracle 的 61 张表（不重不漏）。 */
function assignDomains(tableOrder) {
  const assigned = Object.values(DOMAINS).flat();
  const missing = tableOrder.filter((n) => !assigned.includes(n));
  const extra = assigned.filter((n) => !tableOrder.includes(n));
  if (missing.length || extra.length || new Set(assigned).size !== assigned.length) {
    throw new Error(
      `领域分组与 oracle 表集合不符：缺=${JSON.stringify(missing)} 多=${JSON.stringify(
        extra
      )} 重复=${assigned.length - new Set(assigned).size}`
    );
  }
  const map = new Map();
  for (const [domain, names] of Object.entries(DOMAINS)) {
    for (const name of names) map.set(name, domain);
  }
  return map;
}

function toModelTable(pgTable, sqliteTable, typeMap) {
  return {
    name: pgTable.name,
    primaryKey: pgTable.primary_key,
    columns: pgTable.columns.map((col, i) => {
      const row = typeMap.get(`${pgTable.name}.${col.name}`);
      return {
        name: col.name,
        pgType: row.pg_emit_type,
        sqliteType: row.sqlite_emit_type,
        nullable: col.nullable,
        pgDefault: col.default,
        sqliteDefault: sqliteTable.columns[i].default,
      };
    }),
    indexes: pgTable.indexes.map((i) => ({
      name: i.name,
      columns: i.columns,
      unique: i.unique,
      where: i.where,
    })),
    uniqueConstraints: pgTable.unique_constraints.map((u) => ({
      name: u.name,
      columns: u.columns,
    })),
    foreignKeys: pgTable.foreign_keys.map((f) => ({
      name: f.name,
      columns: f.columns,
      referredTable: f.referred_table,
      referredColumns: f.referred_columns,
      ondelete: f.ondelete,
      onupdate: f.onupdate,
    })),
  };
}

// ---------------------------------------------------------------------------
// 渲染：领域文件
// ---------------------------------------------------------------------------

function renderDomain(dialect, domain, tables, typeMap) {
  let usesSqlHelper = false;
  const isPg = dialect === "pg";
  const tableFn = isPg ? "pgTable" : "sqliteTable";
  const coreImports = new Set([tableFn]);
  const needsLocalTypes = !isPg ? false : false; // 置位处见下
  let usesVector = false;
  const body = [];

  for (const table of tables) {
    const pk = table.primary_key;
    const singlePk = pk.length === 1 ? pk[0] : null;
    const colLines = [];

    for (const col of table.columns) {
      const row = typeMap.get(`${table.name}.${col.name}`);
      const built = isPg
        ? pgBuilder(row.pg_emit_type, col.name)
        : sqliteBuilder(row.sqlite_emit_type, col.name);
      if (built.fromLocalTypes) usesVector = true;
      else for (const imp of built.imports) coreImports.add(imp);
      let expr = built.call;
      if (!col.nullable) expr += ".notNull()";
      if (col.name === singlePk) expr += ".primaryKey()";
      // PG now() ⇔ .defaultNow() 严格等价。
      if (isPg && col.default === "now()") expr += ".defaultNow()";
      // SQLite 侧必须显式发 CURRENT_TIMESTAMP：drizzle 的 insert 会把**未提供的列**
      // 显式写成 null（实测 SQL：values (?, ?, null, …, null, null)），
      // 所以「靠 DDL 的 DEFAULT 兜底」不成立 —— 漏了这句，任何 insert 都会撞
      // NOT NULL constraint failed: <table>.created_at（2026-10-21 实测）。
      // 注意：`col` 来自**契约 PG 档**表对象，默认值字符串只有 "now()" 一种写法；
      // SQLite 档同一列在契约里记作 CURRENT_TIMESTAMP，故这里按 "now()" 判定、
      // 落到 sqlite 侧发 CURRENT_TIMESTAMP。
      if (!isPg && col.default === "now()") {
        usesSqlHelper = true;
        expr += ".default(sql`CURRENT_TIMESTAMP`)";
      }
      colLines.push(`  ${safeKey(col.name)}: ${expr},`);
    }

    // —— 第三参数：索引 / 唯一约束 / 外键 ——
    // extra-config 是**惰性求值**回调，因此互引用（agent↔agent_version、skill↔skill_version、
    // workflow↔workflow_version 三组环）在此安全 —— 这也是 drizzle 官方推荐的写法。
    const extra = [];
    for (const ix of table.indexes) {
      const fn = ix.unique ? "uniqueIndex" : "index";
      coreImports.add(fn);
      const on = ix.columns.map((c) => `t.${c}`).join(", ");
      // partial 索引的 WHERE 用 drizzle 的 `sql` 模板原样搬进来 —— 它是**SQL 片段**，
      // 不是查询构造器，不与「ORM 只在 repositories/」的分层规则冲突（schema/ 本就允许）。
      // 早期版本在这里退化成普通索引 ⇒ 自省看到的 partial 是 0 个，与契约的 1 个对不上。
      if (ix.where) {
        usesSqlHelper = true;
        extra.push(
          `    ${safeKey(ix.name)}: ${fn}(${JSON.stringify(ix.name)}).on(${on}).where(sql\`${ix.where}\`),`
        );
      } else {
        extra.push(`    ${safeKey(ix.name)}: ${fn}(${JSON.stringify(ix.name)}).on(${on}),`);
      }
    }
    for (const uq of table.unique_constraints) {
      coreImports.add("unique");
      const on = uq.columns.map((c) => `t.${c}`).join(", ");
      extra.push(
        `    ${safeKey(uq.name)}: unique(${JSON.stringify(uq.name)}).on(${on}),`
      );
    }
    let seq = 0;
    for (const fk of table.foreign_keys) {
      coreImports.add("foreignKey");
      const key = fk.name ? safeKey(fk.name) : `fk_${table.name}_${seq}`;
      seq += 1;
      const nameArg = fk.name ? `name: ${JSON.stringify(fk.name)}, ` : "";
      const refNs = tables.some((x) => x.name === fk.referred_table)
        ? null
        : `${domainOfTableOf(fk.referred_table)}NS`;
      extra.push(
        `    ${key}: foreignKey({ ${nameArg}columns: [${fk.columns
          .map((c) => `t.${c}`)
          .join(", ")}], foreignColumns: [${fk.referred_columns
          .map((c) => refColumnExpr(table.name, fk.referred_table, c, refNs))
          .join(", ")}] }),`
      );
    }

    // 第三参数必须**显式标注返回类型**：agent↔agent_version / skill↔skill_version /
    // workflow↔workflow_version 三组互引用环上，TS 无法推断 `extra` 的返回类型，
    // 会退化成隐式 any（TS7022 + TS7024，实测 12 条）。惰性求值救不了类型推导，
    // 只有把返回类型钉成 ExtraConfig 才能断环（T1-03 D-03）。
    const extraBlock = extra.length > 0 ? `, (t): ExtraConfig => ({\n${extra.join("\n")}\n  })\n` : "";
    body.push(
      `export const ${table.name} = ${tableFn}("${table.name}", {\n${colLines.join(
        "\n"
      )}\n}${extraBlock});\n`
    );
  }

  // —— import 段 ——
  const sameFile = new Set(tables.map((t) => t.name));
  const externalRefs = new Map(); // refTable -> domain file
  for (const table of tables) {
    for (const fk of table.foreign_keys) {
      if (!sameFile.has(fk.referred_table)) {
        externalRefs.set(fk.referred_table, domainOfTableOf(fk.referred_table));
      }
    }
  }
  const lines = [];
  lines.push("// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**；改 oracle 后重跑生成器。");
  lines.push(
    `// oracle ①: contracts/schema.v0018.${dialect}.normalized.json（schema v0018，结构权威）`
  );
  lines.push("// oracle ②: contracts/db/type-map.csv（列类型权威，禁手填）");
  lines.push(`// 领域：${domain} · 表数 ${tables.length}`);
  lines.push("");
  if (body.some((chunk) => chunk.includes("): ExtraConfig =>"))) {
    coreImports.add("type ForeignKeyBuilder");
    coreImports.add("type IndexBuilder");
    coreImports.add("type UniqueConstraintBuilder");
  }
  lines.push(
    `import { ${[...coreImports].sort().join(", ")} } from "drizzle-orm/${
      isPg ? "pg-core" : "sqlite-core"
    }";`
  );
  if (body.some((chunk) => chunk.includes("): ExtraConfig =>"))) {
    lines.push("");
    lines.push("/** 第三参数返回类型：显式钉死以断开互引用表的类型环（见 T1-03 D-03）。 */");
    lines.push(
      "type ExtraConfig = Record<string, ForeignKeyBuilder | IndexBuilder | UniqueConstraintBuilder>;"
    );
  }
  if (usesSqlHelper) lines.push(`import { sql } from "drizzle-orm";`);
  if (usesVector) lines.push(`import { vector1536 } from "./_types.js";`);
  const externalDomains = [...new Set([...externalRefs.values()])].sort();
  for (const d of externalDomains) lines.push(`import * as ${d}NS from "./${d}.js";`);
  lines.push("");
  lines.push(...body);

  return {
    rel: rel(path.join(isPg ? PATHS.pgDir : PATHS.sqliteDir, `${domain}.ts`)),
    text: `${lines.join("\n")}`,
  };
}

function domainOfTableOf(name) {
  for (const [domain, names] of Object.entries(DOMAINS)) {
    if (names.includes(name)) return domain;
  }
  throw new Error(`表 ${name} 未登记领域`);
}

function renderPgTypes() {
  const text = `// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**。
// pgvector 的 \`vector(1536)\` 无 drizzle 内建列类型，故用 customType **精确**发出该类型串。
//
// 🔴 ORM 编译**不会**自己产生 hnsw 索引（旧线已知缺陷）。那 2 个 hnsw 由 model.ts 的
//    PG_RAW_INDEXES 原样搬运，并由 scripts/check_drizzle_parity.py 显式断言「恰好 2 个」。
import { customType } from "drizzle-orm/pg-core";

/** \`vector(1536)\` —— emit 原文见 contracts/db/type-map.csv 的 \`VectorType()\` 行。 */
export const vector1536 = customType<{ data: number[]; driverData: string }>({
  dataType() {
    return "vector(1536)";
  },
});
`;
  return { rel: rel(path.join(PATHS.pgDir, "_types.ts")), text };
}

function renderDialectIndex(dialect, tableOrder, domainOfTable) {
  const isPg = dialect === "pg";
  const tag = isPg ? "PG" : "SQLITE";
  const lines = [];
  lines.push("// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**。");
  lines.push(`// ${isPg ? "PostgreSQL" : "SQLite"} 档汇总：${tableOrder.length} 张表。`);
  lines.push("");
  for (const domain of Object.keys(DOMAINS)) lines.push(`export * from "./${domain}.js";`);
  if (isPg) lines.push(`export * from "./_types.js";`);
  lines.push("");
  lines.push(`import type { Table } from "drizzle-orm";`);
  for (const domain of Object.keys(DOMAINS)) lines.push(`import * as ${domain}NS from "./${domain}.js";`);
  lines.push("");
  lines.push(`/** 该方言下全部表对象（便于按名取用 / drizzle(db, schema)）。 */`);
  lines.push(`export const ALL_${tag}_TABLES: Record<string, Table> = {`);
  for (const name of tableOrder) {
    lines.push(`  ${JSON.stringify(name)}: ${domainOfTable.get(name)}NS.${name},`);
  }
  lines.push("};");
  lines.push("");
  lines.push(`export const ${tag}_TABLE_COUNT = ${tableOrder.length};`);
  lines.push("");
  return { rel: rel(path.join(isPg ? PATHS.pgDir : PATHS.sqliteDir, "index.ts")), text: `${lines.join("\n")}` };
}

function renderSchemaIndex() {
  const text = `// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**。
// 双档出口：PG 树与 SQLite 树**并列**，两棵树互不 import，避免方言串味。
export * as pg from "./pg/index.js";
export * as sqlite from "./sqlite/index.js";
export * from "./model.js";
`;
  return { rel: rel(path.join(PATHS.schemaDir, "index.ts")), text };
}

function renderModel(version, modelTables, pgDoc, sqliteDoc, stats, indexObjectsTotal) {
  const j = (v) => JSON.stringify(v);
  const lines = [];
  lines.push("// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**。");
  lines.push("// scripts/gen-ddl.ts 的**唯一输入**：与 pg/ sqlite/ 下的 TS schema 文件由同一次");
  lines.push("// 脚本运行产出 ⇒ 「TS schema → DDL」链条内部不可能漂移。");
  lines.push("");
  lines.push(`export const SCHEMA_VERSION = ${j(version)};`);
  lines.push("");
  lines.push("export interface ModelColumn {");
  for (const [field, type] of [
    ["name", "string"],
    ["pgType", "string"],
    ["sqliteType", "string"],
    ["nullable", "boolean"],
    ["pgDefault", "string | null"],
    ["sqliteDefault", "string | null"],
  ]) {
    lines.push(`  ${field}: ${type};`);
  }
  lines.push("}");
  lines.push("");
  lines.push("export interface ModelIndex {");
  for (const [field, type] of [
    ["name", "string"],
    ["columns", "string[]"],
    ["unique", "boolean"],
    ["where", "string | null"],
  ]) {
    lines.push(`  ${field}: ${type};`);
  }
  lines.push("}");
  lines.push("");
  lines.push("export interface ModelUniqueConstraint {");
  lines.push("  name: string;");
  lines.push("  columns: string[];");
  lines.push("}");
  lines.push("");
  lines.push("export interface ModelForeignKey {");
  for (const [field, type] of [
    ["name", "string | null"],
    ["columns", "string[]"],
    ["referredTable", "string"],
    ["referredColumns", "string[]"],
    ["ondelete", "string | null"],
    ["onupdate", "string | null"],
  ]) {
    lines.push(`  ${field}: ${type};`);
  }
  lines.push("}");
  lines.push("");
  lines.push("export interface ModelTable {");
  for (const [field, type] of [
    ["name", "string"],
    ["primaryKey", "string[]"],
    ["columns", "ModelColumn[]"],
    ["indexes", "ModelIndex[]"],
    ["uniqueConstraints", "ModelUniqueConstraint[]"],
    ["foreignKeys", "ModelForeignKey[]"],
  ]) {
    lines.push(`  ${field}: ${type};`);
  }
  lines.push("}");
  lines.push("");
  lines.push("export interface ModelRawIndex {");
  for (const [field, type] of [
    ["name", "string"],
    ["table", "string"],
    ["method", "string"],
    ["indexedColumn", "string"],
    ["operatorClass", "string"],
    ["options", "Record<string, string>"],
    ["sql", "string"],
    ["source", "string"],
  ]) {
    lines.push(`  ${field}: ${type};`);
  }
  lines.push("}");
  lines.push("");
  lines.push("export interface ModelExtension {");
  lines.push("  name: string;");
  lines.push("  sql: string;");
  lines.push("  sources: string[];");
  lines.push("}");
  lines.push("");
  lines.push("export interface ModelDialectOnly {");
  for (const [field, type] of [
    ["kind", "string"],
    ["name", "string"],
    ["table", "string"],
    ["sql", "string"],
    ["source", "string"],
  ]) {
    lines.push(`  ${field}: ${type};`);
  }
  lines.push("}");
  lines.push("");
  lines.push("/** 61 张表的完整结构（表序＝冻结序＝表名字典序）。 */");
  lines.push("export const TABLES: readonly ModelTable[] = [");
  for (const t of modelTables) {
    lines.push("  {");
    lines.push(`    name: ${j(t.name)},`);
    lines.push(`    primaryKey: ${j(t.primaryKey)},`);
    lines.push("    columns: [");
    for (const c of t.columns) {
      lines.push(
        `      { name: ${j(c.name)}, pgType: ${j(c.pgType)}, sqliteType: ${j(
          c.sqliteType
        )}, nullable: ${c.nullable}, pgDefault: ${
          c.pgDefault === null ? "null" : j(c.pgDefault)
        }, sqliteDefault: ${c.sqliteDefault === null ? "null" : j(c.sqliteDefault)} },`
      );
    }
    lines.push("    ],");
    lines.push("    indexes: [");
    for (const i of t.indexes) {
      lines.push(
        `      { name: ${j(i.name)}, columns: ${j(i.columns)}, unique: ${i.unique}, where: ${
          i.where === null ? "null" : j(i.where)
        } },`
      );
    }
    lines.push("    ],");
    lines.push("    uniqueConstraints: [");
    for (const u of t.uniqueConstraints) {
      lines.push(`      { name: ${j(u.name)}, columns: ${j(u.columns)} },`);
    }
    lines.push("    ],");
    lines.push("    foreignKeys: [");
    for (const f of t.foreignKeys) {
      lines.push(
        `      { name: ${f.name === null ? "null" : j(f.name)}, columns: ${j(
          f.columns
        )}, referredTable: ${j(f.referredTable)}, referredColumns: ${j(
          f.referredColumns
        )}, ondelete: ${f.ondelete === null ? "null" : j(f.ondelete)}, onupdate: ${
          f.onupdate === null ? "null" : j(f.onupdate)
        } },`
      );
    }
    lines.push("    ],");
    lines.push("  },");
  }
  lines.push("];");
  lines.push("");
  lines.push("/** PG raw 索引（源②：迁移链 raw DDL）—— **ORM 编译不出来**，必须显式搬运。 */");
  lines.push("export const PG_RAW_INDEXES: readonly ModelRawIndex[] = [");
  for (const raw of pgDoc.raw_indexes) {
    lines.push("  {");
    lines.push(`    name: ${j(raw.name)},`);
    lines.push(`    table: ${j(raw.table)},`);
    lines.push(`    method: ${j(raw.method)},`);
    lines.push(`    indexedColumn: ${j(raw.indexed_column)},`);
    lines.push(`    operatorClass: ${j(raw.operator_class)},`);
    lines.push(`    options: ${j(raw.options)},`);
    lines.push(`    sql: ${j(raw.sql)},`);
    lines.push(`    source: ${j(raw.source)},`);
    lines.push("  },");
  }
  lines.push("];");
  lines.push("");
  lines.push("/** PG 扩展（源②：迁移 0013/0014 各写一次同一条幂等语句，此处保留一条）。 */");
  lines.push("export const PG_EXTENSIONS: readonly ModelExtension[] = [");
  for (const ext of pgDoc.extensions) {
    lines.push("  {");
    lines.push(`    name: ${j(ext.name)},`);
    lines.push(`    sql: ${j(ext.sql)},`);
    lines.push(`    sources: ${j(ext.sources)},`);
    lines.push("  },");
  }
  lines.push("];");
  lines.push("");
  lines.push("/** SQLite 专属对象（源③）：FTS5 虚表 1 + 影子表 4 + 同步触发器 3 = 8。 */");
  lines.push("export const SQLITE_DIALECT_ONLY: readonly ModelDialectOnly[] = [");
  for (const obj of sqliteDoc.dialect_only) {
    lines.push("  {");
    lines.push(`    kind: ${j(obj.kind)},`);
    lines.push(`    name: ${j(obj.name)},`);
    lines.push(`    table: ${j(obj.table)},`);
    lines.push(`    sql: ${j(obj.sql)},`);
    lines.push(`    source: ${j(obj.source)},`);
    lines.push("  },");
  }
  lines.push("];");
  lines.push("");
  lines.push("/** 实跑计数（由生成器输出，**禁止手填**）。 */");
  lines.push(`export const GENERATED_COUNTS = ${j(stats)};`);
  lines.push("");
  lines.push("/** PG/SQLite 两侧的索引对象合计（PG = metadata + raw hnsw 2）。 */");
  lines.push(`export const INDEX_OBJECTS_TOTAL = ${j(indexObjectsTotal)};`);
  lines.push("");
  return { rel: rel(path.join(PATHS.schemaDir, "model.ts")), text: `${lines.join("\n")}` };
}

main(process.argv.slice(2));
