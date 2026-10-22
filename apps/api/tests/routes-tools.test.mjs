/**
 * T3-12 · 工具目录 **1 op**（`GET /api/v1/tools`）的行为证明。
 *
 * 判据（任务卡验收 ③ + 反例「`GET /tools` 回落到 4 个 ⇒ 必红」）：
 *   ① **返回 5 个内置**，名字集合与注册表逐字相同，且**顺序 = 注册表顺序**
 *      （`filesystem / git / http / shell / code_exec`）—— py 返回的就是注册表顺序，
 *      差异会让"按下标取第 N 个工具"的调用方静默错位；
 *   ② **`code_exec` 在其中且 `requires_sandbox === true`**（含 `git` / `shell` 两条同理）；
 *   ③ **物化是幂等的**（R3-23）：连续两次 `GET` 后 `tool` 表行数不变，
 *      第二次的 `total_changes()` 增量为 **0**（"没有重复插入"的独立读数，不靠服务层自证）；
 *   ④ **8 键逐字**（契约 `ToolResponse`）；`input_schema` 是对象、`type === "builtin"`。
 *
 * 反例（注入即红）：
 *   - 把 `BUILTIN_TOOLS` 摘掉一项 ⇒ A-1 的 `length === 5` 与 C-1 的名字集合双红；
 *   - 把 `ensureBuiltinTools()` 从 `ToolService.list` 里删掉 ⇒ 空库下 A-1 变 `[]`（0 条），
 *     这正是"只读内存注册表"与"读物化表"两条实现的差别所在。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/routes-tools.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { OPERATION_SCHEMAS } from "../dist/routes/schemas.js";
import { errorOf, makeApp, request } from "./routes-harness.mjs";

/** 契约 `ToolResponse` 的 8 键（逐字）。 */
const TOOL_KEYS = [
  "category",
  "description",
  "display_name",
  "id",
  "input_schema",
  "name",
  "requires_sandbox",
  "type",
];

/** 注册表顺序（`packages/db/src/repositories/tool-repo.ts::BUILTIN_TOOLS`）。 */
const BUILTIN_NAMES = ["filesystem", "git", "http", "shell", "code_exec"];

/** 工具表行数（独立读数，绕开被测代码）。 */
function toolRows(fixture) {
  return fixture.raw.prepare("SELECT COUNT(*) AS n FROM tool").get().n;
}

/** `total_changes()`（SQLite 连接级写次数；用于证明"幂等 ⇒ 零写"）。 */
function totalChanges(fixture) {
  return fixture.raw.prepare("SELECT total_changes() AS n").get().n;
}

test("A-1 · GET /tools ⇒ 200 且**恰好 5 个**内置（不是 4 个）", async () => {
  const fixture = await makeApp({ username: "tool-a1" });
  try {
    const response = await request(fixture, "GET", "/api/v1/tools");
    assert.equal(response.statusCode, 200);
    const data = JSON.parse(response.body).data;
    assert.equal(Array.isArray(data), true);
    assert.equal(data.length, 5, "必须 5 个内置工具（少一个说明注册表漏项或物化失败）");
  } finally {
    await fixture.close();
  }
});

test("A-2 · 名字集合与**顺序**都与注册表逐字相同", async () => {
  const fixture = await makeApp({ username: "tool-a2" });
  try {
    const response = await request(fixture, "GET", "/api/v1/tools");
    const names = JSON.parse(response.body).data.map((tool) => tool.name);
    assert.deepEqual(names, BUILTIN_NAMES, "顺序必须等于注册表顺序（py 同口径）");
    assert.deepEqual([...names].sort(), [...BUILTIN_NAMES].sort(), "集合相等（无多无少）");
  } finally {
    await fixture.close();
  }
});

test("A-3 · `code_exec` 存在且 `requires_sandbox === true`；`filesystem` 为 false", async () => {
  const fixture = await makeApp({ username: "tool-a3" });
  try {
    const response = await request(fixture, "GET", "/api/v1/tools");
    const tools = JSON.parse(response.body).data;
    const byName = new Map(tools.map((tool) => [tool.name, tool]));

    const codeExec = byName.get("code_exec");
    assert.ok(codeExec !== undefined, "必须含 code_exec（Q-4 的内置工具）");
    assert.equal(codeExec.requires_sandbox, true, "code_exec 必须标 requires_sandbox=true");
    assert.equal(byName.get("shell").requires_sandbox, true);
    assert.equal(byName.get("git").requires_sandbox, true);
    assert.equal(byName.get("filesystem").requires_sandbox, false);
    assert.equal(byName.get("http").requires_sandbox, false);

    // `code_exec` 的 input_schema 要能表达 runtime 三档（python | node | bash）
    assert.equal(typeof codeExec.input_schema, "object");
    assert.notEqual(codeExec.input_schema, null);
    assert.ok(
      JSON.stringify(codeExec.input_schema).includes("runtime"),
      "code_exec 的 input_schema 应声明 runtime"
    );
  } finally {
    await fixture.close();
  }
});

