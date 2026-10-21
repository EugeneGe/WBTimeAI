/**
 * T2-11 · J-11 比对夹具（**不是** test 文件）。
 *
 * 与 `routes-harness.mjs` 的差别只有两点，都是为了"同入参"能成立：
 *  1. **不预注册用户**：19 个 op 里的 `register` / `login` 用的是 py oracle 采到的**原始 body**
 *     （`oracle_second` / `Oracle#12345`），预注册会污染链条；
 *  2. **令牌按侧替换**：oracle 的 `auth:true` 表示"带上本侧链中拿到的 access_token"，
 *     `refresh` 的 body 里是 **py 签的 JWT**（TS 侧无法验证，且验过了也会因为用户不存在而
 *     401）⇒ 比对时替换成 TS 侧链中拿到的 refresh_token。这是**声明式替换**，写在此处与
 *     施工记录里，不是"为了让测试通过而拼数据"：token 值本身是每侧私有、不可比的。
 *
 * 种子只保留"对象存在性"所需的最小集（租户 / 组织 / 供应商），因为 py oracle 起动时
 * 由 `ensure_default` 建了默认租户与组织；不种会让 `list_organizations` 之类从 200 变
 * 500（表里有外键），那就不是在比"同入参同结果"了。
 *
 * 两级比对器（V0.2.0 审计 #4 修复后）
 * --------------------------------
 *  * {@link compareCase} —— 结构级：`{status, code, data 类型, data 键集合}`；
 *  * {@link compareValues} —— **值级**：白名单字段逐值比（`source` / `allowed` / `effect`
 *    / 回显 id …）。V0.2.0 审计 #4 指出旧版只比键集合 ⇒ `source:null` 这种「形状对、
 *    值全错」可以一路绿到底。值白名单见 {@link VALUE_WHITELIST}（逐条注释确定性来源），
 *    显式豁免见 {@link VALUE_EXCLUSIONS}（`reason` 的豁免依据是 R-29 + L-4 裁定）。
 *
 * PG 档的**输入替换**（`PG_INPUT_OVERRIDES`，规模恒为 1 条）
 * ------------------------------------------------------
 * PG 档有且只有一条输入替换：`create_tool_permission.tool_id` 由 oracle 的
 * `"oracle-value"` 换成 UUID。理由：冻结 DDL 里 **PG 的 `resource_permission.resource_id`
 * 是 UUID、SQLite 是同义 CHAR(36)**，而 py 侧 schema 是 `tool_id: str` ⇒ 这是
 * 「契约允许任意 string / DDL 要求 UUID」的**冻结面矛盾（继承自 py，py-on-PG 同会 500）**，
 * 不是 TS 的跨语言分叉。本版禁改 DDL/契约，故只能在测试输入侧开口子：
 *  * **仅** `dialect === "pg"` 生效，SQLite 档逐字不变（仍证明值级等价）；
 *  * 期望值同步改（不做"请求改了、期望没改"的半截替换）；
 *  * 报告里可见（值级列标注 `tool_id=方言替换` + 汇总下方一行说明）；
 *  * 键集合由 {@link PG_INPUT_OVERRIDES_KEYS} 钉死，多一条即红（防止变成掩盖缺陷的橡皮擦）。
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "@wbtime/config";
import { createSqliteDb } from "@wbtime/db/connection";

import { buildApp } from "../../dist/app.js";

/** 仓库根（apps/api/tests/parity → apps/api → apps → 根）。 */
export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");

/** 测试主密钥（≥32 字节）。 */
export const TEST_SECRET = "wbtime-test-secret-key-0123456789abcdef";

/** 主租户（与 T2-07 夹具保持一致）。 */
export const TENANT_ID = "11111111-1111-4111-8111-111111111111";

const DDL = readFileSync(join(ROOT, "output", "ddl.sqlite.sql"), "utf8");

// ─────────────────────────────────────────────────────────────────────────────
// 方言选择（V0.2.0 审计 #2 / FIX-09：PG 档「显式降格 + 一条命令可复跑」）
// ─────────────────────────────────────────────────────────────────────────────
//
// 纪律前提：本版**不得**宣称「PG 已等价」。PG 档默认关闭（`sqlite`），只有在人**显式**
// 给出 `WBTIME_PG_URL` 并切 `WBTIME_PARITY_DIALECT=pg` 时才会尝试；缺 URL 时**抛错**，
// 绝不 skip、绝不静默退回 SQLite（那会把「没验证」伪装成「验证过」）。

/** 方言环境变量名。 */
export const DIALECT_ENV = "WBTIME_PARITY_DIALECT";

/** PG 连接串环境变量名。 */
export const PG_URL_ENV = "WBTIME_PG_URL";

/** 允许 reset（DROP 61 张已知表）的显式授权开关。 */
export const PG_RESET_ENV = "WBTIME_PG_RESET";

/**
 * 专用空库名（红线：**不得**对共享库 `wbtime_ai` 做任何 DDL 级删除）。
 *
 * 该库必须由人工预先建好（`createdb wbtime_ai_parity`）—— 本夹具**不**建库，
 * 也不创建 schema：只做「空库断言 → 灌冻结 DDL → 播种 → 跑用例」。
 */
export const PG_PARITY_DB = "wbtime_ai_parity";

/** 共享库名（**任何** DDL 级删除的红线目标）。 */
export const PG_SHARED_DB = "wbtime_ai";

/**
 * PG 主机环境变量名。
 *
 * **为什么主机必须从环境变量来、而不是写成常量**：主机地址（连同 SSH 用户名）与口令
 * 同属 `docs/*服务器总览.md` 那一类信息，而那份文档是 **gitignored** 的 —— 把地址写进
 * 源码等于绕过那条 gitignore 的意图。所以本文件**不含**任何具体地址：未设置时打印
 * `<PG_HOST>` 占位符，设置了什么就打印什么。
 */
export const PG_HOST_ENV = "WBTIME_PG_HOST";

/** 未配置主机时使用的占位符（保证提示文案仍可整段复制后手工替换）。 */
export const PG_HOST_PLACEHOLDER = "<PG_HOST>";

/**
 * 取本次要展示的 PG 主机。
 *
 * @param {Record<string, string|undefined>} [env] 环境变量表（默认 `process.env`）。
 * @returns {string} `WBTIME_PG_HOST` 的值；未设置时返回 {@link PG_HOST_PLACEHOLDER}。
 */
export function resolvePgHost(env = process.env) {
  const host = String(env[PG_HOST_ENV] ?? "").trim();
  return host === "" ? PG_HOST_PLACEHOLDER : host;
}

