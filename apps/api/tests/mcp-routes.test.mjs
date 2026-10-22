/**
 * T3-11 · MCP 8 op 的行为证明（真库 + `buildApp` + `app.inject`）。
 *
 * 判据（卡面验收 ① ② + 反例①）
 * ------------------------
 *   ① **8 op 全通**，成功码逐字（DELETE 是 **204 零字节**，不是 200）；
 *   ② **discover 幂等物化**（验收 ②）：同一个 server 连续两次 discover，
 *      `mcp_tool` 行数不变、`discovered_at` 更新 —— 走**真链路**
 *      （HTTP → service → 真 SDK → 手写假 server）；
 *   ③ **权限创建幂等**：同 `(tool, agent, action)` 二次创建 ⇒ 返回同一行（不是 201 新行）；
 *   ④ **跨租户 404**（I-1）；**反例①** 的静态面（MCP service 不得绕过 ToolExecutor）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/mcp-routes.test.mjs`
 */

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";

import {
  errorOf,
  makeApp,
  OTHER_TENANT_ID,
  request,
  ROOT,
} from "./routes-harness.mjs";

/** 手写假 MCP server（与 `mcp-client.test.mjs` 同款；只覆盖 initialize / tools/list）。 */
const FAKE_SERVER_SCRIPT = `
let buf = "";
process.stdin.setEncoding("utf8");
let calls = 0;
process.stdin.on("data", (chunk) => {
  buf += chunk;
  let index;
  while ((index = buf.indexOf("\\n")) >= 0) {
    const line = buf.slice(0, index).trim();
    buf = buf.slice(index + 1);
    if (line === "") continue;
    let message;
    try { message = JSON.parse(line); } catch { continue; }
    if (message.method === "initialize") {
      reply(message.id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "fake-mcp", version: "0.0.1" },
      });
    } else if (message.method === "tools/list") {
      calls += 1;
      reply(message.id, {
        tools: [
          { name: "echo", description: "回声", inputSchema: { type: "object", properties: { text: { type: "string" } } } },
          { name: "count", description: "计数", inputSchema: { type: "object" } },
        ],
      });
    }
  }
});
function reply(id, result) {
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, result }) + "\\n");
}
`;

