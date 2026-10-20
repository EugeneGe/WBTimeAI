#!/usr/bin/env node
/**
 * T1-07 · 61 表 ×4 操作冒烟（insert / select / update / soft-delete）
 *
 * 为什么要有这个脚本
 * ------------------
 * `check_drizzle_parity.py` 只证明「61 张表的**结构**在 TS / 契约 / DDL 三处一致」——
 * 它是静态比对，一行 DML 都没跑过。结构对而 DML 跑不通的典型死法：
 *   * NOT NULL 列没默认值，任何业务 insert 都必然炸；
 *   * 主键类型与回读条件不匹配（CHAR(36) 存成 int）；
 *   * FTS5 触发器把基表 insert 带崩。
 * 所以这里对**每一张表**真跑一遍 CRUD，三态记账（通过 / 失败 / 不适用）。
 *
 * 环境
 * ----
 * 本机**没有 Visual Studio**，`better-sqlite3` / `sqlite3` 等原生模块装不上。
 * 唯一可用的 SQLite 是 Node 22 内置 `node:sqlite`（会打 ExperimentalWarning，属预期）：
 *     node --experimental-sqlite scripts/smoke_tables.mjs
 *
 * 纪律
 * ----
 * * **空集合必红**（K-11 哑真防范）：探测到的表数 < 61 直接 INVALID(EMPTY) 退出 9，
 *   绝不把「一张表都没建出来」报告成 0 失败。
 * * **N/A 不是通过**：无软删列的表记 N/A 单独计数，不并入 soft_delete_ok。
 * * **环境不支持不是通过**：FTS5 类对象建不出来时记 SKIPPED(环境不支持) 单独计数。
 * * `--self-test` 用 5 组反例证明「这个脚本真的会红」。
 *
 * 退出码：0 全绿 / 1 有失败 / 2 用法或 DDL 不可加载 / 9 自检失败（含 INVALID(EMPTY)）
 */

import { readFileSync, existsSync, writeFileSync, mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve, relative } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");

/** 冻结契约表数（contracts/schema.v0018.*.sql 与 TS schema 均为 61）。 */
const EXPECTED_TABLES = 61;

/** 软删列探测候选（本项目当前**一个都没有**，见施工记录 T1-07 §5）。 */
const SOFT_DELETE_CANDIDATES = [
  "deleted_at",
  "deleted_on",
  "deleted",
  "is_deleted",
  "deleted_flag",
  "archived_at",
  "removed_at",
];

const EXIT = { PASS: 0, FAIL: 1, USAGE: 2, SELFTEST: 9 };

/** 故障注入（仅供 --self-test 使用；生产路径不传即完全不生效）。 */
const FAULTS = new Set(["empty", "few-tables", "insert-fail", "update-noop"]);

// ---------------------------------------------------------------------------
// DDL 加载与语句切分
// ---------------------------------------------------------------------------

function pickDdlPath(explicit) {
  if (explicit) return resolve(ROOT, explicit);
  const candidates = ["output/ddl.sqlite.sql", "contracts/schema.v0018.sqlite.sql"];
  for (const c of candidates) {
    const p = resolve(ROOT, c);
    if (existsSync(p)) return p;
  }
  return null;
}

/**
 * 按语句切分 DDL。
 *
 * 不能简单 `split(';')`：`CREATE TRIGGER ... BEGIN INSERT ...; UPDATE ...; END;` 的
 * 触发器体内部就有分号，粗暴切分会把一条触发器切成三条废语句。
 * 这里按「行尾分号」判界，且在触发器体内只有单独一行 `END;` 才算结束。
 */
function splitStatements(sql) {
  const out = [];
  let buf = [];
  let inTrigger = false;
  for (const line of sql.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed === "" || trimmed.startsWith("--")) continue;
    buf.push(line.trimEnd());
    if (/^CREATE\s+(TEMP\s+|TEMPORARY\s+)?TRIGGER\b/i.test(trimmed)) inTrigger = true;
    if (trimmed.endsWith(";")) {
      // 触发器体内部语句也以 `;` 结尾；只有「整行末尾就是 END;」才是真正的语句边界。
      // 单行触发器 `CREATE TRIGGER x ... BEGIN ...; END;` 同样命中这个判据。
      if (inTrigger && !/\bEND\s*;$/i.test(trimmed)) continue;
      out.push(buf.join("\n").trim());
      buf = [];
      inTrigger = false;
    }
  }
  if (buf.length > 0) out.push(buf.join("\n").trim());
  return out;
}