/**
 * 起隧道的命令（**不含任何密码 / 凭据 / 具体地址**）。
 *
 * 三个占位符各自由环境变量决定是否替换：
 *   * `<PG_HOST>`   ← `WBTIME_PG_HOST`（未设置则保留占位符）
 *   * `<SSH_USER>` / `<PG_USER>` / `<PG_PASSWORD>` —— **永不**从环境读取后回显，
 *     只提示去 gitignored 的 `docs/*服务器总览.md` / `docs/环境基线.md` §4.1 查。
 *     凭据一旦被打进日志，日志本身就是一次泄漏（见 `docs/施工纪律.md`）。
 *
 * @param {Record<string, string|undefined>} [env] 环境变量表（默认 `process.env`）。
 * @returns {string} 可直接粘贴的命令块（多行）。
 */
export function tunnelCommandHint(env = process.env) {
  const host = resolvePgHost(env);
  return [
    "# PG 只监听远端 127.0.0.1:5432 ⇒ 必须经 SSH 隧道（本地 5433 → 远端 5432）",
    `ssh -N -L 5433:127.0.0.1:5432 <SSH_USER>@${host}`,
    "# <SSH_USER> / <PG_USER> / 口令 / 主机：见 gitignored 的 docs/*服务器总览.md（不入库）",
    `# 主机也可用 ${PG_HOST_ENV} 覆盖（本文件不内置任何地址）`,
    "# 隧道起来后（专用空库，勿用共享库）：",
    `#   export ${PG_URL_ENV}='postgres://<PG_USER>:<PG_PASSWORD>@127.0.0.1:5433/${PG_PARITY_DB}'`,
    `#   export ${DIALECT_ENV}=pg`,
    "#   pnpm test:parity:pg",
  ].join("\n");
}

/**
 * 解析本次运行的方言。
 *
 * @param {Record<string, string|undefined>} [env] 环境变量表（默认 `process.env`）。
 * @returns {"sqlite"|"pg"}
 * @throws {Error} 取值不是 `sqlite` / `pg`（**不**猜、不回落）。
 */
export function resolveDialect(env = process.env) {
  const raw = String(env[DIALECT_ENV] ?? "").trim().toLowerCase();
  if (raw === "" || raw === "sqlite") return "sqlite";
  if (raw === "pg" || raw === "postgres" || raw === "postgresql") return "pg";
  throw new Error(
    `${DIALECT_ENV} 只接受 sqlite / pg，实测 ${JSON.stringify(env[DIALECT_ENV])}`
  );
}

/** 本次运行的方言（模块加载即定，测试名要用它，绿的时候能看出跑的是哪一档）。 */
export const PARITY_DIALECT = resolveDialect();

/**
 * 取 PG 连接串；缺了就直接抛（带隧道命令）。
 *
 * @param {Record<string, string|undefined>} [env] 环境变量表（默认 `process.env`）。
 * @returns {string} 连接串。
 * @throws {Error} 未设置 `WBTIME_PG_URL`。
 */
export function requirePgUrl(env = process.env) {
  const url = String(env[PG_URL_ENV] ?? "").trim();
  if (url === "") {
    throw new Error(
      `dialect=pg 需要 ${PG_URL_ENV}（未设置 ⇒ 无法判定是否等价，**不做** skip、不算绿）\n` +
        tunnelCommandHint()
    );
  }
  return url;
}

/**
 * 从 PG DDL 文本里抽出**已知表名**（`CREATE TABLE <name> (`）。
 *
 * 用于两件事，都必须精确：
 *  1. reset 时**只** DROP 这些表（禁 `DROP SCHEMA public CASCADE` —— 那会连带删掉
 *     别人的对象）；
 *  2. 数量断言（冻结面 61 张），防止正则失配导致"以为只删了几张"。
 *
 * @param {string} sqlText DDL 全文。
 * @returns {string[]} 表名（保持文件顺序、去重）。
 */
export function listDdlTables(sqlText) {
  const names = [];
  const pattern = /^CREATE TABLE\s+(?:IF NOT EXISTS\s+)?"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\(/gim;
  let match = pattern.exec(String(sqlText ?? ""));
  while (match !== null) {
    if (!names.includes(match[1])) names.push(match[1]);
    match = pattern.exec(String(sqlText ?? ""));
  }
  return names;
}

/** 冻结面表数（`contracts/schema.v0018.*.sql` 的 `CREATE TABLE` 计数）。 */
const EXPECTED_TABLE_COUNT = 61;

/** PG 冻结 DDL 的路径（**不改契约**：只读它）。 */
export const PG_DDL_PATH = join(ROOT, "contracts", "schema.v0018.pg.sql");

/**
 * 建一个 PG 连接并把它带进「可安全灌 DDL」的状态。
 *
 * 四道闸（顺序有意义，任何一道不满足都抛，**不**降级）：
 *  1. `current_database()` 必须是名字里含 `parity` 的库（**永不**允许共享库 `wbtime_ai`）；
 *  2. `to_regclass('public.tenant')` 非空 ⇒ 库里已有本 schema ⇒ 拒绝（除非 reset）；
 *  3. `WBTIME_PG_RESET=1` 时才允许 DROP，且**只 DROP DDL 里的已知表**（数量须 = 61）；
 *  4. 共享库 `wbtime_ai` **即使**给了 reset 也拒绝（闸 1 已挡）。
 *
 * 连接句柄走 `@wbtime/db/connection` 的 `createPgDb`（`pg` + drizzle 的唯一装配点），
 * 不在测试里手搓 `new Pool`：否则「生产怎么连」与「测试怎么连」会各说一套。
 * 动态 import 的原因：本文件在 **sqlite 档**不得把 `node:sqlite` 的加载路径当成默认依赖
 * （虽然测试命令恒带 `--experimental-sqlite`，但让依赖按档发生更干净）。
 *
 * @param {string} url PG 连接串。
 * @param {Record<string, string|undefined>} [env] 环境变量表。
 * @returns {Promise<{connection: object, dropped: number}>} `createPgDb` 的句柄与 DROP 表数。
 */
