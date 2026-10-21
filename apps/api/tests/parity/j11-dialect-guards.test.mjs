/**
 * FIX-09 护栏单测 —— **不需要真 PG** 就能证明「PG 档的四道闸与降格口径」成立。
 *
 * 为什么这些断言值得单独立文件：本轮 `127.0.0.1:5433` 隧道已断、PG 主机
 * **2026-10-22 到期**（`02-施工/00-施工期裁定.md` R-3x），所以「PG 等价」**不可验证**。
 * 不可验证时最容易滑向两种假绿：
 *   ① 干脆 skip 掉，报告里写成"通过"；
 *   ② 让它默认退回 SQLite，然后含糊地叫"parity 全绿"。
 * 本文件把"可验证的那一半"钉死：**方言解析**、**缺 URL 必须抛错（不 skip）**、
 * **reset 只能删已知表（禁 DROP SCHEMA）**、**两档 DDL 表名集合一致**。
 * 真正需要 PG 的那一半（灌 DDL + 跑 19 op）由 `pnpm test:parity:pg` 承担，
 * 且**只有**人能给出 `WBTIME_PG_URL` 时才会跑。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import {
  DIALECT_ENV,
  PG_DDL_PATH,
  PG_HOST_ENV,
  PG_HOST_PLACEHOLDER,
  PG_PARITY_DB,
  PG_RESET_ENV,
  PG_SHARED_DB,
  PG_URL_ENV,
  ROOT,
  PG_INPUT_OVERRIDES,
  PG_INPUT_OVERRIDES_KEYS,
  applyExpectedOverride,
  applyInputOverride,
  createSeedAdapter,
  listDdlTables,
  loadOracle,
  requirePgUrl,
  resolveDialect,
  resolvePgHost,
  seedTenants,
  toPgPlaceholders,
  tunnelCommandHint,
} from "./j11-harness.mjs";
import {
  PG_RESET_OFF,
  PG_RESET_ON,
  describeReset,
  parityResetEnv,
} from "../../../../scripts/lib/parity-env.mjs";

test("方言解析：缺省 sqlite / 显式 pg 可用 / 非法值直接抛（不猜、不回落）", () => {
  assert.equal(resolveDialect({}), "sqlite", "未设置时必须默认 sqlite（本版默认档）");
  assert.equal(resolveDialect({ [DIALECT_ENV]: "" }), "sqlite", "空串等价于未设置");
  assert.equal(resolveDialect({ [DIALECT_ENV]: "sqlite" }), "sqlite");
  assert.equal(resolveDialect({ [DIALECT_ENV]: "pg" }), "pg");
  assert.equal(resolveDialect({ [DIALECT_ENV]: "PG" }), "pg", "大小写不敏感");
  assert.equal(resolveDialect({ [DIALECT_ENV]: "postgres" }), "pg", "postgres 视为 pg");

  // 非法值必须抛：静默回落 sqlite 会把"打错字"变成"看起来跑过了"
  assert.throws(
    () => resolveDialect({ [DIALECT_ENV]: "postgresql9" }),
    /WBTIME_PARITY_DIALECT 只接受 sqlite \/ pg/,
  );
});

test("PG 档缺 WBTIME_PG_URL ⇒ **抛错**（打印隧道命令），不 skip、不回落 sqlite", () => {
  let message = "";
  assert.throws(
    () => requirePgUrl({}),
    (error) => {
      message = error instanceof Error ? error.message : String(error);
      return true;
    },
  );
  assert.match(message, new RegExp(PG_URL_ENV), "错误必须点名缺失的环境变量");
  assert.match(message, /ssh -N -L 5433:127\.0\.0\.1:5432/, "必须给出可直接粘贴的隧道命令");
  assert.match(message, new RegExp(PG_PARITY_DB), "必须点名专用空库");
  assert.match(message, /不\*\*做\*\* skip|\*\*不做\*\* skip/, "必须写明「不做」skip（显式拒绝假绿）");
  assert.match(message, /不算绿/, "必须写明「不算绿」");

  // 有 URL 时原样返回（不 trim 掉内部字符，只去首尾空白）
  assert.equal(requirePgUrl({ [PG_URL_ENV]: "  postgres://u@h:5433/db  " }), "postgres://u@h:5433/db");
});

test("隧道命令提示：结构化判据 —— 无具体地址、无真实用户名、无口令", () => {
  // 判据必须是**结构化**的：写 `hint.includes("某个真实用户名")` 等于把要防的东西
  // 留在仓库里（那条字面量本身就是泄漏）。所以这里一律用形态规则，不用实值。
  const hint = tunnelCommandHint({});

  // ① 主机位置必须是占位符（本仓源码不内置任何基础设施地址）
  assert.match(hint, /<SSH_USER>/, "SSH 用户必须是占位符（真实值在 gitignored 文档里）");
  assert.match(hint, /<PG_PASSWORD>/, "口令必须是占位符");
  assert.match(
    hint,
    /ssh -N -L 5433:127\.0\.0\.1:5432 <SSH_USER>@<PG_HOST>/,
    "隧道命令行必须是 `ssh -N -L 5433:127.0.0.1:5432 <SSH_USER>@<PG_HOST>` 形态",
  );
  assert.match(hint, /WBTIME_PG_HOST/, "必须提示主机可由 WBTIME_PG_HOST 覆盖");

  // ② 不得出现**非回环**的 IPv4 字面量。
  //    为什么不是「任何 IPv4 都零命中」：隧道命令本体必须写 `127.0.0.1:5432`（远端的
  //    回环地址）与 `127.0.0.1:5433`（本地回环），这是命令正确性的一部分，把回环也禁掉
  //    只会逼出"用 hostname 代替回环"这种更糟的写法。真正的风险是**基础设施地址**入仓，
  //    即除回环外的任何 IPv4。
  const ipv4 = hint.match(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g) ?? [];
  assert.deepEqual(
    ipv4.filter((address) => address !== "127.0.0.1"),
    [],
    `隧道提示里出现了非回环 IPv4（基础设施地址不得入仓）：${ipv4.join(", ")}`,
  );

  // ③ `@` 之后不得是具体用户名（必须有第二个 `@` 才算"用户名@主机"形态）
  assert.equal(
    /@(?!<)[A-Za-z0-9._-]+@/.test(hint),
    false,
    "隧道提示里出现了 `用户名@主机` 的实值形态（用户名与地址都不得入仓）",
  );

  // ④ 不得出现口令字形
  for (const forbidden of ["password=", "passwd", "PASSWORD="]) {
    assert.equal(
      hint.toLowerCase().includes(forbidden.toLowerCase()),
      false,
      `隧道提示里出现了疑似口令片段：${forbidden}`,
    );
  }
  // 口令位置只能是 `<PG_PASSWORD>` 占位符，不能是 `:xxxx@` 形式的字面量
  assert.equal(/:([^/<>@\s]{6,})@/.test(hint), false, "URL 模板里不得出现字面量口令");

  // ⑤ 覆盖率自证：`WBTIME_PG_HOST` 有值时确实会被替换（否则"支持覆盖"是空话）
  const overridden = tunnelCommandHint({ WBTIME_PG_HOST: "pg.example.internal" });
  assert.match(overridden, /<SSH_USER>@pg\.example\.internal/, "设置 WBTIME_PG_HOST 后应替换占位符");
  assert.equal(overridden.includes("<PG_HOST>"), false, "替换后不应残留占位符");

  // ⑥ `resolvePgHost()` 的缺省行为
  assert.equal(resolvePgHost({}), PG_HOST_PLACEHOLDER);
  assert.equal(resolvePgHost({ [PG_HOST_ENV]: "  " }), PG_HOST_PLACEHOLDER, "空白视同未设置");
  assert.equal(resolvePgHost({ [PG_HOST_ENV]: "h.example" }), "h.example");
});

test("PG 占位符改写：`?` → `$1..$n`，且跳过字符串字面量/注释/jsonb 运算符", () => {
  // 缺陷来源（dev 服务器 PG 18.6 首跑实测）：
  //   not ok 1 - J-11 …（dialect=pg）
  //   error: syntax error at or near ","   code: 42601
  //   at seedTenants (j11-harness.mjs:335) ← adapter.run
  // 根因：播种 SQL 用 `?`（node:sqlite 写法），PG 只认 `$n`。
  // 这条用例把「改写正确」和「不该改写的地方没改」同时钉住 —— 后者更关键：
  // 粗暴 split/join 会把 `'a?b'` 改坏，而且改坏后往往"还能跑"，只是参数错位。

  // ① 基本改写（本轮修复的主路径）
  assert.equal(
    toPgPlaceholders("INSERT INTO tenant (id, name, slug, is_active) VALUES (?, ?, ?, ?)"),
    "INSERT INTO tenant (id, name, slug, is_active) VALUES ($1, $2, $3, $4)",
  );
  assert.equal(toPgPlaceholders("VALUES (?, ?, ?)"), "VALUES ($1, $2, $3)", "你给的用例原样成立");

  // ② 单引号字符串里的 `?` 不得被替换
  assert.equal(toPgPlaceholders("SELECT 'a?b', ?"), "SELECT 'a?b', $1");
  // ②' `''` 是字符串内的转义单引号，字符串并未结束 ⇒ 后面的 `?` 仍是字面量
  assert.equal(toPgPlaceholders("SELECT 'it''s ?', ?"), "SELECT 'it''s ?', $1");

  // ③ 双引号标识符里的 `?` 不得被替换
  assert.equal(toPgPlaceholders('SELECT "weird?col", ?'), 'SELECT "weird?col", $1');

  // ④ jsonb 运算符 `?|` / `?&` 不是占位符
  assert.equal(
    toPgPlaceholders("SELECT 1 WHERE config ?| array['a'] AND config ?& array['b']"),
    "SELECT 1 WHERE config ?| array['a'] AND config ?& array['b']",
  );

  // ⑤ 注释里的 `?` 不得被替换（行注释 + 块注释）
  assert.equal(toPgPlaceholders("-- ? 不是参数\nSELECT ?"), "-- ? 不是参数\nSELECT $1");
  assert.equal(toPgPlaceholders("/* ? */ SELECT ?"), "/* ? */ SELECT $1");

  // ⑥ 占位符后接类型转换：`?::text` ⇒ `$1::text`（`::` 作用在参数上，不是 `?` 的另一语法）
  assert.equal(toPgPlaceholders("SELECT ?::text"), "SELECT $1::text");

  // ⑦ 序号连续且从 1 开始（跳过的 `?` 不占号）
  assert.equal(toPgPlaceholders("VALUES ('?', ?, '?', ?)"), "VALUES ('?', $1, '?', $2)");

  // ⑧ 无占位符的文本原样返回（DDL 走 exec，不该被动过）
  const ddlLike = 'CREATE TABLE t (id CHAR(36) NOT NULL, flag BOOLEAN NOT NULL);';
  assert.equal(toPgPlaceholders(ddlLike), ddlLike);
});