/** 造假 server 脚本。 */
function makeFakeServer() {
  const dir = mkdtempSync(join(tmpdir(), "wb-mcp-r-"));
  const scriptPath = join(dir, "fake-mcp-server.mjs");
  writeFileSync(scriptPath, FAKE_SERVER_SCRIPT, "utf8");
  return { command: process.execPath, args: [scriptPath], cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

/** 直接插一条别租户的 MCP server（跨租户 404 靶子）。 */
function seedOtherServer(fixture) {
  const id = "5a5a5a5a-0000-4000-8000-0000000000a5";
  fixture.raw
    .prepare(
      `insert into mcp_server (id, tenant_id, name, transport, command, args, endpoint, credential_id,
                                env_ref, status, created_at, updated_at)
       values (?, ?, ?, 'stdio', 'x', '[]', NULL, NULL, '{}', 'ACTIVE', '2026-10-22 00:00:00', '2026-10-22 00:00:00')`
    )
    .run(id, OTHER_TENANT_ID, "other-server");
  return id;
}

// ---------------------------------------------------------------------------
// A 组 · server 目录（op 1–4）
// ---------------------------------------------------------------------------

test("A-1 · 注册 ⇒ 201 + 12 键；缺 name ⇒ 422；transport 非法 ⇒ 422", async () => {
  const fixture = await makeApp({ username: "mcp-a1" });
  try {
    const created = await request(fixture, "POST", "/api/v1/mcp/servers", {
      payload: { name: "local-tools", transport: "stdio", command: "node", args: ["server.mjs"] },
    });
    assert.equal(created.statusCode, 201);
    const data = JSON.parse(created.body).data;
    assert.deepEqual(Object.keys(data).sort(), [
      "args", "command", "created_at", "credential_id", "endpoint", "env_ref",
      "id", "name", "status", "tenant_id", "transport", "workspace_id",
    ]);
    assert.equal(data.status, "ACTIVE");
    assert.deepEqual(data.args, ["server.mjs"]);

    const noName = await request(fixture, "POST", "/api/v1/mcp/servers", {
      payload: { name: "", transport: "stdio" },
    });
    assert.equal(noName.statusCode, 422);

    const badTransport = await request(fixture, "POST", "/api/v1/mcp/servers", {
      payload: { name: "x", transport: "carrier-pigeon" },
    });
    assert.equal(badTransport.statusCode, 422);
    assert.equal(errorOf(badTransport).data.field, "transport");
  } finally {
    await fixture.close();
  }
});

test("A-2 · 详情 / 列表 / 删除（**204 零字节**）全链路", async () => {
  const fixture = await makeApp({ username: "mcp-a2" });
  try {
    const created = await request(fixture, "POST", "/api/v1/mcp/servers", {
      payload: { name: "to-delete", transport: "stdio", command: "x" },
    });
    const id = JSON.parse(created.body).data.id;

    const detail = await request(fixture, "GET", `/api/v1/mcp/servers/${id}`);
    assert.equal(detail.statusCode, 200);
    assert.equal(JSON.parse(detail.body).data.name, "to-delete");

    const list = await request(fixture, "GET", "/api/v1/mcp/servers");
    assert.equal(JSON.parse(list.body).data.length, 1);

    const removed = await fixture.app.inject({
      method: "DELETE",
      url: `/api/v1/mcp/servers/${id}`,
      headers: { authorization: fixture.authHeader },
    });
    assert.equal(removed.statusCode, 204, "契约成功码是 204");
    assert.equal(removed.body, "", "204 必须零字节（J-10）");

    const gone = await request(fixture, "GET", `/api/v1/mcp/servers/${id}`);
    assert.equal(gone.statusCode, 404);
  } finally {
    await fixture.close();
  }
});

test("A-3 · 跨租户 / 不存在 ⇒ 404 `NOT_FOUND`", async () => {
  const fixture = await makeApp({ username: "mcp-a3" });
  try {
    const otherId = seedOtherServer(fixture);

    const cross = await request(fixture, "GET", `/api/v1/mcp/servers/${otherId}`);
    assert.equal(cross.statusCode, 404);
    assert.equal(errorOf(cross).code, "NOT_FOUND");

    const crossDelete = await fixture.app.inject({
      method: "DELETE",
      url: `/api/v1/mcp/servers/${otherId}`,
      headers: { authorization: fixture.authHeader },
    });
    assert.equal(crossDelete.statusCode, 404, "跨租户删除不得落到别租户的行上");

    // 对照：那一行还在
    assert.equal(
      fixture.raw.prepare("select count(*) as n from mcp_server where id = ?").get(otherId).n,
      1
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B 组 · discover（验收 ②）—— **真链路**：HTTP → 真 SDK → 假 server
// ---------------------------------------------------------------------------

test("B-1 · discover ⇒ 200 + 物化 2 个工具；**两次 discover 行数不变**（幂等）", async () => {
  const fixture = await makeApp({ username: "mcp-b1" });
  const fake = makeFakeServer();
  try {
    const created = await request(fixture, "POST", "/api/v1/mcp/servers", {
      payload: { name: "fake", transport: "stdio", command: fake.command, args: fake.args },
    });
    const serverId = JSON.parse(created.body).data.id;

    const first = await request(fixture, "POST", `/api/v1/mcp/servers/${serverId}/discover`);
    assert.equal(first.statusCode, 200);
    const tools = JSON.parse(first.body).data;
    assert.equal(tools.length, 2);
    assert.deepEqual(
      tools.map((tool) => tool.name).sort(),
      ["count", "echo"]
    );
    assert.ok(tools[0].discovered_at !== null);
    assert.deepEqual(Object.keys(tools[0]).sort(), [
      "description", "discovered_at", "id", "input_schema", "mcp_server_id", "name", "output_schema", "status",
    ]);

    const rowsAfterFirst = fixture.raw.prepare("select count(*) as n from mcp_tool").get().n;
    assert.equal(rowsAfterFirst, 2);

    const second = await request(fixture, "POST", `/api/v1/mcp/servers/${serverId}/discover`);
    assert.equal(second.statusCode, 200);
    const rowsAfterSecond = fixture.raw.prepare("select count(*) as n from mcp_tool").get().n;
    assert.equal(
      rowsAfterSecond,
      rowsAfterFirst,
      "第二次 discover 不得产生新行（幂等物化，验收 ②）"
    );

    // GET /mcp/tools 聚合返回
    const list = await request(fixture, "GET", "/api/v1/mcp/tools");
    assert.equal(JSON.parse(list.body).data.length, 2);

    // server_id 过滤
    const filtered = await request(fixture, "GET", `/api/v1/mcp/tools?server_id=${serverId}`);
    assert.equal(JSON.parse(filtered.body).data.length, 2);
  } finally {
    fake.cleanup();
    await fixture.close();
  }
});

test("B-2 · discover 连不上的 server ⇒ 502 系错误（INTERNAL_ERROR，不是 500 裸抛）", async () => {
  const fixture = await makeApp({ username: "mcp-b2" });
  const dir = mkdtempSync(join(tmpdir(), "wb-mcp-"));
  const silent = join(dir, "silent.mjs");
  writeFileSync(silent, "setInterval(() => {}, 1000);\n", "utf8");
  try {
    const created = await request(fixture, "POST", "/api/v1/mcp/servers", {
      payload: { name: "silent", transport: "stdio", command: process.execPath, args: [silent] },
    });
    const serverId = JSON.parse(created.body).data.id;

    const result = await request(fixture, "POST", `/api/v1/mcp/servers/${serverId}/discover`);
    assert.equal(result.statusCode, 500, "core 码表无独立 upstream 码 ⇒ INTERNAL_ERROR 映射 500（不新增码）");
    assert.equal(errorOf(result).code, "INTERNAL_ERROR");
    assert.match(errorOf(result).message, /discover 失败/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// C 组 · 权限（op 7–8）
// ---------------------------------------------------------------------------

test("C-1 · 权限创建 ⇒ 201；**同键二次创建返回同一行**（幂等，不是 201 新行）", async () => {
  const fixture = await makeApp({ username: "mcp-c1" });
  const fake = makeFakeServer();
  try {
    const created = await request(fixture, "POST", "/api/v1/mcp/servers", {
      payload: { name: "fake", transport: "stdio", command: fake.command, args: fake.args },
    });
    const serverId = JSON.parse(created.body).data.id;
    await request(fixture, "POST", `/api/v1/mcp/servers/${serverId}/discover`);
    const tools = JSON.parse((await request(fixture, "GET", "/api/v1/mcp/tools")).body).data;
    const toolId = tools[0].id;

    const first = await request(fixture, "POST", "/api/v1/mcp/permissions", {
      payload: { mcp_tool_id: toolId, action: "EXECUTE", effect: "ALLOW" },
    });
    assert.equal(first.statusCode, 201);
    const firstData = JSON.parse(first.body).data;
    assert.deepEqual(Object.keys(firstData).sort(), [
      "action", "agent_id", "agent_version_id", "created_at", "effect", "id", "mcp_tool_id", "scope", "tenant_id",
    ]);

    const second = await request(fixture, "POST", "/api/v1/mcp/permissions", {
      payload: { mcp_tool_id: toolId, action: "EXECUTE", effect: "ALLOW" },
    });
    assert.equal(second.statusCode, 201, "幂等命中仍返回 201（契约没有 200 语义）");
    assert.equal(JSON.parse(second.body).data.id, firstData.id, "必须是同一行");

    // 非法 action ⇒ 422
    const bad = await request(fixture, "POST", "/api/v1/mcp/permissions", {
      payload: { mcp_tool_id: toolId, action: "DROP" },
    });
    assert.equal(bad.statusCode, 422);
  } finally {
    fake.cleanup();
    await fixture.close();
  }
});

test("C-2 · `GET /mcp/permissions` 的 `mcp_tool_id` **必填**；不存在的 tool ⇒ 空数组（契约未说 404）", async () => {
  const fixture = await makeApp({ username: "mcp-c2" });
  try {
    const missing = await request(fixture, "GET", "/api/v1/mcp/permissions");
    assert.equal(missing.statusCode, 422, "缺必填 query ⇒ 422");

    const ghost = await request(
      fixture,
      "GET",
      "/api/v1/mcp/permissions?mcp_tool_id=5b5b5b5b-0000-4000-8000-0000000000b5"
    );
    assert.equal(ghost.statusCode, 200);
    assert.deepEqual(JSON.parse(ghost.body).data, []);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// D 组 · 认证 + 反例①静态面
// ---------------------------------------------------------------------------

test("D-1 · 8 op 无令牌 ⇒ 401", async () => {
  const fixture = await makeApp({ username: "mcp-d1" });
  try {
    const cases = [
      ["GET", "/api/v1/mcp/servers"],
      ["POST", "/api/v1/mcp/servers"],
      ["GET", "/api/v1/mcp/servers/f0000000-0000-4000-8000-0000000000de"],
      ["DELETE", "/api/v1/mcp/servers/f0000000-0000-4000-8000-0000000000de"],
      ["POST", "/api/v1/mcp/servers/f0000000-0000-4000-8000-0000000000de/discover"],
      ["GET", "/api/v1/mcp/tools"],
      ["GET", "/api/v1/mcp/permissions?mcp_tool_id=x"],
      ["POST", "/api/v1/mcp/permissions"],
    ];
    for (const [method, url] of cases) {
      const response = await fixture.app.inject({ method, url });
      assert.equal(response.statusCode, 401, `${method} ${url} 无令牌必须 401`);
      assert.equal(errorOf(response).code, "UNAUTHORIZED");
    }
  } finally {
    await fixture.close();
  }
});

test("D-2 · 反例①静态：`callTool` 只能出现在 adapter（唯一执行出口）", () => {
  const serviceSource = readFileSync(
    join(ROOT, "apps/api/src/modules/mcp/service.ts"),
    "utf8"
  );
  const adapterSource = readFileSync(
    join(ROOT, "apps/api/src/modules/mcp/adapter.ts"),
    "utf8"
  );

  // 服务层只管目录 CRUD（8 op），**不得**出现执行出口 —— 否则就绕过了 ToolExecutor。
  assert.equal(
    serviceSource.includes("callTool"),
    false,
    "McpService 出现了 callTool —— 执行必须只走 adapter（卡面反例①）"
  );
  // adapter 是唯一经 MCP 协议执行的地方（它产出 ToolOutcome，交给 ToolExecutor 第 4 段映射）。
  assert.ok(
    adapterSource.includes("callTool"),
    "adapter.ts 必须包含 callTool（唯一执行出口断言失效 ⇒ 断言本身坏了）"
  );
});