export async function preparePgDatabase(url, env = process.env) {
  const { createPgDb } = await import("@wbtime/db/connection");
  const connection = createPgDb(url);
  const pool = connection.pool;
  const ddlText = readFileSync(PG_DDL_PATH, "utf8");
  const knownTables = listDdlTables(ddlText);
  if (knownTables.length !== EXPECTED_TABLE_COUNT) {
    await connection.close().catch(() => {});
    throw new Error(
      `PG DDL 解析出 ${knownTables.length} 张表，期望 ${EXPECTED_TABLE_COUNT} —— ` +
        "表名正则失配时**不得**继续（否则 reset 会删错范围）"
    );
  }

  let dropped = 0;
  try {
    // ── 闸 1：库名（共享库红线）────────────────────────────────────────────
    const dbRow = await pool.query("SELECT current_database() AS db");
    const database = String(dbRow.rows[0]?.db ?? "");
    if (database === PG_SHARED_DB) {
      throw new Error(
        `拒绝执行：目标是共享库 ${PG_SHARED_DB}。PG 档必须在专用空库 ${PG_PARITY_DB} 上跑` +
          "（红线：绝不对共享库做任何 DDL 级删除）"
      );
    }
    if (!database.includes("parity")) {
      throw new Error(
        `拒绝执行：当前库 ${database} 看起来不是专用 parity 库。` +
          `请用 ${PG_PARITY_DB}（名字须含 "parity"），避免误删他人 schema`
      );
    }

    // ── 闸 2/3：非空则拒绝；reset 只在显式授权下按**已知表**删除 ─────────
    const regRow = await pool.query("SELECT to_regclass('public.tenant') AS reg");
    const existing = regRow.rows[0]?.reg ?? null;
    if (existing !== null) {
      if (String(env[PG_RESET_ENV] ?? "") !== "1") {
        throw new Error(
          `库 ${database} 已存在 public.tenant（非空库）。` +
            `请改用专用空库 ${PG_PARITY_DB}，` +
            `或用 ${PG_RESET_ENV}=1 显式授权后 DROP ${knownTables.length} 张已知表`
        );
      }
      // 只删本 DDL 的已知表；`CASCADE` 仅用于解外键依赖，**不**涉及 schema。
      // 明令禁止 `DROP SCHEMA public CASCADE`（会带走别人的对象）。
      await pool.query(
        `DROP TABLE IF EXISTS ${knownTables.map((name) => `"${name}"`).join(", ")} CASCADE`
      );
      dropped = knownTables.length;
    }

    // ── 灌冻结 DDL（61 表 + 扩展 + 索引 + 外键）───────────────────────────
    try {
      await pool.query(ddlText);
    } catch (error) {
      throw new Error(
        `灌 PG DDL 失败：${error instanceof Error ? error.message : String(error)}\n` +
          "提示：DDL 首段是 `CREATE EXTENSION IF NOT EXISTS vector` —— 远端必须已装 pgvector" +
          " 且当前用户有权建扩展（见 docs/施工纪律.md 表格第 1 行）"
      );
    }

    const countRow = await pool.query(
      "SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'"
    );
    const tableCount = Number(countRow.rows[0]?.n ?? 0);
    if (tableCount < EXPECTED_TABLE_COUNT) {
      throw new Error(`灌完 DDL 后 public 只有 ${tableCount} 张表，期望 ≥ ${EXPECTED_TABLE_COUNT}`);
    }
  } catch (error) {
    await connection.close().catch(() => {});
    throw error;
  }

  return { connection, dropped };
}

/** 读 py 侧期望值（仓内副本，溯源写在文件里）。 */
export function loadOracle() {
  return JSON.parse(readFileSync(join(ROOT, "apps", "api", "tests", "fixtures", "py-oracle-19ops.json"), "utf8"));
}

/**
 * 把 SQL 文本里的 `?` 占位符**依次**转成 PG 的 `$1..$n`（纯函数，可单测）。
 *
 * 为什么必须有它（dev 服务器 PG 首跑实测缺陷，`code: 42601 syntax error at or near ","`）：
 * `seedTenants` 的 SQL 用的是 `?` 占位符（`node:sqlite` 的写法），而 **PG 只认 `$n`** ——
 * 直接把 `?` 交给 `pool.query` 会在第一个 `VALUES (?, ?, ?, ?)` 处语法错。
 *
 * 为什么不能 `sql.split("?").join("$n")`：`?` 在 SQL 里有三种**不是占位符**的用法，
 * 粗暴替换会把语义改坏（而且改坏后往往还是"能跑"，只是参数错位 —— 那比报错更难查）：
 *
 * | 场景 | 必须跳过 | 例 |
 * |---|---|---|
 * | 单引号字符串 | ✅ | `'a?b'`、`'it''s ?'`（`''` 是转义，不是字符串结束） |
 * | 双引号标识符 | ✅ | `"weird?column"` |
 * | `--` 行注释 / 块注释 | ✅ | `-- ? 不是参数` |
 * | jsonb 运算符 `?|` / `?&` / `?` | ✅ | `config ? 'k'`（PG 的键存在性运算符） |
 *
 * 关于 `?::text`（占位符后接类型转换）：**不做**特殊处理，转成 `$1::text` 才是正确结果 ——
 * 类型转换作用在参数上，不是 `?` 的另一种语法。这也是本函数不"跳过 `::`"的原因。
 *
 * 已知边界（本版不做，写清避免误用）：不建模 `E'...'` 转义字符串与 `$tag$...$tag$` 美元引用；
 * 本仓唯一的调用方是 {@link seedTenants}，其 SQL 只用 `?` 占位符，不涉及上述语法。
 *
 * @param {string} sql 含 `?` 占位符的 SQL 文本。
 * @returns {string} 占位符已替换为 `$1..$n` 的 SQL；字符串/注释/运算符里的 `?` 原样保留。
 */
export function toPgPlaceholders(sql) {
  const text = String(sql ?? "");
  const out = [];
  /** 下一个占位符的序号（从 1 开始，**只**对真正的占位符递增）。 */
  let next = 1;
  /** 扫描状态机：code / single / double / line / block。 */
  let state = "code";

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const following = text[index + 1];

    if (state === "code") {
      if (char === "'") {
        state = "single";
        out.push(char);
        continue;
      }
      if (char === '"') {
        state = "double";
        out.push(char);
        continue;
      }
      if (char === "-" && following === "-") {
        state = "line";
        out.push(char, following);
        index += 1;
        continue;
      }
      if (char === "/" && following === "*") {
        state = "block";
        out.push(char, following);
        index += 1;
        continue;
      }
      if (char === "?") {
        // jsonb 运算符不是占位符：`?|`（任一键存在）/ `?&`（全键存在）。
        // 裸 `?`（键存在运算符）无法在不做语义分析的前提下与占位符区分 ——
        // 本仓的 SQL 不用它；若将来要用，请写成 `jsonb_exists(col, ?)`。
        if (following === "|" || following === "&") {
          out.push(char);
          continue;
        }
        out.push(`$${next}`);
        next += 1;
        continue;
      }
      out.push(char);
      continue;
    }

    if (state === "single") {
      out.push(char);
      if (char === "'") {
        if (following === "'") {
          // `''` 是字符串内的转义单引号，字符串**没有**结束。
          out.push(following);
          index += 1;
          continue;
        }
        state = "code";
      }
      continue;
    }

    if (state === "double") {
      out.push(char);
      if (char === '"') {
        if (following === '"') {
          out.push(following);
          index += 1;
          continue;
        }
        state = "code";
      }
      continue;
    }

    if (state === "line") {
      out.push(char);
      if (char === "\n") state = "code";
      continue;
    }

    // state === "block"
    out.push(char);
    if (char === "*" && following === "/") {
      out.push(following);
      index += 1;
      state = "code";
    }
  }

  return out.join("");
}