test("A-4 · 8 键逐字 + `type === \"builtin\"` + `id` 非空", async () => {
  const fixture = await makeApp({ username: "tool-a4" });
  try {
    const response = await request(fixture, "GET", "/api/v1/tools");
    for (const tool of JSON.parse(response.body).data) {
      assert.deepEqual(Object.keys(tool).sort(), TOOL_KEYS, `${tool.name} 的键集合不符`);
      assert.equal(tool.type, "builtin");
      assert.equal(typeof tool.id, "string", "物化后的行必须有稳定 id（权限表要 FK 它）");
      assert.notEqual(tool.id, "");
      assert.equal(typeof tool.display_name, "string");
      assert.equal(typeof tool.description, "string");
      assert.equal(typeof tool.category, "string");
    }
  } finally {
    await fixture.close();
  }
});

test("B-1 · 物化幂等：两次 GET 后行数不变，且第二次**零写**（total_changes 不增）", async () => {
  const fixture = await makeApp({ username: "tool-b1" });
  try {
    const first = await request(fixture, "GET", "/api/v1/tools");
    assert.equal(first.statusCode, 200);
    assert.equal(toolRows(fixture), 5, "首次 GET 应把 5 个内置物化进 tool 表");

    const changesAfterFirst = totalChanges(fixture);
    const second = await request(fixture, "GET", "/api/v1/tools");
    assert.equal(second.statusCode, 200);
    assert.equal(toolRows(fixture), 5, "第二次不得再插一遍");

    // R3-23 ③ 的硬判据：第二次调用**写次数增量为 0**。
    // 为什么用 total_changes 而不是"看列表长度"：后者在"重复插入后去重"的实现下也会是 5，
    // 那样就测不出"到底有没有写"。
    assert.equal(
      totalChanges(fixture),
      changesAfterFirst,
      "第二次 GET 不得产生任何写入（幂等物化 ⇒ 零写）"
    );

    // 两次响应的 id 集合相同（物化后 id 稳定，不会每次都换 uuid）
    const idsFirst = JSON.parse(first.body).data.map((tool) => tool.id).sort();
    const idsSecond = JSON.parse(second.body).data.map((tool) => tool.id).sort();
    assert.deepEqual(idsSecond, idsFirst, "id 必须稳定");
  } finally {
    await fixture.close();
  }
});

test("B-2 · 工具目录按租户物化（别租户的行不混进来）", async () => {
  const fixture = await makeApp({ username: "tool-b2" });
  try {
    await request(fixture, "GET", "/api/v1/tools");
    // 直接给别租户插一行同名工具：本租户列表不得因它而变成 6 条
    fixture.raw
      .prepare(
        `INSERT INTO tool (id, tenant_id, name, display_name, description, category,
                           source, input_schema, requires_sandbox, status)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      )
      .run(
        "2f2f2f2f-0000-4000-8000-0000000000f2",
        "22222222-2222-4222-8222-222222222222",
        "foreign-tool",
        "别租户工具",
        "",
        "",
        "builtin",
        "{}",
        0,
        "active"
      );

    const response = await request(fixture, "GET", "/api/v1/tools");
    const names = JSON.parse(response.body).data.map((tool) => tool.name);
    assert.equal(names.length, 5, "别租户的工具行不得出现在本租户目录里");
    assert.equal(names.includes("foreign-tool"), false);
  } finally {
    await fixture.close();
  }
});

test("C-1 · 无令牌 ⇒ 401", async () => {
  const fixture = await makeApp({ username: "tool-c1" });
  try {
    const response = await fixture.app.inject({ method: "GET", url: "/api/v1/tools" });
    assert.equal(response.statusCode, 401);
    assert.equal(errorOf(response).code, "UNAUTHORIZED");
  } finally {
    await fixture.close();
  }
});

test("C-2 · operationId / method / path / 成功码与契约一致", () => {
  const entry = OPERATION_SCHEMAS["list_tools_api_v1_tools_get"];
  assert.ok(entry !== undefined, "缺少 list_tools_api_v1_tools_get");
  assert.equal(entry.method, "GET");
  assert.equal(entry.path, "/api/v1/tools");
  assert.equal(entry.successStatus, 200);
  assert.equal(entry.body, undefined, "契约该 op 无请求体");
});
