/**
 * B2 · `mcp` 族行为证明（server / tool / permission 三族，SQLite 真库）。
 *
 * 判据（裁定 ⑥ + 硬约束 B + B1 判据纪律）：
 *   ① 三套值域**手写字面量**（transport 3 值 / action 3 值 / effect 2 值 + 三个缺省值）
 *      + 判定函数三层 + 非成员必 false；
 *   ② `dialect` 双档：三个类各一对 `columnType` 手写字面量；
 *   ③ server：`status` 缺省 `ACTIVE`、`transport` 缺省 `stdio`、`args` 缺省 `[]`、
 *      `env_ref` 缺省 `{}`、租户注入；非法 transport 抛；
 *   ④ tool：父域隔离（两个 server 各 1 条互不可见）+ 父不存在 ⇒ `ScopeError` 且不落库
 *      + `(server,name)` 重复**幂等**（跨实例：第二个实例发现同一工具不新增行、写次数 0）；
 *   ⑤ server `remove`：**先删子表**（FK 无级联）⇒ 断言 mcp_tool 归零、server 归零，
 *      且**另一个 server 的工具不受伤**（对照）；
 *   ⑥ permission：缺省 `EXECUTE` / `DENY`；`agent_id` 为 NULL 的"租户级默认权限"
 *      重复 grant ⇒ **同一行**（跨实例 + `total_changes()` 增量 0，硬约束 B）；
 *      不同 agent / 不同 action 各自新增。
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  MCP_DEFAULT_TRANSPORT,
  MCP_PERMISSION_ACTIONS,
  MCP_PERMISSION_DEFAULT_ACTION,
  MCP_PERMISSION_DEFAULT_EFFECT,
  MCP_PERMISSION_EFFECTS,
  MCP_SERVER_STATUS_ACTIVE,
  MCP_TOOL_STATUS_ACTIVE,
  MCP_TRANSPORTS,
  McpPermissionRepo,
  McpServerRepo,
  McpToolRepo,
  Scope,
  ScopeError,
  isMcpPermissionAction,
  isMcpPermissionEffect,
  isMcpTransport,
} from "../dist/repositories/index.js";

import { DIALECT, freshConnection, IDS, seedParents, T_A, T_B } from "./fixtures/runtime-fixture.mjs";

function seed() {
  const connection = freshConnection();
  seedParents(connection);
  return { connection, db: connection.db, scopeA: new Scope(T_A), scopeB: new Scope(T_B) };
}

/** 连接级写次数（`INSERT/UPDATE/DELETE` 递增，`SELECT` 不递增）。 */
function totalChanges(connection) {
  const row = connection.raw.prepare("select total_changes() as n").get();
  return Number(row.n);
}

function rawCount(connection, table) {
  return Number(connection.raw.prepare(`select count(*) as n from ${table}`).get().n);
}

/** 手写期望：传输方式（3 值全覆盖）。 */
const EXPECTED_TRANSPORT = { stdio: true, sse: true, http: true };
/** 手写期望：权限动作（3 值全覆盖）。 */
const EXPECTED_ACTION = { EXECUTE: true, READ: true, WRITE: true };
/** 手写期望：权限效果（2 值全覆盖）。 */
const EXPECTED_EFFECT = { ALLOW: true, DENY: true };

let seq = 0;
function newServer(repo, overrides = {}) {
  seq += 1;
  return repo.create({
    id: overrides.id ?? `a1000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    name: overrides.name ?? `server-${seq}`,
    endpoint: "http://localhost:7777/mcp",
    ...overrides,
  });
}

function newTool(repo, overrides = {}) {
  seq += 1;
  return repo.discover({
    id: overrides.id ?? `a2000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    name: overrides.name ?? `tool-${seq}`,
    inputSchema: { type: "object" },
    ...overrides,
  });
}

// ---------------------------------------------------------------------------
// A · 值域
// ---------------------------------------------------------------------------