/**
 * 播种适配器：把「同步 sqlite `prepare/run`」与「异步 pg `pool.query`」统一成
 * `{ dialect, run(sql, params), exec(sqlText) }`。
 *
 * 为什么需要它：`seedTenants` 原来是 `raw.prepare(..).run(..)`（`node:sqlite` 同步接口），
 * 直接搬不到 PG。抽一层后 **sqlite 路径的行为完全不变**（仍是同一句 SQL、同一个原生
 * 语句对象），把两处**真实**的方言差异挡在适配器里：
 *
 * | 差异 | sqlite | pg | 挡在哪 |
 * |---|---|---|---|
 * | 占位符 | `?` | `$1..$n` | `run()` 里调 {@link toPgPlaceholders} |
 * | 布尔列取值 | `integer`，**必须**传 `1` | `boolean`，**必须**传 `true` | `dialect` 暴露给调用方 |
 *
 * ⚠️ 布尔这一条**不能"顺手统一"**：`node:sqlite` 传 JS `true` 会 `TypeError`（它只收
 * number/string/bigint/null/Uint8Array），而 PG 的 `tenant.is_active` 是 `boolean`，
 * 传 `1` 会类型错。两条档必须各传各的 —— 这正是第二处缺陷的根因。
 *
 * @param {"sqlite"|"pg"} dialect 方言。
 * @param {object} handle sqlite 传 `DatabaseSync`；pg 传 `PgConnection`。
 * @returns {{dialect: "sqlite"|"pg",
 *            run: (sql: string, params?: unknown[]) => Promise<void>,
 *            exec: (sqlText: string) => Promise<void>}}
 */
export function createSeedAdapter(dialect, handle) {
  if (dialect === "sqlite") {
    return {
      dialect: "sqlite",
      async run(sql, params = []) {
        handle.prepare(sql).run(...params);
      },
      async exec(sqlText) {
        handle.exec(sqlText);
      },
    };
  }
  if (dialect === "pg") {
    return {
      dialect: "pg",
      async run(sql, params = []) {
        // 只做「占位符改写」这一件事：参数原样交给驱动，**不做**任何隐式类型转换
        // （那会把"SQL 写错"变成"某天悄悄能跑"）。
        await handle.pool.query(toPgPlaceholders(sql), params);
      },
      async exec(sqlText) {
        await handle.pool.query(sqlText);
      },
    };
  }
  throw new Error(`未知方言：${String(dialect)}（只支持 sqlite / pg）`);
}

/**
 * 播种「对象存在性」所需的最小集：租户 / 组织 / 供应商各一。
 *
 * 双档适配（V0.2.0 审计 #2 / FIX-09）：入参从 `raw`（sqlite 原生句柄）改为
 * {@link createSeedAdapter} 的产物，两条档走**同一份 SQL 文本**（占位符由适配器改写）。
 *
 * 唯一的**取值**差异是 `tenant.is_active`：SQLite 列是 integer ⇒ 传 `1`；
 * PG 列是 boolean ⇒ 传 `true`。两者都**不可**互换（见 {@link createSeedAdapter} 的说明）。
 *
 * @param {{dialect: "sqlite"|"pg", run: Function}} adapter 播种适配器。
 * @returns {Promise<void>}
 * @throws {TypeError} 适配器没暴露 `dialect`（无法决定布尔列取值 ⇒ 宁可当场炸，
 *   也不要在 PG 上悄悄写入错误类型，或在 SQLite 上抛 `TypeError` 后被误读成"夹具坏了"）。
 */
export async function seedTenants(adapter) {
  const dialect = adapter?.dialect;
  if (dialect !== "sqlite" && dialect !== "pg") {
    throw new TypeError(
      `seedTenants 需要带 dialect 的适配器（实测 ${JSON.stringify(dialect)}）；` +
        "请用 createSeedAdapter() 构造 —— 布尔列取值必须按方言决定"
    );
  }
  /** `tenant.is_active` 的方言正确取值（sqlite=integer 1 / pg=boolean true）。 */
  const isActive = dialect === "pg" ? true : 1;

  await adapter.run("INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, ?)", [
    TENANT_ID,
    "租户 A",
    "tenant-a",
    isActive,
  ]);
  await adapter.run("INSERT INTO organization (id, tenant_id, name, slug) VALUES (?, ?, ?, ?)", [
    "1a1a1a1a-0000-4000-8000-00000000000a",
    TENANT_ID,
    "组织 A",
    "org-a",
  ]);
  await adapter.run(
    "INSERT INTO model_provider (id, tenant_id, name, type, endpoint, status, config) " +
      "VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
      "1c1c1c1c-0000-4000-8000-00000000000c",
      TENANT_ID,
      "openai-main",
      "openai",
      "https://api.openai.com/v1",
      "ACTIVE",
      "{}",
    ]
  );
}

/**
 * 建一个"干净但对象齐备"的应用：租户 / 组织 / 供应商各一，**无用户**。
 *
 * 方言由 {@link PARITY_DIALECT}（`WBTIME_PARITY_DIALECT`）决定，也可用
 * `options.dialect` 显式覆盖（供反例用例使用）：
 *
 * | 档 | 连接 | DDL 来源 | 播种 |
 * |---|---|---|---|
 * | `sqlite`（默认） | `createSqliteDb(":memory:")` | `output/ddl.sqlite.sql`（可再生） | 同 SQL |
 * | `pg` | `createPgDb(WBTIME_PG_URL)` | `contracts/schema.v0018.pg.sql`（冻结面，**只读**） | 同 SQL |
 *
 * PG 档会先过 {@link preparePgDatabase} 的四道闸（专用 parity 库 / 非空拒绝 /
 * reset 只删已知表 / 共享库红线），**不会**在别人的库上灌 DDL。
 *
 * @param {{dialect?: "sqlite"|"pg"}} [options]
 * @returns {Promise<{app: object, dialect: string, raw: object|null,
 *                    dropped?: number, close: () => Promise<void>}>}
 */
