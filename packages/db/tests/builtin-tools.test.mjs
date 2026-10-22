/**
 * T3-03 · B1 · 内置工具物化的行为证明（**R3-23**）。
 *
 * 判据（任务卡验收 ④ + R3-23 影响判据 ①②③④）：
 *   ① `ensureBuiltinTools` 两次 ⇒ `tool` 行数 **== 5**（不是 10），且第二次**写次数为 0**；
 *   ② 5 行的 `input_schema` 与注册表**逐字节一致**（SQLite 档比原始字符串）；
 *   ③ `source='builtin'` / `status='active'` / `tenant_id=<scope>`（按租户物化）；
 *   ④ 手工造重复行 ⇒ {@link ToolRepo.findDuplicates} 必非空（常驻反例，**不**真并发去撞）。
 *
 * 两条刻意的口径（与任务卡对齐，写在这里免得后人误读）：
 *   * **`input_schema` 的"逐字节"只在 SQLite 档成立**：PG 的 `jsonb` 会重排键序 + 去空白，
 *     拿回读原文比必然假红 ⇒ PG 档只比深等价 + 稳定 sha（见 `runtime-pg.mjs` 的口径说明）。
 *   * **不测"并发首启会重复"**：R3-23 ③ 把 `ensureBuiltinTools` 限定为单写者
 *     （bootstrap、进程内串行），真去并发撞只会验证出"没有唯一索引"，得不出稳定结论。
 *     已知弱点用④的常驻反例暴露。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  BUILTIN_TOOLS,
  BUILTIN_TOOL_VERSION,
  CODE_EXEC_DEFAULT_RUNTIME,
  CODE_EXEC_RUNTIMES,
  Scope,
  TOOL_SOURCE_BUILTIN,
  TOOL_STATUS_ACTIVE,
  ToolRepo,
  readToolPermissionAction,
  serializeBuiltinInputSchema,
  serializeBuiltinToolSpec,
  toToolCatalogEntry,
} from "../dist/repositories/index.js";

import { DIALECT, freshConnection, seedParents, T_A, T_B } from "./fixtures/runtime-fixture.mjs";

/** 每例一份新库（父链已灌：两个租户）。 */
function seed() {
  const connection = freshConnection();
  seedParents(connection);
  return { connection, db: connection.db, scopeA: new Scope(T_A), scopeB: new Scope(T_B) };
}

/** 连接级写次数（`INSERT`/`UPDATE`/`DELETE` 递增，`SELECT` 不递增）。 */
function totalChanges(connection) {
  const row = connection.raw.prepare("select total_changes() as n").get();
  return Number(row.n);
}

/** 直读 `tool` 表（绕过仓储 —— 断言"库里到底有什么"，而不是"仓储说有什么"）。 */
function rawTools(connection, tenantId) {
  return tenantId === undefined
    ? connection.raw.prepare("select * from tool").all()
    : connection.raw.prepare("select * from tool where tenant_id = ?").all(tenantId);
}

/** 直读 `tool_version` 行数（按租户 join 回 `tool`）。 */
function rawVersionCount(connection, tenantId) {
  const row = connection.raw
    .prepare(
      "select count(*) as n from tool_version v join tool t on t.id = v.tool_id where t.tenant_id = ?",
    )
    .get(tenantId);
  return Number(row.n);
}

// ---------------------------------------------------------------------------
// A · 注册表本身（`input_schema` 的唯一真源）
// ---------------------------------------------------------------------------

test("A · 注册表：5 个工具，名字与顺序按 R3-23", () => {
  assert.deepEqual(
    BUILTIN_TOOLS.map((spec) => spec.name),
    ["filesystem", "git", "http", "shell", "code_exec"],
  );
  assert.equal(BUILTIN_TOOLS.length, 5, "判据 ④ 的 5 就是这里的 5");
});

test("A · 注册表：5 条 schema 都是 object + additionalProperties:false（与 py SPEC 同形）", () => {
  for (const spec of BUILTIN_TOOLS) {
    assert.equal(spec.inputSchema.type, "object", `${spec.name}.type`);
    assert.equal(
      spec.inputSchema.additionalProperties,
      false,
      `${spec.name}.additionalProperties 必须 false（py SPEC 逐字如此）`,
    );
    assert.ok(Array.isArray(spec.inputSchema.required), `${spec.name}.required 必须是数组`);
    assert.equal(typeof spec.inputSchema.properties, "object", `${spec.name}.properties`);
  }
});