test("A · 三套值域手写字面量 + 判定函数三层（非成员含大小写/尾空格）", () => {
  assert.deepEqual([...MCP_TRANSPORTS], ["stdio", "sse", "http"]);
  assert.equal(MCP_DEFAULT_TRANSPORT, "stdio");
  assert.equal(MCP_DEFAULT_TRANSPORT, MCP_TRANSPORTS[0], "缺省必须取自同一常量（不得另写一遍字面量）");

  assert.deepEqual([...MCP_PERMISSION_ACTIONS], ["EXECUTE", "READ", "WRITE"]);
  assert.equal(MCP_PERMISSION_DEFAULT_ACTION, "EXECUTE");
  assert.deepEqual([...MCP_PERMISSION_EFFECTS], ["ALLOW", "DENY"]);
  assert.equal(MCP_PERMISSION_DEFAULT_EFFECT, "DENY");

  assert.equal(MCP_SERVER_STATUS_ACTIVE, "ACTIVE");
  assert.equal(MCP_TOOL_STATUS_ACTIVE, "ACTIVE");

  assert.deepEqual(Object.keys(EXPECTED_TRANSPORT).sort(), [...MCP_TRANSPORTS].sort());
  assert.deepEqual(Object.keys(EXPECTED_ACTION).sort(), [...MCP_PERMISSION_ACTIONS].sort());
  assert.deepEqual(Object.keys(EXPECTED_EFFECT).sort(), [...MCP_PERMISSION_EFFECTS].sort());

  for (const value of MCP_TRANSPORTS) {
    assert.equal(isMcpTransport(value), EXPECTED_TRANSPORT[value], `isMcpTransport(${value})`);
    assert.equal(isMcpTransport(value), MCP_TRANSPORTS.includes(value));
  }
  for (const value of MCP_PERMISSION_ACTIONS) {
    assert.equal(isMcpPermissionAction(value), EXPECTED_ACTION[value], `isMcpPermissionAction(${value})`);
    assert.equal(isMcpPermissionAction(value), MCP_PERMISSION_ACTIONS.includes(value));
  }
  for (const value of MCP_PERMISSION_EFFECTS) {
    assert.equal(isMcpPermissionEffect(value), EXPECTED_EFFECT[value], `isMcpPermissionEffect(${value})`);
    assert.equal(isMcpPermissionEffect(value), MCP_PERMISSION_EFFECTS.includes(value));
  }

  for (const bogus of ["", "STDIO", "stdio ", "websocket"]) {
    assert.equal(isMcpTransport(bogus), false, `传输非成员：${JSON.stringify(bogus)}`);
  }
  for (const bogus of ["", "execute", "EXECUTE ", "DELETE"]) {
    assert.equal(isMcpPermissionAction(bogus), false, `动作非成员：${JSON.stringify(bogus)}`);
  }
  for (const bogus of ["", "allow", "DENY ", "ASK"]) {
    assert.equal(isMcpPermissionEffect(bogus), false, `效果非成员：${JSON.stringify(bogus)}`);
  }
});

// ---------------------------------------------------------------------------
// B · dialect 双档（三类各一对）
// ---------------------------------------------------------------------------

test("B · dialect 双档：server / tool / permission 的 columnType 手写字面量配对", () => {
  const { db, scopeA } = seed();

  const sqServer = new McpServerRepo(db, scopeA, "sqlite");
  const pgServer = new McpServerRepo(db, scopeA, "pg");
  assert.equal(sqServer.tableName, pgServer.tableName, "两档同名 ⇒ tableName 无判别力");
  assert.equal(sqServer.columns.status.columnType, "SQLiteText");
  assert.equal(pgServer.columns.status.columnType, "PgVarchar");
  assert.equal(sqServer.columns.args.columnType, "SQLiteTextJson");
  assert.equal(pgServer.columns.args.columnType, "PgJsonb");
  assert.equal(sqServer.columns.endpoint.columnType, "SQLiteText");
  assert.equal(pgServer.columns.endpoint.columnType, "PgVarchar");
  assert.notEqual(sqServer.columns.status.columnType, pgServer.columns.status.columnType);

  // tool 是子表：构造要先有一个 server ref（构造期不查库）
  const serverRef = scopeA.ref("a1000000-0000-4000-8000-0000000000ff");
  const sqTool = new McpToolRepo(db, scopeA, serverRef, "sqlite");
  const pgTool = new McpToolRepo(db, scopeA, serverRef, "pg");
  assert.equal(sqTool.tableName, "mcp_tool");
  assert.equal(sqTool.columns.input_schema.columnType, "SQLiteTextJson");
  assert.equal(pgTool.columns.input_schema.columnType, "PgJsonb");
  assert.equal(sqTool.columns.discovered_at.columnType, "SQLiteText");
  assert.equal(pgTool.columns.discovered_at.columnType, "PgTimestamp");

  const sqPerm = new McpPermissionRepo(db, scopeA, "sqlite");
  const pgPerm = new McpPermissionRepo(db, scopeA, "pg");
  assert.equal(sqPerm.columns.effect.columnType, "SQLiteText");
  assert.equal(pgPerm.columns.effect.columnType, "PgVarchar");
  assert.equal(sqPerm.columns.agent_id.columnType, "SQLiteText");
  assert.equal(pgPerm.columns.agent_id.columnType, "PgUUID");
  assert.notEqual(sqPerm.columns.agent_id.columnType, pgPerm.columns.agent_id.columnType);

  // 缺省档 = 生产档 pg（三类各查一次）
  assert.equal(new McpServerRepo(db, scopeA).columns.status.columnType, "PgVarchar");
  assert.equal(new McpPermissionRepo(db, scopeA).columns.effect.columnType, "PgVarchar");
  assert.equal(
    new McpToolRepo(db, scopeA, serverRef).columns.input_schema.columnType,
    "PgJsonb",
  );
});