export async function makeParityApp(options = {}) {
  const dialect = options.dialect ?? PARITY_DIALECT;

  // ── SQLite 档（默认；行为与本版之前**逐字一致**）────────────────────────
  if (dialect === "sqlite") {
    const connection = createSqliteDb(":memory:");
    connection.raw.exec(DDL);
    await seedTenants(createSeedAdapter("sqlite", connection.raw));

    const app = buildApp({
      config: loadConfig({ WBTIME_AI_MODE: "local", WBTIME_AI_SECRET_KEY: TEST_SECRET }),
      enableLogging: false,
      database: connection.db,
      dialect: "sqlite",
      tenantId: TENANT_ID,
    });
    await app.ready();
    return {
      app,
      dialect: "sqlite",
      raw: connection.raw,
      close: async () => {
        await app.close();
        connection.close();
      },
    };
  }

  // ── PG 档（FIX-09：只有显式给 URL 才可能走到这里）─────────────────────
  if (dialect === "pg") {
    const { connection, dropped } = await preparePgDatabase(requirePgUrl(), process.env);
    await seedTenants(createSeedAdapter("pg", connection));

    const app = buildApp({
      config: loadConfig({ WBTIME_AI_MODE: "local", WBTIME_AI_SECRET_KEY: TEST_SECRET }),
      enableLogging: false,
      database: connection.db,
      dialect: "pg",
      tenantId: TENANT_ID,
    });
    await app.ready();
    return {
      app,
      dialect: "pg",
      // PG 档没有 `raw`（`node:sqlite` 的 `DatabaseSync`）；调用方不该按 sqlite 形态用它。
      raw: null,
      dropped,
      close: async () => {
        await app.close();
        await connection.close();
      },
    };
  }

  throw new Error(`未知方言：${String(dialect)}（只支持 sqlite / pg）`);
}

/**
 * 把 oracle 的一条 `operation`（形如 `"GET /api/v1/..."`）拆成 method + path。
 *
 * @param {string} operation 例：`"DELETE /api/v1/models/credentials/{credential_id}"`。
 * @returns {{method: string, path: string}}
 */
export function splitOperation(operation) {
  const [method, path] = operation.split(" ");
  return { method, path };
}

/**
 * 用 `params` 填路径占位符，用 `query` 拼查询串。
 *
 * @param {string} path 含 `{x}` 占位的路径。
 * @param {Record<string,string>|null} params 路径参数。
 * @param {Record<string,string>|null} query 查询参数。
 * @returns 可直接 inject 的 url。
 */
export function buildUrl(path, params, query) {
  let url = path;
  for (const [key, value] of Object.entries(params ?? {})) {
    url = url.replace(`{${key}}`, encodeURIComponent(value));
  }
  if (query !== null && Object.keys(query).length > 0) {
    const search = new URLSearchParams(query).toString();
    url = `${url}?${search}`;
  }
  return url;
}

/**
 * 比较一条 op 的 `{status, code, data 键集合}`。
 *
 * 三条豁免（与判据一致）：`request_id` 值 / 时间戳值 / `id` 值 —— 它们不参与键集合比较，
 * 值更是每侧不同，故只比**键**。
 *
 * @param {object} expected oracle 的 `expected`。
 * @param {object} response `app.inject()` 的返回。
 * @returns {{ok: boolean, diffs: string[], actual: object}}
 */
export function compareCase(expected, response) {
  const diffs = [];
  const body = response.body === "" ? null : JSON.parse(response.body);
  const actual = {
    status: response.statusCode,
    code: body?.code ?? null,
    data_type: body === null ? "none" : Array.isArray(body.data) ? "array" : typeof body.data,
    data_keys:
      body !== null && body.data !== null && typeof body.data === "object" && !Array.isArray(body.data)
        ? Object.keys(body.data).sort()
        : null,
  };

  if (actual.status !== expected.status) {
    diffs.push(`status: 期望 ${expected.status}，实测 ${actual.status}`);
  }
  if (actual.code !== expected.code) {
    diffs.push(`code: 期望 ${String(expected.code)}，实测 ${String(actual.code)}`);
  }
  if (expected.data_type !== actual.data_type) {
    diffs.push(`data 类型: 期望 ${expected.data_type}，实测 ${actual.data_type}`);
  }
  if (expected.data_keys === null) {
    if (actual.data_keys !== null) {
      diffs.push(`data 键: 期望 null（数组/无体），实测 ${JSON.stringify(actual.data_keys)}`);
    }
  } else if (actual.data_keys === null) {
    diffs.push(`data 键: 期望 ${JSON.stringify(expected.data_keys)}，实测 null`);
  } else {
    const expectedKeys = [...expected.data_keys].sort();
    const missing = expectedKeys.filter((key) => !actual.data_keys.includes(key));
    const extra = actual.data_keys.filter((key) => !expectedKeys.includes(key));
    if (missing.length > 0) diffs.push(`data 少键: ${missing.join(", ")}`);
    if (extra.length > 0) diffs.push(`data 多键: ${extra.join(", ")}`);
  }

  return { ok: diffs.length === 0, diffs, actual };
}

// ─────────────────────────────────────────────────────────────────────────────
// 值级比对（FIX-02）：堵住「只比键集合」的放水口
// ─────────────────────────────────────────────────────────────────────────────

/**
 * **值白名单**：这些字段的取值「由代码决定」，因此两侧必须逐值相等。
 *
 * 入选标准只有一条 —— **值的确定性来自代码，而不是来自时刻 / 随机源 / 夹具**：
 * 常量与枚举（`token_type`）、判定式结果（`allowed` / `effect` / `source`）、
 * 入参回显（`capability` / `action` / 路径参数 id）。凡是「每侧本来就不同」的字段
 * （`id` / `request_id` / `created_at` / `tenant_id`）**一律不在此表**，见
 * {@link VALUE_EXCLUSIONS}（那里逐条写明为什么不可比）。
 *
 * 逐条理由（「为何确定性」）：
 *
 * - `capability` —— 回显 querystring `?cap=`；同一请求两侧同值，与时钟无关。
 * - `allowed` —— 判定式 `code ∈ codes ∪ {"*"}` 的输出；两侧种子/成员关系同为「无」。
 * - `effect` —— 契约枚举 `{ALLOW, DENY}`，且由 `decision()` 唯一构造点与 `allowed` 同步。
 * - `source` —— R-29 机器枚举三态（`default_deny` / `explicit_grant` / `wildcard_admin`）；
 *   py oracle 实测 `"source":"default_deny"`，本项就是 FIX-01 的判据。
 * - `token_type` —— 契约常量 `"Bearer"`（RFC 6750），与时钟、密钥无关。
 * - `expires_in` —— access token TTL 常量（配置项），两侧同配置 ⇒ 同整数（非绝对时刻）。
 * - `is_active` —— 注册即 `true`（`user.is_active` 的写入常量），与时刻无关。
 * - `is_superuser` —— 注册即 `false`（同上；提权是另一个 op，本链路没有）。
 * - `key_type` —— 回显请求体的 `key_type`（缺省 `api_key`）。
 * - `action` —— 回显请求体的 `action`（缺省 `EXECUTE`）。
 * - `scope` —— 请求体未给 ⇒ 两侧都落空对象 `{}`。
 * - 回显 id（`organization_id` / `permission_id` / `credential_id` / `provider_id`）——
 *   404 `data` 里回显的是**客户端自己传进来的路径参数**（本链固定
 *   `00000000-0000-4000-8000-000000000000`），不是行数据 ⇒ 与库内容无关，必然相等。
 * - `username` / `email` / `display_name` —— 回显 register body（`oracle_second` /
 *   `oracle2@example.com` / `null`）；同一入参 ⇒ 同一回显。
 * - `agent_id` / `agent_version_id` —— `agent_id` 回显请求体（本链未给 ⇒ `null`）；
 *   `agent_version_id` 恒 `null`（`resource_permission` 无该列，J-1 红线）。
 * - `tool_id` / `provider` / `workspace_id` —— 回显请求体（`oracle-value` / `null`）。
 * - `revoked_at` —— 新建会话未撤销 ⇒ `null`（写入常量，不是时刻）。
 */