test("A · code_exec：runtime 三值、**不进 required**、缺省 python（Q-4 泛化的裁定落点）", () => {
  assert.deepEqual([...CODE_EXEC_RUNTIMES], ["python", "node", "bash"]);
  assert.equal(CODE_EXEC_DEFAULT_RUNTIME, "python");
  assert.equal(
    CODE_EXEC_RUNTIMES[0],
    CODE_EXEC_DEFAULT_RUNTIME,
    "缺省值必须来自同一个常量（不得在别处再写一遍字面量）",
  );

  const codeExec = BUILTIN_TOOLS.find((spec) => spec.name === "code_exec");
  assert.ok(codeExec);
  const schema = codeExec.inputSchema;
  assert.deepEqual(schema.properties.runtime, { type: "string", enum: ["python", "node", "bash"] });
  assert.deepEqual(schema.required, ["code"], "runtime 不进 required（否则 py 的既有输入就不再合法）");
});

test("A · code_exec 的前两个键与 py 线 python 工具逐字相同（只多了一个 runtime）", () => {
  const codeExec = BUILTIN_TOOLS.find((spec) => spec.name === "code_exec");
  assert.ok(codeExec);
  // py: {"code": {"type":"string","minLength":1}, "timeout_ms": {"type":"integer","minimum":1}}
  assert.deepEqual(codeExec.inputSchema.properties.code, { type: "string", minLength: 1 });
  assert.deepEqual(codeExec.inputSchema.properties.timeout_ms, { type: "integer", minimum: 1 });
  assert.deepEqual(Object.keys(codeExec.inputSchema.properties), ["code", "timeout_ms", "runtime"]);
});

// ---------------------------------------------------------------------------
// B · 物化：幂等 + 逐字节一致 + 按租户
// ---------------------------------------------------------------------------

test("B · ensureBuiltinTools 首次：5 行 + 5 条 v1 版本行，写次数恰 10", async () => {
  const { connection, db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);

  const before = totalChanges(connection);
  const summary = await tools.ensureBuiltinTools();
  const writes = totalChanges(connection) - before;

  assert.deepEqual([...summary.inserted], BUILTIN_TOOLS.map((spec) => spec.name));
  assert.deepEqual([...summary.existing], []);
  assert.equal(summary.registered, 5);

  assert.equal(rawTools(connection, T_A).length, 5, "tool 行数 == 5");
  assert.equal(rawVersionCount(connection, T_A), 5, "tool_version 每工具 1 行（R3-23 ⑤）");
  assert.equal(writes, 10, "5 条 tool + 5 条 tool_version，不多不少（多一条说明有隐藏写）");
});

test("B · ensureBuiltinTools 第二次：仍 5 行，且**写次数为 0**（幂等的实证）", async () => {
  const { connection, db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);
  await tools.ensureBuiltinTools();

  const before = totalChanges(connection);
  const second = await tools.ensureBuiltinTools();
  const writes = totalChanges(connection) - before;

  assert.deepEqual([...second.inserted], [], "第二次不应插入任何行");
  assert.equal(second.existing.length, 5);
  assert.equal(rawTools(connection, T_A).length, 5, "行数仍 5（不是 10）");
  assert.equal(rawVersionCount(connection, T_A), 5, "版本行也没被重复插入");
  assert.equal(writes, 0, "这条锁的是**写次数**：任何 INSERT/UPDATE 都会让它红");
});

test("B · 落库的 input_schema 与注册表**逐字节一致**（SQLite 档比原始字符串）", async () => {
  const { connection, db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);
  await tools.ensureBuiltinTools();

  const rows = rawTools(connection, T_A);
  assert.equal(rows.length, 5);
  for (const spec of BUILTIN_TOOLS) {
    const row = rows.find((candidate) => candidate.name === spec.name);
    assert.ok(row, `库里缺 ${spec.name}`);
    assert.equal(
      row.input_schema,
      serializeBuiltinInputSchema(spec),
      `${spec.name}.input_schema 与注册表不逐字节一致 —— 说明落库前被重排/裁剪过`,
    );
  }
});

test("B · tool_version.spec 与注册表条目一致（v1 / 深等价）", async () => {
  const { connection, db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);
  await tools.ensureBuiltinTools();

  for (const spec of BUILTIN_TOOLS) {
    const row = rawTools(connection, T_A).find((candidate) => candidate.name === spec.name);
    const versions = await tools.listVersions(row.id);
    assert.equal(versions.length, 1, `${spec.name} 应恰有 1 条版本行`);
    assert.equal(versions[0].version, BUILTIN_TOOL_VERSION);
    assert.deepEqual(versions[0].spec, JSON.parse(serializeBuiltinToolSpec(spec)));
  }
});

test("B · 落库列口径：source/status/tenant_id + requires_sandbox 逐工具", async () => {
  const { connection, db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);
  await tools.ensureBuiltinTools();

  const expectedSandbox = {
    filesystem: false,
    git: true,
    http: false,
    shell: true,
    code_exec: true,
  };
  for (const row of rawTools(connection, T_A)) {
    assert.equal(row.source, TOOL_SOURCE_BUILTIN, `${row.name}.source`);
    assert.equal(row.status, TOOL_STATUS_ACTIVE, `${row.name}.status`);
    assert.equal(row.tenant_id, T_A, `${row.name}.tenant_id 必须按租户物化（R3-23 ①）`);
    assert.equal(
      Boolean(row.requires_sandbox),
      expectedSandbox[row.name],
      `${row.name}.requires_sandbox 与 py SPEC 不符`,
    );
  }
});