// ---------------------------------------------------------------------------
// C · server
// ---------------------------------------------------------------------------

test("C · server.create：ACTIVE / stdio / args [] / env_ref {} 缺省 + 租户注入 + 非法 transport 抛", async () => {
  const { connection, db, scopeA } = seed();
  const servers = new McpServerRepo(db, scopeA, DIALECT);

  const created = await newServer(servers, { args: undefined, envRef: undefined });
  assert.equal(created.status, MCP_SERVER_STATUS_ACTIVE, "契约 default：ACTIVE");
  assert.equal(created.transport, MCP_DEFAULT_TRANSPORT, "契约 default：stdio");
  assert.deepEqual(created.args, [], "契约 args 是 array ⇒ 缺省 []");
  assert.deepEqual(created.env_ref, {}, "契约 env_ref 是 object ⇒ 缺省 {}");
  assert.equal(created.tenant_id, T_A);
  assert.equal(created.workspace_id, null, "workspace 未给 ⇒ null（scope 未锁 workspace 时不注入）");

  const row = connection.raw.prepare("select * from mcp_server where id = ?").get(created.id);
  assert.ok(row, "对照路径：行真的落库了");
  assert.equal(row.transport, "stdio");

  assert.ok(await servers.findByName(created.name), "按名字查得到");
  assert.equal(await servers.findByName("nope"), null);

  assert.throws(
    () => servers.create({ id: "x", name: "y", transport: "websocket" }),
    (error) => error instanceof ScopeError && /transport 必须是 stdio \| sse \| http/.test(error.message),
  );
});

test("C · server 跨租户隔离：B 的列表/按名查都看不到 A 的 server", async () => {
  const { db, scopeA, scopeB } = seed();
  const serversA = new McpServerRepo(db, scopeA, DIALECT);
  const serversB = new McpServerRepo(db, scopeB, DIALECT);
  const created = await newServer(serversA, { name: "shared-name" });

  assert.equal((await serversA.list()).length, 1, "对照路径：A 看得到");
  assert.deepEqual(await serversB.list(), [], "B 的列表不得出现 A 的行");
  assert.equal(await serversB.findById(scopeB.ref(created.id)), null);
  // 同名在**另一个租户**是允许的（uq 是 (tenant_id, name)）
  const bOwn = await newServer(serversB, { name: "shared-name" });
  assert.equal(bOwn.tenant_id, T_B);
});

// ---------------------------------------------------------------------------
// D · tool（子表）
// ---------------------------------------------------------------------------

test("D · tool.discover：ACTIVE 缺省 + 父域隔离（两个 server 互不可见）", async () => {
  const { connection, db, scopeA } = seed();
  const servers = new McpServerRepo(db, scopeA, DIALECT);
  const a = await newServer(servers, { name: "a" });
  const b = await newServer(servers, { name: "b" });
  const toolsA = new McpToolRepo(db, scopeA, scopeA.ref(a.id), DIALECT);
  const toolsB = new McpToolRepo(db, scopeA, scopeA.ref(b.id), DIALECT);

  const ta = await newTool(toolsA, { name: "search" });
  const tb = await newTool(toolsB, { name: "search" });
  assert.equal(ta.status, MCP_TOOL_STATUS_ACTIVE, "契约 default：ACTIVE");
  assert.equal(ta.mcp_server_id, a.id, "父由基类注入");
  assert.equal(tb.mcp_server_id, b.id);

  // 父域隔离：同一租户、同一个工具名，两个 server 各自只看到自己那条
  assert.deepEqual((await toolsA.list()).map((row) => row.id), [ta.id]);
  assert.deepEqual((await toolsB.list()).map((row) => row.id), [tb.id]);
  assert.equal((await toolsA.list()).length, 1, "对照路径：A 自己的工具查得到");
  assert.equal(rawCount(connection, "mcp_tool"), 2, "两条都在库里（只是互相看不见）");
});