export const VALUE_WHITELIST = Object.freeze({
  capability: "回显 query `cap`",
  allowed: "判定式输出（同一判权式 + 同一「无成员关系」前置）",
  effect: "契约枚举，且与 allowed 同步（唯一构造点）",
  source: "R-29 机器枚举三态（py 实测 default_deny）",
  token_type: "契约常量 \"Bearer\"",
  expires_in: "access TTL 配置常量（非绝对时刻）",
  is_active: "注册写入常量 true",
  is_superuser: "注册写入常量 false",
  key_type: "回显请求体（缺省 api_key）",
  action: "回显请求体（缺省 EXECUTE）",
  scope: "请求体未给 ⇒ 空对象 {}",
  organization_id: "回显路径参数（客户端给定）",
  permission_id: "回显路径参数（客户端给定）",
  credential_id: "回显路径参数（客户端给定）",
  provider_id: "回显路径参数（客户端给定）",
  username: "回显 register body",
  email: "回显 register body",
  display_name: "回显 register body（null）",
  agent_id: "回显请求体（未给 ⇒ null）",
  agent_version_id: "恒 null（resource_permission 无该列，J-1）",
  tool_id: "回显请求体",
  provider: "回显请求体",
  workspace_id: "回显请求体（null）",
  revoked_at: "新建会话未撤销 ⇒ null（写入常量）",
});

/**
 * **显式排除表**：这些字段的值**不**参与逐值比对，且每条都必须写清依据。
 *
 * 「显式」是重点：排除必须是一条**有理由的记录**，而不是「白名单里没有它 ⇒ 悄悄不比」。
 * {@link compareValues} 会把「py 有、却既不在白名单也不在本表」的键报进
 * `unaccounted` —— 新增字段若忘记登记，19/19 会当场红，而不是继续静默放水。
 *
 * `reason` 的依据（**不得**按审计报告的建议去对齐它）：
 * R-29 与 L-4 已裁定「`reason` 值不逐字对齐 —— py 是中文文案
 * （`"默认拒绝（deny-by-default）"`），TS 是机器枚举（`permission_not_granted`）」。
 * 审计报告 #4 建议「reason 与 py oracle 逐字对齐」，该建议与本裁定冲突，
 * 主理人已判定**不采纳**；因此这里必须显式豁免，并让反例用例把它钉住
 * （见 `j11-19ops.test.mjs` 的值级反例自检）。
 *
 * 其中 `masked_value` / `message` / `errors` 三条的性质是
 * **「契约合法，但值级不等价」**（不是夹具差异、也不是采集限制）：
 * 主理人 2026-10-21 裁定**登记不修**（TS 侧更严格或属实现自由，详见各条注释），
 * 已登记入 `03-台账` 与 V0.2.1。它们**不得**被用于声称「值级等价」。
 */
export const VALUE_EXCLUSIONS = Object.freeze({
  reason:
    "R-29 + L-4 已裁定：py 是中文文案、TS 是机器枚举，值不逐字对齐是**裁定口径**不是缺陷；" +
    "审计报告「对齐 reason」的建议与 R-29 冲突，主理人已判定不采纳",
  id: "每侧随机 UUID（用户 / 会话 / 权限行 / 凭据行）；存在性由 data_keys 覆盖",
  tenant_id:
    "两侧装配的租户本就不同（py `ensure_default` 生成随机 ULID，TS 用固定 UUID）—— 属夹具差异",
  created_at: "写入时刻（各侧 now()），绝对时刻不可比",
  expires_at: "写入时刻 + TTL 增量 ⇒ 绝对时刻不可比（TTL 常量由白名单 expires_in 面覆盖）",
  device: "设备标识由客户端决定（py 采集器写 node / TS inject 写 lightMyRequest）",
  ip_address: "客户端地址（回环），由调用方网络栈决定",
  user_agent: "同 device：调用方 UA 字符串",
  name: "组织名由种子决定（py Default / TS 组织 A）—— 夹具差异",
  slug: "同上（py default / TS org-a）",
  errors:
    "**契约合法但值级不等价**：校验器私有结构（py FastAPI `loc/msg` vs TS TypeBox " +
    "`instancePath/keyword/params`）。契约 `errorEnvelope.data` 是 `additionalProperties: true` " +
    "的 object ⇒ TS 结构合法；前端零处消费 `data.errors`（已 grep 确认）。主理人 2026-10-21 " +
    "裁定登记不修（逐字对齐等于重写校验器）；`data.errors` 的存在性由 data_keys 覆盖",
  masked_value:
    "**契约合法但值级不等价**：遮罩字形各侧自定（py `orac...alue` 留首尾 4 字符 / " +
    "TS `****alue` 全遮）。契约只要求「仅掩码、无明文」⇒ TS 更严格；为对齐 py 去多露 4 个" +
    "明文字符是**安全降级**，主理人 2026-10-21 裁定不改 TS。前端仅 `{credential.masked_value}` " +
    "原样直出、无解析依赖（已核 apps/web/src）",
  message:
    "**契约合法但值级不等价**：人类可读文案（py 已登出 / TS 已退出登录）。契约把该字段定义为" +
    "人类可读自由文本，文案差异属实现自由；与 reason 同一裁定口径（L-4），主理人裁定不改",
});