test("seedTenants 的布尔列按方言取值：pg 传 true、sqlite 传 1（SQL 文本两档一致）", async () => {
  // 第二处根因：`tenant.is_active` 在 sqlite 是 integer（传 true ⇒ node:sqlite TypeError）、
  // 在 PG 是 boolean（传 1 ⇒ 类型错）。「顺手统一」会在某一档上炸，所以必须按方言取值。
  // 用假适配器记录入参 —— 不需要真库，也就能在本地证明 PG 那一路写的是 true。

  /** 记录每次 run 的假适配器。 */
  const recorder = (dialect) => {
    const calls = [];
    return {
      dialect,
      calls,
      async run(sql, params = []) {
        calls.push({ sql, params });
      },
      async exec() {},
    };
  };

  const pg = recorder("pg");
  await seedTenants(pg);
  const pgTenant = pg.calls[0];
  assert.match(pgTenant.sql, /INSERT INTO tenant \(id, name, slug, is_active\) VALUES \(\?, \?, \?, \?\)/,
    "SQL 文本必须是带 `?` 的那份（改写归适配器，不在播种处改 SQL —— 否则 sqlite 档被牵连）");
  assert.equal(pgTenant.params[3], true, "PG 的 is_active 必须是 boolean true");
  assert.equal(typeof pgTenant.params[3], "boolean", "PG 的 is_active 不得是数字 1");

  const sqlite = recorder("sqlite");
  await seedTenants(sqlite);
  const sqliteTenant = sqlite.calls[0];
  assert.equal(sqliteTenant.params[3], 1, "SQLite 的 is_active 必须仍是 integer 1");
  assert.equal(typeof sqliteTenant.params[3], "number", "SQLite 的 is_active 不得是 JS true");

  // 两档的 SQL 文本逐字一致（证明没有夹带别的方言分支：占位符改写只在适配器里发生）
  assert.deepEqual(
    sqlite.calls.map((call) => call.sql),
    pg.calls.map((call) => call.sql),
    "两档的 SQL 文本必须逐字一致（`?` 由适配器改写，不在播种处出现方言分支）",
  );
  // 参数：**只有** `tenant.is_active`（第 1 条 INSERT 的第 4 个参数）允许不同
  for (const index of [0, 1, 2]) {
    const sqliteParams = [...sqlite.calls[index].params];
    const pgParams = [...pg.calls[index].params];
    if (index === 0) {
      assert.equal(sqliteParams[3], 1, "SQLite 的 is_active 是 integer 1");
      assert.equal(pgParams[3], true, "PG 的 is_active 是 boolean true");
      sqliteParams[3] = "<is_active>";
      pgParams[3] = "<is_active>";
    }
    assert.deepEqual(
      sqliteParams,
      pgParams,
      `第 ${index + 1} 条 INSERT 的参数（除 is_active 外）必须一致`,
    );
  }

  // 三次播种都在（tenant / organization / model_provider），防止"只改第一条就交差"
  assert.equal(pg.calls.length, 3, "播种必须仍然是三条 INSERT");
  assert.equal(sqlite.calls.length, 3);

  // 缺 dialect 的适配器必须当场抛（否则无法决定布尔取值 —— 静默猜一个就是埋雷）
  await assert.rejects(() => seedTenants({ async run() {} }), /需要带 dialect 的适配器/);

  // 闭环：**真的**走 `createSeedAdapter("pg", …)` 这一层（dev 服务器上炸的正是这一跳），
  // 断言"交给驱动的 SQL 已是 `$n`、且 is_active 是 boolean"——只测纯函数 + 只测播种
  // 都不足以证明两者接上了。
  const sent = [];
  const fakePgHandle = {
    pool: {
      async query(sql, params) {
        sent.push({ sql, params });
      },
    },
  };
  await seedTenants(createSeedAdapter("pg", fakePgHandle));
  assert.equal(sent.length, 3, "三条 INSERT 都应到达驱动");
  assert.match(
    sent[0].sql,
    /INSERT INTO tenant \(id, name, slug, is_active\) VALUES \(\$1, \$2, \$3, \$4\)/,
    "到达驱动的 SQL 必须是 `$1..$4` 形态（PG 不接受 `?`，42601 就是这一步炸的）",
  );
  assert.equal(sent[0].params[3], true, "到达驱动的 is_active 必须是 boolean true");
  assert.equal(
    sent.some((call) => call.sql.includes("?")),
    false,
    "任何一条到达驱动的 SQL 都不得残留 `?` 占位符",
  );
});