test("B · 权限动作借位 tool_ref：READ/WRITE/EXECUTE 逐工具（读取封在一处）", async () => {
  const { db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);
  await tools.ensureBuiltinTools();

  const expected = { filesystem: "READ", git: "WRITE", http: "EXECUTE", shell: "EXECUTE", code_exec: "EXECUTE" };
  const rows = await tools.list();
  assert.equal(rows.length, 5);
  for (const row of rows) {
    assert.equal(readToolPermissionAction(row), expected[row.name], `${row.name}.permission_action`);
  }
});

test("B · readToolPermissionAction：借位缺失 ⇒ 抛（宁可红，不猜动作）", () => {
  assert.throws(
    () => readToolPermissionAction({ name: "bogus", tool_ref: null }),
    /permission_action 缺失或非法/,
  );
  assert.throws(
    () => readToolPermissionAction({ name: "bogus", tool_ref: { permission_action: "DELETE" } }),
    /permission_action 缺失或非法/,
  );
});

test("B · toToolCatalogEntry：契约 8 字段，且 type ← source（映射只此一处）", async () => {
  const { db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);
  await tools.ensureBuiltinTools();
  const row = await tools.findByName("code_exec");
  const entry = toToolCatalogEntry(row);

  assert.deepEqual(Object.keys(entry).sort(), [
    "category",
    "description",
    "display_name",
    "id",
    "input_schema",
    "name",
    "requires_sandbox",
    "type",
  ]);
  assert.equal(entry.type, TOOL_SOURCE_BUILTIN);
  assert.equal(entry.type, row.source);
  assert.equal(entry.name, "code_exec");
  assert.equal(entry.requires_sandbox, true);
  assert.equal(entry.description, row.description);
});

// ---------------------------------------------------------------------------
// C · 隔离与自检（含常驻反例）
// ---------------------------------------------------------------------------

test("C · 按租户物化：B 租户各有 5 行，A 看不到 B 的", async () => {
  const { connection, db, scopeA, scopeB } = seed();
  const toolsA = new ToolRepo(db, scopeA, DIALECT);
  const toolsB = new ToolRepo(db, scopeB, DIALECT);

  await toolsA.ensureBuiltinTools();
  const bSummary = await toolsB.ensureBuiltinTools();
  assert.equal(bSummary.inserted.length, 5, "B 租户也要插自己那 5 行（不是复用 A 的）");

  assert.equal(rawTools(connection).length, 10, "两租户各 5 行");
  const listedA = await toolsA.list();
  assert.equal(listedA.length, 5);
  for (const row of listedA) assert.equal(row.tenant_id, T_A, "A 的 list 里不得出现 B 的行");
});

test("C · 手工造重复行（绕过 writer）⇒ findDuplicates 必非空 —— 常驻反例", async () => {
  const { connection, db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);
  await tools.ensureBuiltinTools();
  assert.deepEqual(await tools.findDuplicates(), [], "正常情况下本租户内不得有同名重复");

  // ① 已知弱点：`tool` **没有 (tenant_id, name) 唯一索引**（零 DDL）⇒ 原生 SQL 能插重复。
  //    这不是"我们允许重复"，而是"数据库拦不住，所以断言必须拦得住"。
  connection.raw.exec(
    `insert into tool (id, tenant_id, name, display_name, category, source, requires_sandbox, status) ` +
      `values ('99990000-0000-4000-8000-00000000000f', '${T_A}', 'git', 'Git', 'vcs', 'builtin', 1, 'active')`,
  );

  const duplicates = await tools.findDuplicates();
  assert.equal(duplicates.length, 2, "同名两行都要被报出来（`git` 原行 + 手工行）");
  assert.ok(duplicates.every((row) => row.name === "git"));
});

test("C · tenant_id 为空的行在本 scope 内不可见（「必须有租户」的兜底）", async () => {
  const { connection, db, scopeA } = seed();
  const tools = new ToolRepo(db, scopeA, DIALECT);
  await tools.ensureBuiltinTools();

  connection.raw.exec(
    `insert into tool (id, tenant_id, name, display_name, category, source, requires_sandbox, status) ` +
      `values ('99990000-0000-4000-8000-0000000000ff', null, 'platform_only', '平台级', 'system', 'builtin', 0, 'active')`,
  );

  const listed = await tools.list();
  assert.equal(listed.length, 5, "NULL tenant_id 的行走不进 scoped 查询");
  assert.equal(await tools.findByName("platform_only"), null, "按名字也查不到");
  assert.equal(rawTools(connection).length, 6, "但它在库里（证明上面是过滤掉了，不是没插进去）");
});