/**
 * `raw_preview` 被采集器截断（**500 字符**上限）的三条 op。
 *
 * ⚠️ **这三条 op 的 `token_type` / `expires_in` 没有逐值比对过** —— 原因是硬性的：
 * 它们的 `data` 以两个 JWT 开头（`access_token` / `refresh_token`），而采集器把
 * `raw_preview` 截到 500 字符（`body_bytes` 实测 1006），截断后 JSON 无法解析，
 * py 侧的 `token_type` / `expires_in` 根本读不出来。
 *
 * 这两个字段**仍留在** {@link VALUE_WHITELIST} 里：一旦重采全量 oracle
 * （采集器不再截断 `raw_preview`），它们会**自动**进入逐值比对，不需要改本文件。
 * 换句话说：白名单已就位，缺的只是 py 侧证据。
 *
 * 不要把「在名单里」误读成「已经比过了」—— 这是 `skipped` 与 `ok` 必须分开返回的原因。
 *
 * 三条 op 被跳过的这件事本身**不是豁免**：调用方必须把 `skipped` 集合与这份登记表
 * **逐一比对**（多一条少一条都算红），否则「今天截断三条、明天截断十三条」会无声扩大。
 */
export const TRUNCATED_PREVIEW_IDS = Object.freeze(["register", "login", "refresh"]);

/**
 * 解析 oracle 的 `raw_preview`（py 真运行时抓到的响应原文）。
 *
 * @param {object} expected oracle 的 `expected`。
 * @returns {{ok: true, body: object} | {ok: false, reason: string}}
 */
function parsePreview(expected) {
  const preview = expected?.raw_preview;
  if (typeof preview !== "string" || preview.trim() === "") {
    return { ok: false, reason: "oracle 缺 raw_preview（无法取 py 侧值）" };
  }
  try {
    return { ok: true, body: JSON.parse(preview) };
  } catch {
    return { ok: false, reason: `raw_preview 被截断（${preview.length} 字符）⇒ py 侧值不可读` };
  }
}