function classify(stmt) {
  if (/^CREATE\s+VIRTUAL\s+TABLE\b/i.test(stmt)) return "virtual";
  if (/^CREATE\s+(TEMP\s+|TEMPORARY\s+)?TABLE\b/i.test(stmt)) return "table";
  if (/^CREATE\s+(UNIQUE\s+)?INDEX\b/i.test(stmt)) return "index";
  if (/^CREATE\s+(TEMP\s+|TEMPORARY\s+)?TRIGGER\b/i.test(stmt)) return "trigger";
  return "other";
}

function objectName(stmt) {
  const m = stmt.match(
    /^CREATE\s+(?:VIRTUAL\s+)?(?:UNIQUE\s+)?(?:TEMP\s+|TEMPORARY\s+)?(?:TABLE|INDEX|TRIGGER)\s+(?:IF\s+NOT\s+EXISTS\s+)?["'`[]?([\w.]+)/i,
  );
  return m ? m[1] : "(unnamed)";
}

/** 索引归属表（`CREATE INDEX x ON t (...)`），用于 few-tables 注入时裁掉孤儿索引。 */
function indexTarget(stmt) {
  const m = stmt.match(/\bON\s+["'`[]?([\w.]+)/i);
  return m ? m[1] : null;
}

// ---------------------------------------------------------------------------
// 造值：按真实列类型生成最小合法值（不硬编码任何列名）
// ---------------------------------------------------------------------------

function affinityOf(type) {
  const t = String(type ?? "").toUpperCase();
  if (/\bBOOL/.test(t)) return "bool";
  if (/INT/.test(t)) return "int";
  if (/DATE|TIME/.test(t)) return "datetime";
  if (/BLOB/.test(t)) return "blob";
  if (/REAL|FLOA|DOUB|NUMERIC|DECIMAL/.test(t)) return "real";
  return "text"; // CHAR / VARCHAR / TEXT / CLOB / UUID / JSON
}

let seq = 0;
function uuidLike() {
  seq += 1;
  const hex = seq.toString(16).padStart(12, "0");
  return `00000000-0000-4000-8000-${hex}`;
}

function valueFor(col, phase) {
  const aff = affinityOf(col.type);
  const isUuid = /CHAR\s*\(\s*36\s*\)|UUID/i.test(String(col.type ?? ""));
  switch (aff) {
    case "int":
      return phase === "insert" ? 7 : 8;
    case "bool":
      return phase === "insert" ? 1 : 0;
    case "real":
      return phase === "insert" ? 1.5 : 2.5;
    case "blob":
      return Buffer.from(phase === "insert" ? "smoke" : "smoke2");
    case "datetime":
      return phase === "insert" ? "2026-10-21 00:00:00" : "2026-10-21 01:02:03";
    default:
      if (isUuid) return uuidLike();
      return phase === "insert" ? "smoke" : "smoke_updated";
  }
}

function sameValue(a, b) {
  if (a instanceof Uint8Array || b instanceof Uint8Array) {
    const ba = Buffer.from(a ?? []);
    const bb = Buffer.from(b ?? []);
    return ba.equals(bb);
  }
  if (typeof a === "number" || typeof b === "number") return Number(a) === Number(b);
  return a === b;
}

function q(ident) {
  return `"${String(ident).replace(/"/g, '""')}"`;
}

/** 选一个可更新的非主键列：优先可空 TEXT，保证「改完一定合法」。 */
function pickUpdateColumn(info, pkNames) {
  const usable = info.filter((c) => !pkNames.includes(c.name));
  if (usable.length === 0) return null;
  const soft = new Set(SOFT_DELETE_CANDIDATES);
  const notSoft = usable.filter((c) => !soft.has(c.name.toLowerCase()));
  const pool = notSoft.length > 0 ? notSoft : usable;
  const nullableText = pool.find((c) => c.notnull === 0 && affinityOf(c.type) === "text");
  if (nullableText) return nullableText;
  const nullable = pool.find((c) => c.notnull === 0);
  if (nullable) return nullable;
  return pool[0];
}

// ---------------------------------------------------------------------------
// 主体
// ---------------------------------------------------------------------------

function runSmoke({ db, tableNames, fault, log, verbose }) {
  const failures = [];
  const naSoftDelete = [];
  const skippedObjects = [];
  const perTable = [];
  const counts = { insert_ok: 0, select_ok: 0, update_ok: 0, soft_delete_ok: 0 };

  for (const table of tableNames) {
    const info = db.prepare(`PRAGMA table_info(${q(table)})`).all();
    if (info.length === 0) {
      failures.push({ table, op: "introspect", reason: "表未建出（PRAGMA table_info 无列）" });
      continue;
    }
    const pkCols = info.filter((c) => c.pk > 0).sort((a, b) => a.pk - b.pk);
    if (pkCols.length === 0) {
      failures.push({ table, op: "introspect", reason: "无主键，无法做「按主键回读」" });
      continue;
    }
    const pkNames = pkCols.map((c) => c.name);

    // ---- 1) insert：只填「主键 + NOT NULL 且无默认值」的列，其余吃 DDL 默认 ----
    const insCols = [];
    const insVals = [];
    for (const c of info) {
      const needValue = c.pk > 0 || (c.notnull === 1 && c.dflt_value === null);
      if (!needValue) continue;
      insCols.push(c.name);
      insVals.push(valueFor(c, "insert"));
    }
    const pkVals = pkCols.map((c) => insVals[insCols.indexOf(c.name)]);

    const insertSql =
      `INSERT INTO ${q(table)} (${insCols.map(q).join(", ")}) VALUES (${insCols.map(() => "?").join(", ")})`;
    try {
      const r = db.prepare(insertSql).run(...insVals);
      if (r.changes !== 1) throw new Error(`changes=${r.changes}，期望 1`);
      counts.insert_ok += 1;
    } catch (e) {
      failures.push({ table, op: "insert", reason: `${e.message} | sql=${insertSql}` });
      continue; // 后续三步依赖这一行，跳过
    }

    // ---- 2) select：按主键回读，逐列比对刚才写进去的值 ----
    const wherePk = pkCols.map((c) => `${q(c.name)} = ?`).join(" AND ");
    try {
      const rows = db.prepare(`SELECT * FROM ${q(table)} WHERE ${wherePk}`).all(...pkVals);
      if (rows.length !== 1) throw new Error(`回读行数=${rows.length}，期望 1`);
      for (let i = 0; i < insCols.length; i += 1) {
        const got = rows[0][insCols[i]];
        if (!sameValue(got, insVals[i])) {
          throw new Error(`列 ${insCols[i]} 回读=${JSON.stringify(String(got))} 写入=${JSON.stringify(String(insVals[i]))}`);
        }
      }
      counts.select_ok += 1;
    } catch (e) {
      failures.push({ table, op: "select", reason: e.message });
    }

    // ---- 3) update：改一个非主键列，断言 changes=1 且值已变 ----
    const updCol = pickUpdateColumn(info, pkNames);
    if (updCol === null) {
      failures.push({ table, op: "update", reason: "除主键外无可更新列" });
    } else {
      const newVal = valueFor(updCol, "update");
      const whereForUpdate = fault === "update-noop" ? `${wherePk} AND 0` : wherePk;
      try {
        const r = db.prepare(`UPDATE ${q(table)} SET ${q(updCol.name)} = ? WHERE ${whereForUpdate}`).run(
          newVal,
          ...pkVals,
        );
        if (r.changes !== 1) throw new Error(`changes=${r.changes}，期望 1`);
        const back = db.prepare(`SELECT ${q(updCol.name)} AS v FROM ${q(table)} WHERE ${wherePk}`).all(...pkVals);
        if (back.length !== 1) throw new Error(`更新后回读行数=${back.length}，期望 1`);
        if (!sameValue(back[0].v, newVal)) {
          throw new Error(`更新后 ${updCol.name}=${JSON.stringify(String(back[0].v))}，期望 ${JSON.stringify(String(newVal))}`);
        }
        counts.update_ok += 1;
      } catch (e) {
        failures.push({ table, op: "update", reason: `${e.message} | col=${updCol.name}` });
      }
    }

    // ---- 4) soft-delete：仅对存在软删列的表；没有则 N/A（既不算通过也不算失败）----
    const sdCol = info.find((c) => SOFT_DELETE_CANDIDATES.includes(String(c.name).toLowerCase()));
    if (!sdCol) {
      naSoftDelete.push(table);
    } else {
      const mark = affinityOf(sdCol.type) === "bool" ? 1 : "2026-10-21 01:02:03";
      try {
        const r = db.prepare(`UPDATE ${q(table)} SET ${q(sdCol.name)} = ? WHERE ${wherePk}`).run(mark, ...pkVals);
        if (r.changes !== 1) throw new Error(`changes=${r.changes}，期望 1`);
        const back = db.prepare(`SELECT ${q(sdCol.name)} AS v FROM ${q(table)} WHERE ${wherePk}`).all(...pkVals);
        if (back.length !== 1 || back[0].v === null) throw new Error("软删列未落值");
        counts.soft_delete_ok += 1;
      } catch (e) {
        failures.push({ table, op: "soft-delete", reason: `${e.message} | col=${sdCol.name}` });
      }
    }

    perTable.push({ table, cols: info.length, pk: pkNames.join(","), ok: true });
    if (verbose) log(`  [OK] ${table} (cols=${info.length}, pk=${pkNames.join(",")})`);
  }

  return { failures, naSoftDelete, skippedObjects, counts, perTable };
}

/** 把 DDL 建库，返回建成功的对象清单与失败/跳过清单。 */
function buildDb(DatabaseSync, sql) {
  // FK 强制关闭：61 表之间有 159 条外键且**存在环**（agent.current_version_id → agent_version
  // → agent.id），逐表 CRUD 无法拓扑排序。外键拓扑不在本任务范围（见施工记录 §6 挂账）。
  const db = new DatabaseSync(":memory:", { enableForeignKeyConstraints: false });
  const stmts = splitStatements(sql);
  const built = { table: [], virtual: [], index: [], trigger: [], other: [] };
  const createFailures = [];
  const skipped = [];

  for (const stmt of stmts) {
    const kind = classify(stmt);
    const name = objectName(stmt);
    try {
      db.exec(stmt);
      built[kind].push(name);
    } catch (e) {
      if (kind === "virtual" || kind === "trigger") {
        skipped.push({ name, kind, reason: `SKIPPED(环境不支持): ${e.message}` });
      } else {
        createFailures.push({ name, kind, reason: e.message });
      }
    }
  }
  return { db, stmts, built, createFailures, skipped };
}

function applyFault(sql, fault) {
  if (fault === "empty") return "-- 注入：空 DDL\n";
  if (fault === "few-tables") {
    const stmts = splitStatements(sql);
    const keepTables = new Set();
    const out = [];
    for (const s of stmts) {
      if (classify(s) === "table" && keepTables.size < 3) {
        keepTables.add(objectName(s));
        out.push(s);
      }
    }
    for (const s of stmts) {
      if (classify(s) === "index" && keepTables.has(indexTarget(s))) out.push(s);
    }
    return `${out.join("\n")}\n`;
  }
  if (fault === "insert-fail") {
    // 注入一张 CHECK 必然失败的探针表：insert 应该变红（证明 insert 断言真的在看结果）
    return `${sql}\nCREATE TABLE zz_probe_insert_fail (\n\tid CHAR(36) NOT NULL,\n\tn INTEGER NOT NULL CHECK (n > 1000),\n\tPRIMARY KEY (id)\n);\n`;
  }
  return sql;
}

function parseArgs(argv) {
  const opts = { ddl: null, fault: null, verbose: false, selfTest: false, json: null };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--self-test") opts.selfTest = true;
    else if (a === "--verbose") opts.verbose = true;
    else if (a === "--ddl") opts.ddl = argv[(i += 1)];
    else if (a === "--fault") opts.fault = argv[(i += 1)];
    else if (a === "--json") opts.json = argv[(i += 1)];
    else if (a === "-h" || a === "--help") opts.help = true;
    else return { error: `未知参数: ${a}` };
  }
  if (opts.fault !== null && !FAULTS.has(opts.fault)) return { error: `未知故障注入: ${opts.fault}` };
  return { opts };
}

// ---------------------------------------------------------------------------
// 自检：5 组反例，全部必须按预期变红
// ---------------------------------------------------------------------------

const SELF_TEST_CASES = [
  { name: "baseline 正向（真 DDL 全绿）", args: [], expectExit: EXIT.PASS, expect: /\[smoke\] PASS/ },
  { name: "反例① 全空 DDL ⇒ INVALID", args: ["--fault", "empty"], expectExit: EXIT.SELFTEST, expect: /INVALID\(EMPTY\)[^\n]*tables_total=0/ },
  { name: "反例② 表数不足（3 < 61）⇒ INVALID", args: ["--fault", "few-tables"], expectExit: EXIT.SELFTEST, expect: /INVALID\(EMPTY\)[^\n]*tables_total=3/ },
  { name: "反例③ 某表 insert 失败 ⇒ 退出 1", args: ["--fault", "insert-fail"], expectExit: EXIT.FAIL, expect: /zz_probe_insert_fail[^\n]*insert/ },
  { name: "反例④ update 影响 0 行 ⇒ 退出 1", args: ["--fault", "update-noop"], expectExit: EXIT.FAIL, expect: /op=update[^\n]*changes=0/ },
];

function runSelfTest() {
  console.log("[smoke] self-test（5 组：1 正向 + 4 反例）");
  let bad = 0;
  for (const c of SELF_TEST_CASES) {
    const r = spawnSync(process.execPath, ["--experimental-sqlite", fileURLToPath(import.meta.url), ...c.args], {
      cwd: ROOT,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    });
    const out = `${r.stdout ?? ""}${r.stderr ?? ""}`;
    const exitOk = r.status === c.expectExit;
    const textOk = c.expect.test(out);
    const ok = exitOk && textOk;
    if (!ok) bad += 1;
    console.log(`  [${ok ? "OK" : "FAIL"}] ${c.name} (exit=${r.status}, 期望 ${c.expectExit}; 文本命中=${textOk})`);
    if (!ok) {
      console.log(`        期望文本: ${c.expect}`);
      console.log(`        实际输出尾部: ${out.split(/\r?\n/).slice(-4).join(" | ")}`);
    }
  }
  if (bad === 0) {
    console.log(`[smoke] SELF-TEST PASS (${SELF_TEST_CASES.length}/${SELF_TEST_CASES.length})`);
    return EXIT.PASS;
  }
  console.log(`[smoke] SELF-TEST FAIL (${SELF_TEST_CASES.length - bad}/${SELF_TEST_CASES.length} 通过)`);
  return EXIT.SELFTEST;
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

async function main(argv) {
  const parsed = parseArgs(argv);
  if (parsed.error) {
    console.error(`[smoke] 用法错误: ${parsed.error}`);
    console.error("用法: node --experimental-sqlite scripts/smoke_tables.mjs [--ddl <path>] [--fault <name>] [--verbose] [--json <path>] [--self-test]");
    return EXIT.USAGE;
  }
  const opts = parsed.opts;
  if (opts.help) {
    console.log("用法: node --experimental-sqlite scripts/smoke_tables.mjs [--ddl <path>] [--fault <name>] [--verbose] [--json <path>] [--self-test]");
    console.log(`故障注入（仅自检用）: ${[...FAULTS].join(" | ")}`);
    return EXIT.PASS;
  }
  if (opts.selfTest) return runSelfTest();

  let DatabaseSync;
  try {
    ({ DatabaseSync } = await import("node:sqlite"));
  } catch (e) {
    console.error(`[smoke] FATAL node:sqlite 不可用（${e.message}）—— 请加 --experimental-sqlite 运行`);
    return EXIT.USAGE;
  }

  const ddlPath = pickDdlPath(opts.ddl);
  if (ddlPath === null || !existsSync(ddlPath)) {
    console.error(`[smoke] FATAL 找不到 SQLite DDL（试过 output/ddl.sqlite.sql、contracts/schema.v0018.sqlite.sql）`);
    return EXIT.USAGE;
  }
  let sql = readFileSync(ddlPath, "utf8");
  if (opts.fault) sql = applyFault(sql, opts.fault);

  const log = (s) => console.log(s);
  log(`[smoke] ddl=${relative(ROOT, ddlPath).replace(/\\/g, "/")} (${sql.split(/\r?\n/).length} 行, fault=${opts.fault ?? "none"})`);

  const { db, stmts, built, createFailures, skipped } = buildDb(DatabaseSync, sql);
  const ddlTableNames = [...new Set(stmts.filter((s) => classify(s) === "table").map(objectName))];
  const ddlTriggerNames = stmts.filter((s) => classify(s) === "trigger").map(objectName);
  const ddlVirtualNames = stmts.filter((s) => classify(s) === "virtual").map(objectName);

  const master = db
    .prepare(
      `SELECT
         (SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%') AS tables,
         (SELECT count(*) FROM sqlite_master WHERE type='trigger') AS triggers,
         (SELECT count(*) FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%') AS indexes`,
    )
    .get();

  log(
    `[smoke] DDL 声明: CREATE TABLE=${ddlTableNames.length} virtual=${ddlVirtualNames.length} index=${built.index.length} trigger=${ddlTriggerNames.length}`,
  );
  log(
    `[smoke] 建成对象: table=${master.tables}(含 FTS5 影子表) trigger=${master.triggers} index=${master.indexes} skipped=${skipped.length}`,
  );
  for (const s of skipped) log(`[smoke] ${s.reason} :: ${s.kind} ${s.name}`);

  // 空集合必红（K-11）：表数不足直接 INVALID，绝不报 PASS
  if (ddlTableNames.length < EXPECTED_TABLES) {
    log(`[smoke] INVALID(EMPTY) tables_total=${ddlTableNames.length} expected=${EXPECTED_TABLES} —— 表数不足，拒绝判定`);
    return EXIT.SELFTEST;
  }

  const { failures, naSoftDelete, counts, perTable } = runSmoke({
    db,
    tableNames: ddlTableNames,
    fault: opts.fault,
    log,
    verbose: opts.verbose,
  });
  for (const f of createFailures) failures.push({ table: f.name, op: `ddl:${f.kind}`, reason: f.reason });

  // 交叉校验：DDL 里声明的触发器个数必须与 sqlite_master 里的实际个数一致。
  // 防的是「切分器把 3 条触发器并成 1 条」这类静默吞对象——它曾让本脚本报过 trigger=1 还 PASS。
  if (opts.fault === null && master.triggers !== ddlTriggerNames.length) {
    failures.push({
      table: "(sqlite_master)",
      op: "cross-check",
      reason: `触发器 DDL 声明 ${ddlTriggerNames.length} 个，实际建成 ${master.triggers} 个`,
    });
  }

  const tablesTotal = ddlTableNames.length;
  const skippedTotal = skipped.length;
  log(`[smoke] tables_total=${tablesTotal}`);
  log(`[smoke] insert_ok=${counts.insert_ok}`);
  log(`[smoke] select_ok=${counts.select_ok}`);
  log(`[smoke] update_ok=${counts.update_ok}`);
  log(`[smoke] soft_delete_ok=${counts.soft_delete_ok}`);
  log(`[smoke] soft_delete_na=${naSoftDelete.length}(${naSoftDelete.length === 0 ? "-" : "无软删列，N/A 不计入通过"})`);
  log(`[smoke] skipped=${skippedTotal}(${skippedTotal === 0 ? "-" : "环境不支持，单独计数"})`);
  log(`[smoke] failures=${failures.length}`);
  for (const f of failures) log(`  [FAIL] table=${f.table} op=${f.op} reason=${f.reason}`);

  if (opts.json) {
    const out = resolve(ROOT, opts.json);
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(
      out,
      `${JSON.stringify(
        {
          task: "T1-07",
          generated_at: new Date().toISOString(),
          ddl: relative(ROOT, ddlPath).replace(/\\/g, "/"),
          fault: opts.fault ?? null,
          tables_total: tablesTotal,
          insert_ok: counts.insert_ok,
          select_ok: counts.select_ok,
          update_ok: counts.update_ok,
          soft_delete_ok: counts.soft_delete_ok,
          soft_delete_na: naSoftDelete.length,
          soft_delete_na_tables: naSoftDelete,
          skipped: skippedTotal,
          skipped_objects: skipped,
          failures,
          tables: perTable,
        },
        null,
        2,
      )}\n`,
    );
    log(`[smoke] json=${relative(ROOT, out).replace(/\\/g, "/")}`);
  }

  const allGreen =
    failures.length === 0 &&
    counts.insert_ok === tablesTotal &&
    counts.select_ok === tablesTotal &&
    counts.update_ok === tablesTotal;
  if (allGreen) {
    log("[smoke] PASS");
    return EXIT.PASS;
  }
  log("[smoke] FAIL");
  return EXIT.FAIL;
}

process.exitCode = await main(process.argv.slice(2));