test("PG DDL 表名解析 = 61 张，且**与 SQLite 档表名集合完全一致**（方言切换前提）", () => {
  const pgDdl = readFileSync(PG_DDL_PATH, "utf8");
  const sqliteDdl = readFileSync(join(ROOT, "output", "ddl.sqlite.sql"), "utf8");

  const pgTables = listDdlTables(pgDdl);
  const sqliteTables = listDdlTables(sqliteDdl);

  assert.equal(pgTables.length, 61, `PG 冻结面必须 61 张表，实测 ${pgTables.length}`);
  assert.equal(new Set(pgTables).size, 61, "表名不得重复（正则重复捕获会让 DROP 语句变味）");
  assert.deepEqual(
    [...pgTables].sort(),
    [...sqliteTables].sort(),
    "两档表名集合必须完全一致 —— 否则「同一条 SQL 播种」在另一档上会指向不同的表",
  );
});

test("reset 红线：只允许按已知表 DROP TABLE，**禁止** DROP SCHEMA / 删共享库", () => {
  // 扫**代码**而不是注释：本文件与 harness 的注释里正当地讨论了这条红线
  // （`明令禁止 DROP SCHEMA public CASCADE`），若不剥注释会自己把自己判红。
  const source = stripComments(
    readFileSync(new URL("./j11-harness.mjs", import.meta.url), "utf8")
  );

  // ① 可执行代码里不得出现 `DROP SCHEMA`（会连带删掉别人的对象）
  assert.equal(
    /DROP\s+SCHEMA/i.test(source),
    false,
    "j11-harness.mjs 的可执行代码里出现 DROP SCHEMA —— 违反 reset 红线（只许 DROP 已知表）",
  );
  // ② 必须确实是按表名列表 DROP（而不是 `DROP TABLE` 裸删或 `TRUNCATE`）
  assert.match(source, /DROP TABLE IF EXISTS \$\{/, "reset 必须是「按解析出的表名列表 DROP」");
  // ③ 共享库与专用库名必须是常量并对不上（名字含 parity 才放行）
  assert.notEqual(PG_SHARED_DB, PG_PARITY_DB);
  assert.match(PG_PARITY_DB, /parity/, "专用库名必须含 parity（闸 1 的判据）");
  // ④ reset 开关只能靠环境变量显式给
  assert.equal(PG_RESET_ENV, "WBTIME_PG_RESET");
});

test("PG 输入替换表：同一份 oracle 输入 sqlite 不改写 / pg 改写为 UUID；期望值同步只动 tool_id", () => {
  // 背景（dev 服务器 PG 18.6 实测）：`invalid input syntax for type uuid: "oracle-value"` 22P02，
  // 因为冻结 DDL 里 PG 的 `resource_permission.resource_id` 是 UUID，而 SQLite 是 CHAR(36)。
  // py 侧 schema 也是 `tool_id: str` ⇒ py-on-PG 同会 500 ⇒ 属冻结面矛盾，不是跨语言分叉。
  const oracle = loadOracle();
  const op = oracle.ops.find((item) => item.id === "create_tool_permission");
  assert.ok(op, "oracle 必须含 create_tool_permission");
  const originalBody = op.request.body;
  const uuid = PG_INPUT_OVERRIDES.create_tool_permission.value;

  // ── ① SQLite 档：逐字不变（同一引用即可证明"没复制、没改")────────────────
  const sqliteApplied = applyInputOverride("create_tool_permission", originalBody, "sqlite");
  assert.equal(sqliteApplied.applied, false, "SQLite 档不得应用输入替换");
  assert.equal(sqliteApplied.payload, originalBody, "SQLite 档必须原样返回同一个对象");
  assert.equal(originalBody.tool_id, "oracle-value", "oracle 的原始输入必须仍是 oracle-value");

  // ── ② PG 档：只改 tool_id，其余字段原样；且**不**改写原对象（无副作用）──────
  const pgApplied = applyInputOverride("create_tool_permission", originalBody, "pg");
  assert.equal(pgApplied.applied, true, "PG 档必须应用输入替换");
  assert.equal(pgApplied.payload.tool_id, uuid, "PG 档 tool_id 必须替换为 UUID");
  assert.equal(originalBody.tool_id, "oracle-value", "不得就地改写 oracle 的输入对象");
  assert.deepEqual(
    Object.keys(pgApplied.payload).sort(),
    Object.keys(originalBody).sort(),
    "替换不得增减字段（只换值）",
  );
  for (const key of Object.keys(originalBody)) {
    if (key === "tool_id") continue;
    assert.deepEqual(pgApplied.payload[key], originalBody[key], `字段 ${key} 不得被牵连`);
  }

  // 未登记的 op 在 pg 档同样逐字不变（表只有一条，不许顺手扩）
  const untouched = applyInputOverride("get_me", { a: 1 }, "pg");
  assert.equal(untouched.applied, false);
  assert.deepEqual(untouched.payload, { a: 1 });

  // ── ③ 期望值同步：只覆盖 tool_id，其它字段仍来自 oracle ────────────────
  const pgExpected = applyExpectedOverride(op.expected, "create_tool_permission", "pg");
  assert.equal(pgExpected.applied, true);
  const patched = JSON.parse(pgExpected.expected.raw_preview);
  const oraclePreview = JSON.parse(op.expected.raw_preview);
  assert.equal(patched.data.tool_id, uuid, "期望值的 tool_id 必须同步为 UUID");
  assert.deepEqual(
    patched.data,
    { ...oraclePreview.data, tool_id: uuid },
    "除 tool_id 外，期望值必须逐字仍是 oracle 的（不做任何「顺手对齐」）",
  );
  assert.equal(patched.code, oraclePreview.code, "壳的 code 不得被改");
  assert.equal(patched.message, oraclePreview.message, "壳的 message 不得被改");
  assert.equal(
    op.expected.raw_preview.includes("oracle-value"),
    true,
    "oracle 原对象不得被就地改写（raw_preview 仍含 oracle-value）",
  );

  // SQLite 档的期望值同样逐字不变
  const sqliteExpected = applyExpectedOverride(op.expected, "create_tool_permission", "sqlite");
  assert.equal(sqliteExpected.applied, false);
  assert.equal(sqliteExpected.expected, op.expected, "SQLite 档期望值必须是同一引用");
});

test("PG 输入替换**防扩张**：登记表键集合必须恰好一条（多一条就红）", () => {
  // 这张表是"冻结面矛盾的临时出口"，一旦能随手加条目，它就会变成掩盖真缺陷的橡皮擦
  // —— 那时 PG 档"19/19 绿"就不再有任何信息量。所以规模钉死在 1 条。
  assert.deepEqual(
    Object.keys(PG_INPUT_OVERRIDES),
    [...PG_INPUT_OVERRIDES_KEYS],
    "PG_INPUT_OVERRIDES 的键集合必须与 PG_INPUT_OVERRIDES_KEYS 完全一致",
  );
  assert.deepEqual(
    [...PG_INPUT_OVERRIDES_KEYS],
    ["create_tool_permission"],
    "允许的替换**只能**是 create_tool_permission 这一条；新增必须先改本断言并给出理由",
  );
  assert.equal(Object.keys(PG_INPUT_OVERRIDES).length, 1, "表规模必须恰好 1 条");
  // 每条必须齐备 path/value（缺一个就是半截替换）
  for (const [opId, rule] of Object.entries(PG_INPUT_OVERRIDES)) {
    assert.match(rule.path, /^body\.[A-Za-z_][A-Za-z0-9_]*$/, `${opId}: path 必须是 body.<field> 形态`);
    assert.equal(typeof rule.value, "string", `${opId}: value 必须是字符串`);
    assert.match(
      rule.value,
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
      `${opId}: value 必须是 UUID 形态（替换的目的就是喂给 UUID 列）`,
    );
  }
});

test("parity runner 的 RESET 决策：默认注入 1、显式 0 不注入、注入值只可能是 \"1\"", () => {
  // dev 服务器实测：`j11-19ops.test.mjs` 有 3 个 test 各自 `makeParityApp()`，PG 档共用
  // 同一个 parity 库 ⇒ 不清库则第 2、3 个必然撞闸 2（非空库），官方命令会得到 1 过 2 红。
  // 所以 runner **必须默认**带 `WBTIME_PG_RESET=1`；这三条断言就是那条默认值的守卫。

  // ── ① 默认开（未设置 / 空串都算"没给"）────────────────────────────────
  for (const raw of [undefined, "", "   "]) {
    const decision = parityResetEnv(raw === undefined ? {} : { [PG_RESET_ENV]: raw });
    assert.equal(decision.mode, "on", `未设置/空白时必须默认开（实测 raw=${JSON.stringify(raw)}）`);
    assert.equal(decision.env[PG_RESET_ENV], PG_RESET_ON, "默认必须注入 1");
    assert.equal(decision.reason, "default");
  }

  // ── ② 显式 0：**不注入**（尊重用户；库非空时由闸 2 报错）──────────────
  const off = parityResetEnv({ [PG_RESET_ENV]: PG_RESET_OFF });
  assert.equal(off.mode, "off");
  assert.deepEqual(off.env, {}, "显式关时不得注入任何值（不注入才不会覆盖用户的 0）");
  assert.equal(Object.hasOwn(off.env, PG_RESET_ENV), false);
  assert.equal(off.reason, "user-off");

  // ── ③ 注入值只可能是 "1"（`true`/`yes`/`on` 等都归一，理由见模块头注）────
  for (const raw of ["1", "true", "TRUE", "yes", "on", "01"]) {
    const decision = parityResetEnv({ [PG_RESET_ENV]: raw });
    assert.equal(decision.mode, "on", `raw=${raw} 应视为开`);
    assert.deepEqual(
      Object.keys(decision.env),
      [PG_RESET_ENV],
      "只允许注入 RESET 这一个变量（不要顺手塞别的东西）",
    );
    assert.equal(decision.env[PG_RESET_ENV], PG_RESET_ON, `raw=${raw} 必须归一成 "1"`);
  }

  // ── 日志可见性：开/关两态都要能一眼看出来 ──────────────────────────────
  assert.match(describeReset(parityResetEnv({})), /RESET=on/);
  assert.match(describeReset(parityResetEnv({})), /仅对库名含 parity 且非共享库生效/, "必须写清安全边界");
  assert.match(describeReset(parityResetEnv({ [PG_RESET_ENV]: PG_RESET_OFF })), /RESET=off/);
  assert.match(
    describeReset(parityResetEnv({ [PG_RESET_ENV]: PG_RESET_OFF })),
    /不会自动清库/,
    "关态必须说明「库非空会报错」，否则用户会以为没事",
  );
});

/**
 * 去掉 `/* … *\/` 块注释与 `// …` 行注释（保留换行，便于报行号）。
 *
 * 只用于本文件这种"扫自己源码"的断言；不做字符串/正则字面量的精细建模
 * —— 它失败的方向是**多剥**（漏报），而这里的红线同时被 ①②③④ 四条交叉覆盖。
 *
 * @param {string} text 源码全文。
 * @returns {string} 剥掉注释后的文本。
 */
function stripComments(text) {
  return String(text ?? "")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((line) => line.replace(/\/\/.*$/, ""))
    .join("\n");
}