/** 值的稳定渲染（对象按 JSON，避免 `[object Object]`）。 */
function render(value) {
  if (typeof value === "string") return JSON.stringify(value);
  if (value === undefined) return "undefined";
  if (value !== null && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** 值是否相等（对象/数组按 JSON 结构；原始值严格相等）。 */
function sameValue(left, right) {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== "object" || typeof right !== "object") {
    return false;
  }
  return JSON.stringify(left) === JSON.stringify(right);
}

/**
 * **值级比对**（FIX-02）：把 py 真运行时的值（`expected.raw_preview`）与 TS 实测值
 * 逐字段比对，字段范围由 {@link VALUE_WHITELIST} 界定，{@link VALUE_EXCLUSIONS} 显式豁免。
 *
 * 三条行为（都有反例用例钉住）：
 *  1. **对象**：白名单字段逐个比**值**（缺字段 / 多字段 / 值不同都报 diff）；
 *  2. **数组**：非空时比**首元素键集合**（值不比 —— 元素里都是 `id` / `created_at`
 *     等每侧不同字段）；py 是空数组时断言实测也为空数组（`list_credentials` 即此形态）；
 *  3. **截断**：`raw_preview` 不可解析 ⇒ 返回 `skipped:true` 而不是 `ok:true`，
 *     调用方必须把它与 {@link TRUNCATED_PREVIEW_IDS} 对齐（见该常量的注释）。
 *
 * @param {object} expected oracle 的 `expected`（含 `raw_preview`）。
 * @param {object|null} body TS 侧响应的**解析后** body（空响应体传 `null`）。
 * @returns {{ok: boolean, diffs: string[], checked: string[], excluded: string[],
 *            unaccounted: string[], skipped: boolean, reason: string|null}}
 *   `unaccounted` = py 有、但既不在白名单也不在排除表的键（非空 ⇒ 有人漏登记）。
 */
export function compareValues(expected, body) {
  const diffs = [];
  const checked = [];
  const excluded = [];
  const unaccounted = [];
  const result = (skipped = false, reason = null) => ({
    ok: diffs.length === 0,
    diffs,
    checked,
    excluded,
    unaccounted,
    skipped,
    reason,
  });

  const parsed = parsePreview(expected);
  if (parsed.ok === false) return result(true, parsed.reason);

  const expectedData = parsed.body?.data;
  const actualData = body?.data;

  // ── 数组形态：首元素键集合 + 空数组断言 ──────────────────────────────────
  if (Array.isArray(expectedData)) {
    if (!Array.isArray(actualData)) {
      diffs.push(`data 形态: py 是数组，实测 ${actualData === null ? "null" : typeof actualData}`);
      return result();
    }
    if (expectedData.length === 0) {
      // py 侧为空 ⇒ 实测必须也为空（否则是「多出了行」这种最需要发现的偏差）。
      if (actualData.length !== 0) {
        diffs.push(`data 元素数: py 期望空数组，实测 ${actualData.length} 行`);
      }
      checked.push("data[]:empty");
      return result();
    }
    const expectedKeys = Object.keys(expectedData[0] ?? {}).sort();
    const actualFirst = actualData[0];
    if (actualFirst === null || typeof actualFirst !== "object") {
      diffs.push("data[0]: py 是对象，实测不是对象");
      return result();
    }
    const actualKeys = Object.keys(actualFirst).sort();
    const missing = expectedKeys.filter((key) => !actualKeys.includes(key));
    const extra = actualKeys.filter((key) => !expectedKeys.includes(key));
    if (missing.length > 0) diffs.push(`data[0] 少键: ${missing.join(", ")}`);
    if (extra.length > 0) diffs.push(`data[0] 多键: ${extra.join(", ")}`);
    checked.push(`data[0].keys(${expectedKeys.length})`);
    return result();
  }

  // ── 对象形态：白名单逐值比对 ─────────────────────────────────────────────
  if (expectedData === null || typeof expectedData !== "object") {
    // py 侧 data 不是对象（不应出现）；只记录形态差异，不伪造通过。
    if (expectedData !== actualData) {
      diffs.push(`data: py 是 ${render(expectedData)}，实测 ${render(actualData)}`);
    }
    return result();
  }
  if (actualData === null || typeof actualData !== "object" || Array.isArray(actualData)) {
    diffs.push(`data 形态: py 是对象，实测 ${actualData === null ? "null" : typeof actualData}`);
    return result();
  }

  for (const key of Object.keys(expectedData)) {
    if (Object.hasOwn(VALUE_WHITELIST, key)) {
      checked.push(key);
      if (!Object.hasOwn(actualData, key)) {
        diffs.push(`值: 少字段 ${key}（py=${render(expectedData[key])}）`);
        continue;
      }
      if (!sameValue(expectedData[key], actualData[key])) {
        diffs.push(
          `值: ${key} 期望 ${render(expectedData[key])}，实测 ${render(actualData[key])}`
        );
      }
      continue;
    }
    if (Object.hasOwn(VALUE_EXCLUSIONS, key)) {
      excluded.push(key);
      continue;
    }
    unaccounted.push(key);
  }

  // 白名单字段在 py 侧缺失、TS 侧却出现 ⇒ 也是分岔（不静默放过）。
  for (const key of Object.keys(VALUE_WHITELIST)) {
    if (!Object.hasOwn(expectedData, key) && Object.hasOwn(actualData, key)) {
      diffs.push(`值: 多字段 ${key}（py 无此键，实测=${render(actualData[key])}）`);
    }
  }

  return result();
}

// ─────────────────────────────────────────────────────────────────────────────
// PG 档的**输入替换**（V0.2.0 审计 #2 / FIX-09 收口 · 冻结面矛盾，不是跨语言分叉）
// ─────────────────────────────────────────────────────────────────────────────
//
// 为什么需要这张表（dev 服务器 PG 18.6 实测到的**原始错误**，不是推测）：
//
//     error: invalid input syntax for type uuid: "oracle-value"   code 22P02
//     WHERE unnamed portal parameter $6 = 'oracle-value'      -- $6 = resource_id
//
// 冻结 DDL 的双档类型不同：PG 的 `resource_permission.resource_id` 是 **UUID**，
// SQLite 的同一列是 **CHAR(36)**。而 oracle 的输入是 `tool_id: "oracle-value"`
// （非 UUID）—— SQLite 能收，PG 直接类型错。
//
// 关键判断（决定了这条改动**不是**在掩盖缺陷）：
// 1. py 侧 schema 实测是 `tool_id: str`（`wbtime_ai_api/schemas/tool.py:37`）⇒
//    **py-on-PG 也会 500**。所以这是「契约允许任意 string / 冻结 DDL 要求 UUID」的
//    冻结面矛盾（继承自 py），**不是** TS 的跨语言分叉；
// 2. 本版不允许改 DDL/契约（硬边界）⇒ 只能在**测试输入**侧让 PG 档能跑；
// 3. 所以这张表必须在**报告里可见**（值级比对该行标注 `tool_id=方言替换`），
//    并且用守卫断言把它的规模钉死 —— 见 {@link PG_INPUT_OVERRIDES_KEYS}。
//
// 边界（写清，防止被当成通用橡皮擦）：
//   * **只有** `dialect === "pg"` 时生效；SQLite 档逐字不变（仍发 `"oracle-value"`、
//     仍与 py 值比对，所以 SQLite 档仍在证明「值级等价」）；
//   * 只支持 `body.<field>` 一种形态（本版唯一的用例）；其它形态直接抛，不静默放过；
//   * 表规模**必须恒为 1 条**，多一条就红（{@link PG_INPUT_OVERRIDES_KEYS} 有单测）。

/**
 * PG 档唯一允许的输入替换（**规模恒为 1 条**，扩张即红）。
 *
 * `path` 的第一段是**输入来源**（`body` / `query` / `params`；本版只实现 `body`），
 * 最后一段同时用于**同步期望值**（响应 `data` 里同名字段）—— 这样一条记录只有一个
 * `value`，不会出现"请求改了、期望没改"的半截状态。
 */
export const PG_INPUT_OVERRIDES = Object.freeze({
  create_tool_permission: Object.freeze({
    path: "body.tool_id",
    value: "00000000-0000-4000-8000-0000000000aa",
  }),
});

/** 允许出现在 {@link PG_INPUT_OVERRIDES} 里的 op 键（守卫用：多一条就红）。 */
export const PG_INPUT_OVERRIDES_KEYS = Object.freeze(["create_tool_permission"]);

/**
 * 按方言改写**请求体**（只对登记过的 op 生效）。
 *
 * @param {string} opId oracle 的 `id`。
 * @param {object|null|undefined} payload 原请求体。
 * @param {"sqlite"|"pg"} [dialect] 方言（默认 {@link PARITY_DIALECT}）。
 * @returns {{payload: object|null|undefined, applied: boolean}} 改写后的请求体与应用标记。
 * @throws {Error} `path` 不是 `body.<field>` 形态，或 body 不是对象（**不静默 no-op**）。
 */
export function applyInputOverride(opId, payload, dialect = PARITY_DIALECT) {
  const rule = PG_INPUT_OVERRIDES[opId];
  if (dialect !== "pg" || rule === undefined) return { payload, applied: false };

  const segments = String(rule.path).split(".");
  if (segments.length !== 2 || segments[0] !== "body") {
    throw new Error(
      `PG_INPUT_OVERRIDES['${opId}'].path 只支持 "body.<field>"，实测 ${JSON.stringify(rule.path)}`
    );
  }
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error(
      `PG_INPUT_OVERRIDES['${opId}'] 需要对象型请求体，实测 ${JSON.stringify(payload)}`
    );
  }
  return { payload: { ...payload, [segments[1]]: rule.value }, applied: true };
}

/**
 * 按方言同步**期望值**（改 `raw_preview` 里响应 `data` 的同名字段）。
 *
 * 为什么改 `raw_preview` 而不是给 `compareValues` 加参数：值级比对的唯一真值来源就是
 * 那份 py 响应原文；把注入点收敛在这里，`compareValues` 仍然只做"比"，不知道方言。
 *
 * @param {object} expected oracle 的 `expected`。
 * @param {string} opId oracle 的 `id`。
 * @param {"sqlite"|"pg"} [dialect] 方言（默认 {@link PARITY_DIALECT}）。
 * @returns {{expected: object, applied: boolean}} 改写后的 expected 与应用标记。
 * @throws {Error} `raw_preview` 不可解析（被截断），或 `data` 不是对象。
 */
export function applyExpectedOverride(expected, opId, dialect = PARITY_DIALECT) {
  const rule = PG_INPUT_OVERRIDES[opId];
  if (dialect !== "pg" || rule === undefined) return { expected, applied: false };

  const field = String(rule.path).split(".").at(-1);
  const parsed = parsePreview(expected);
  if (parsed.ok === false) {
    throw new Error(
      `op ${opId} 登记了输入替换，但 raw_preview 不可解析（${parsed.reason}）——` +
        "期望值无法同步，不允许半截替换"
    );
  }
  const data = parsed.body?.data;
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`op ${opId} 的 raw_preview.data 不是对象，无法同步 ${field} 的期望值`);
  }
  return {
    expected: {
      ...expected,
      raw_preview: JSON.stringify({ ...parsed.body, data: { ...data, [field]: rule.value } }),
    },
    applied: true,
  };
}