test("D · tool：父 server 不存在 ⇒ ScopeError 且不落库（父不存在由基类首次使用校验挡住）", async () => {
  const { connection, db, scopeA } = seed();
  const ghost = scopeA.ref("a1000000-0000-4000-8000-00000000dead");
  const tools = new McpToolRepo(db, scopeA, ghost, DIALECT);

  await assert.rejects(
    () => newTool(tools, { name: "orphan" }),
    (error) => {
      assert.ok(error instanceof ScopeError, `必须是 ScopeError，实测 ${String(error)}`);
      assert.match(error.message, /父 mcp_server .* 在本 scope 下不可见/);
      return true;
    },
  );
  assert.equal(rawCount(connection, "mcp_tool"), 0, "父不可见时一行都不许落库");
});

test("D · tool.discover 幂等（跨实例）：重复发现同一工具 ⇒ 同一行、0 写", async () => {
  const { connection, db, scopeA } = seed();
  const servers = new McpServerRepo(db, scopeA, DIALECT);
  const server = await newServer(servers);
  const serverRef = scopeA.ref(server.id);

  const first = new McpToolRepo(db, scopeA, serverRef, DIALECT);
  const created = await newTool(first, { name: "list_files" });
  assert.equal(rawCount(connection, "mcp_tool"), 1);

  // 换一个实例再发现一次（跨实例，不是同实例自证）
  const second = new McpToolRepo(db, scopeA, serverRef, DIALECT);
  const before = totalChanges(connection);
  const again = await newTool(second, { name: "list_files", id: "a2000000-0000-4000-8000-00000000ffff" });
  const writes = totalChanges(connection) - before;

  assert.equal(again.id, created.id, "幂等 ⇒ 返回既有行，而不是新插一行");
  assert.equal(writes, 0, "任何 INSERT 都会让这条红（total_changes 增量必须为 0）");
  assert.equal(rawCount(connection, "mcp_tool"), 1, "行数仍 1（不是 2）");
});

// ---------------------------------------------------------------------------
// E · server.remove 必须先删子表（裁定 ⑥）
// ---------------------------------------------------------------------------

test("E · server.remove：先删子表再删自己；另一个 server 的工具不受伤", async () => {
  const { connection, db, scopeA } = seed();
  const servers = new McpServerRepo(db, scopeA, DIALECT);
  const doomed = await newServer(servers, { name: "doomed" });
  const survivor = await newServer(servers, { name: "survivor" });

  const doomedTools = new McpToolRepo(db, scopeA, scopeA.ref(doomed.id), DIALECT);
  const survivorTools = new McpToolRepo(db, scopeA, scopeA.ref(survivor.id), DIALECT);
  await newTool(doomedTools, { name: "t1" });
  await newTool(doomedTools, { name: "t2" });
  const keep = await newTool(survivorTools, { name: "keep" });
  assert.equal(rawCount(connection, "mcp_tool"), 3);

  assert.equal(await servers.remove(scopeA.ref(doomed.id)), true);

  assert.equal(rawCount(connection, "mcp_tool"), 1, "被删 server 的 2 个工具必须一起删掉（FK 无级联）");
  assert.equal(rawCount(connection, "mcp_server"), 1, "server 自己也删掉了");
  const left = connection.raw.prepare("select * from mcp_tool").all();
  assert.equal(left[0].id, keep.id, "另一个 server 的工具不得被误删（父谓词隔离）");
  assert.ok(await servers.findById(scopeA.ref(survivor.id)), "对照路径：另一个 server 还在");

  // 不存在 / 别的租户的 server ⇒ false（不抛）
  assert.equal(await servers.remove(scopeA.ref(doomed.id)), false);
});

// ---------------------------------------------------------------------------
// F · permission（硬约束 B：NULL agent_id 的唯一约束失效 ⇒ 应用层查重）
// ---------------------------------------------------------------------------

test("F · permission.grant：缺省 EXECUTE / DENY + 非法值抛", async () => {
  const { db, scopeA } = seed();
  const servers = new McpServerRepo(db, scopeA, DIALECT);
  const server = await newServer(servers);
  const tools = new McpToolRepo(db, scopeA, scopeA.ref(server.id), DIALECT);
  const tool = await newTool(tools, { name: "exec" });
  const perms = new McpPermissionRepo(db, scopeA, DIALECT);

  const granted = await perms.grant({ id: "a3000000-0000-4000-8000-000000000001", mcpToolId: tool.id });
  assert.equal(granted.action, MCP_PERMISSION_DEFAULT_ACTION, "契约 default：EXECUTE");
  assert.equal(granted.effect, MCP_PERMISSION_DEFAULT_EFFECT, "契约 default：DENY");
  assert.equal(granted.agent_id, null, "未给 agent ⇒ 租户级默认权限");
  assert.equal(granted.tenant_id, T_A);

  await assert.rejects(
    async () => perms.grant({ id: "x", mcpToolId: tool.id, action: "DELETE" }),
    (error) => error instanceof ScopeError && /action 必须是 EXECUTE \| READ \| WRITE/.test(error.message),
  );
  await assert.rejects(
    async () => perms.grant({ id: "x", mcpToolId: tool.id, effect: "ASK" }),
    (error) => error instanceof ScopeError && /effect 必须是 ALLOW \| DENY/.test(error.message),
  );
});

test("F · 租户级默认权限（agent_id IS NULL）重复 grant ⇒ 同一行、跨实例 0 写", async () => {
  const { connection, db, scopeA } = seed();
  const servers = new McpServerRepo(db, scopeA, DIALECT);
  const server = await newServer(servers);
  const tools = new McpToolRepo(db, scopeA, scopeA.ref(server.id), DIALECT);
  const tool = await newTool(tools, { name: "dangerous" });

  const a = new McpPermissionRepo(db, scopeA, DIALECT);
  const first = await a.grant({
    id: "a3000000-0000-4000-8000-0000000000a1",
    mcpToolId: tool.id,
    effect: "ALLOW",
  });
  assert.equal(rawCount(connection, "mcp_permission"), 1);

  // 另一个实例、另一个 id、同样的语义键 ⇒ 必须幂等
  const b = new McpPermissionRepo(db, scopeA, DIALECT);
  const before = totalChanges(connection);
  const second = await b.grant({
    id: "a3000000-0000-4000-8000-0000000000b2",
    mcpToolId: tool.id,
    effect: "ALLOW",
  });
  const writes = totalChanges(connection) - before;

  assert.equal(second.id, first.id, "NULL agent 的唯一约束失效 ⇒ 必须由应用层查重挡住（返回既有行）");
  assert.equal(writes, 0, "跨实例重复 grant 不得产生任何写");
  assert.equal(rawCount(connection, "mcp_permission"), 1, "库里只能有 1 行（出现 2 行 = 唯一约束在 NULL 上失效的漏洞）");
  assert.equal((await a.listTenantDefaults(tool.id)).length, 1);

  // 对照：**有** agent 的授权走唯一索引那一路，语义键不同 ⇒ 必须新增
  const withAgent = await b.grant({
    id: "a3000000-0000-4000-8000-0000000000c3",
    mcpToolId: tool.id,
    agentId: IDS.agentA,
    effect: "ALLOW",
  });
  assert.notEqual(withAgent.id, first.id);
  assert.equal(rawCount(connection, "mcp_permission"), 2);
  assert.equal((await a.listTenantDefaults(tool.id)).length, 1, "带 agent 的那条不算租户级默认权限");

  // 换 action 也是不同的语义键 ⇒ 新增第三条
  const readPerm = await b.grant({
    id: "a3000000-0000-4000-8000-0000000000d4",
    mcpToolId: tool.id,
    action: "READ",
    effect: "ALLOW",
  });
  assert.equal(rawCount(connection, "mcp_permission"), 3);
  assert.equal(readPerm.action, "READ");
});

test("F · permission.listByTool 父域隔离 + 跨租户不可见", async () => {
  const { connection, db, scopeA, scopeB } = seed();
  const servers = new McpServerRepo(db, scopeA, DIALECT);
  const server = await newServer(servers);
  const tools = new McpToolRepo(db, scopeA, scopeA.ref(server.id), DIALECT);
  const tool1 = await newTool(tools, { name: "one" });
  const tool2 = await newTool(tools, { name: "two" });

  const permsA = new McpPermissionRepo(db, scopeA, DIALECT);
  await permsA.grant({ id: "a3000000-0000-4000-8000-0000000000e1", mcpToolId: tool1.id });
  await permsA.grant({ id: "a3000000-0000-4000-8000-0000000000e2", mcpToolId: tool2.id });

  assert.equal((await permsA.listByTool(tool1.id)).length, 1, "只回该工具的授权");
  assert.equal((await permsA.listByTool(tool1.id))[0].mcp_tool_id, tool1.id);

  const permsB = new McpPermissionRepo(db, scopeB, DIALECT);
  assert.deepEqual(await permsB.listByTool(tool1.id), [], "B 看 A 的工具授权必须是空集");
  assert.equal(rawCount(connection, "mcp_permission"), 2, "两行都在库里（证明是过滤掉的）");
});
