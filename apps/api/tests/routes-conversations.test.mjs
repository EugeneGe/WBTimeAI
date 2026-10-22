/**
 * T3-07 · Conversation / Message **5 op** 的行为证明（真库 + `buildApp` + `app.inject`）。
 *
 * 判据（任务卡验收 ①–④ + 2 条反例）—— 每条都给出**可复跑的断言**：
 *   ① **5 op 全通**：`GET /conversations` 200 / `POST` 201 / `GET {id}` 200 /
 *      `PUT {id}` 200 / `GET {id}/messages` 200（A / B / C 组）；
 *   ② **跨租户 404**（I-1 口径延续）：别租户的会话在 get / put / messages 上都是
 *      **404 `NOT_FOUND`**，不是 403、也不是"空数组"（A-3 / B-2 / C-3 组，每组都带
 *      "本租户看得到"的对照，否则 404 可能只是"没插进去"）；
 *   ③ **消息分页稳定**：同一 `created_at` 内的先后由 `id` 决定，两次调用逐字一致，
 *      且**不丢行不重行**（C-2 组：直接用 raw 把 6 条消息的 `created_at` 拉平到同一秒）；
 *   ④ **消息写入幂等**：同一 `run_id` 重复提交 assistant 消息**不产生第二行**（D-1 组，
 *      走服务层入口 `ConversationService.appendMessage` —— 契约无消息写 op，故不挂路由）。
 *
 * 反例（注入复验见施工记录 T3-07 §5）：
 *   - 分页丢行/重行 ⇒ C-2 组必红（去掉 `id` 次序键后两次调用次序不再确定）；
 *   - `message` 写入绕过 conversation scope ⇒ D-2 组必红（去掉写路径的 scoped 父查询，
 *     跨租户会话也能被写入）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/routes-conversations.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { ConversationService } from "../dist/modules/conversation/service.js";
import {
  CreateConversationRequestSchema,
  OPERATION_SCHEMAS,
  UpdateConversationRequestSchema,
} from "../dist/routes/schemas.js";
import {
  makeApp,
  ORG_ID,
  OTHER_TENANT_ID,
  request,
  TENANT_ID,
} from "./routes-harness.mjs";

// ---------------------------------------------------------------------------
// 夹具 id（本文件专用，避免与其它测试撞车）
// ---------------------------------------------------------------------------

/** 本租户工作区。 */
const WORKSPACE_ID = "1d1d1d1d-0000-4000-8000-0000000000d1";

/** 别租户工作区。 */
const OTHER_WORKSPACE_ID = "2d2d2d2d-0000-4000-8000-0000000000d2";

/** 别租户用户。 */
const OTHER_USER_ID = "2e2e2e2e-0000-4000-8000-0000000000e2";

/** 别租户 agent。 */
const OTHER_AGENT_ID = "2a2a2a2a-0000-4000-8000-0000000000a2";

/** 别租户会话（跨租户 404 的靶子）。 */
const OTHER_CONVERSATION_ID = "2c2c2c2c-0000-4000-8000-0000000000c2";

/** 不存在的会话 id（"库里真的没有"的对照）。 */
const MISSING_CONVERSATION_ID = "f0000000-0000-4000-8000-0000000000de";

/** 消息测试用的 run id（服务层幂等键）。 */
const RUN_ID = "3a3a3a3a-0000-4000-8000-0000000000a3";

/** 契约 `ConversationResponse` 的 9 键（逐字，用于"多一键少一键都红"）。 */
const CONVERSATION_KEYS = [
  "agent_id",
  "created_at",
  "id",
  "status",
  "tenant_id",
  "title",
  "updated_at",
  "user_id",
  "workspace_id",
];

/** 契约 `ConversationMessageResponse` 的 8 键。 */
const MESSAGE_KEYS = [
  "content",
  "content_parts",
  "conversation_id",
  "created_at",
  "id",
  "role",
  "run_id",
  "token_count",
];

// ---------------------------------------------------------------------------
// 夹具助手
// ---------------------------------------------------------------------------

/** 插一个本租户工作区（`conversation.workspace_id` 是 NOT NULL + FK，必须有行）。 */
function seedWorkspace(fixture) {
  fixture.raw
    .prepare(
      "insert into workspace (id, tenant_id, organization_id, owner_id, name, workspace_type) " +
        "values (?, ?, ?, ?, '工作区 A', 'PERSONAL')",
    )
    .run(WORKSPACE_ID, TENANT_ID, ORG_ID, fixture.userId);
}

/**
 * 插一整套**别租户**的图（user → workspace / agent → conversation）。
 *
 * 为什么必须走 raw：跨租户行没法经本租户的 HTTP 路由造出来（那正是隔离的效果）。
 * 插完由 A-3 组断言"它确实存在"（对照），否则 404 的成因就无法区分。
 */
function seedOtherTenantGraph(fixture) {
  fixture.raw
    .prepare(
      "insert into user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser) " +
        "values (?, ?, 'conv-bob', 'conv-bob@b.example', 'x', 'bob', 1, 0)",
    )
    .run(OTHER_USER_ID, OTHER_TENANT_ID);
  fixture.raw
    .prepare(
      "insert into workspace (id, tenant_id, organization_id, owner_id, name, workspace_type) " +
        "values (?, ?, null, ?, '工作区 B', 'PERSONAL')",
    )
    .run(OTHER_WORKSPACE_ID, OTHER_TENANT_ID, OTHER_USER_ID);
  fixture.raw
    .prepare(
      "insert into agent (id, tenant_id, organization_id, workspace_id, name, description, type, status, " +
        "current_version_id, created_by, created_at, updated_at) " +
        "values (?, ?, null, null, '隔壁 Agent', null, 'PRIMARY', 'DRAFT', null, ?, " +
        "'2026-10-22 00:00:00', '2026-10-22 00:00:00')",
    )
    .run(OTHER_AGENT_ID, OTHER_TENANT_ID, OTHER_USER_ID);
  fixture.raw
    .prepare(
      "insert into conversation (id, tenant_id, organization_id, workspace_id, agent_id, user_id, title, status, " +
        "created_at, updated_at) " +
        "values (?, ?, null, ?, ?, ?, '隔壁会话', 'ACTIVE', '2026-10-22 00:00:00', '2026-10-22 00:00:00')",
    )
    .run(OTHER_CONVERSATION_ID, OTHER_TENANT_ID, OTHER_WORKSPACE_ID, OTHER_AGENT_ID, OTHER_USER_ID);
}

/** 造一个本租户 agent（走真 HTTP 路由 —— 会话的 `agent_id` 有 FK）。 */
async function createAgent(fixture) {
  const res = await request(fixture, "POST", "/api/v1/agents", { payload: { name: "会话测试 Agent" } });
  assert.equal(res.statusCode, 201, res.body);
  return JSON.parse(res.body).data;
}

/** 造一个本租户会话（走真 HTTP 路由）。 */
async function createConversation(fixture, agentId, overrides = {}) {
  const res = await request(fixture, "POST", "/api/v1/conversations", {
    payload: { agent_id: agentId, workspace_id: WORKSPACE_ID, ...overrides },
  });
  assert.equal(res.statusCode, 201, res.body);
  return JSON.parse(res.body).data;
}

/** 直插一条消息（`created_at` 由测试显式给 —— 秒粒度并列要靠这个拉平）。 */
function seedMessage(fixture, conversationId, { id, role = "user", content = "hi", createdAt, runId = null }) {
  fixture.raw
    .prepare(
      "insert into message (id, conversation_id, run_id, role, content, content_parts, token_count, created_at) " +
        "values (?, ?, ?, ?, ?, null, null, ?)",
    )
    .run(id, conversationId, runId, role, content, createdAt);
}

/** 某会话的消息行数（"到底写了几行"的对照口径）。 */
function countMessages(fixture, conversationId) {
  return fixture.raw.prepare("select count(*) as n from message where conversation_id = ?").get(conversationId).n;
}

/** 直读会话行（对照"库里到底有什么"）。 */
function rawConversation(fixture, id) {
  return fixture.raw.prepare("select * from conversation where id = ?").get(id);
}

// ---------------------------------------------------------------------------
// A · op 1–3：create / list / get（验收 ① ②）
// ---------------------------------------------------------------------------

test("A-1 · create：201 + 9 键逐字 + ACTIVE + tenant/user/workspace 归属 + 真落库", async () => {
  const fixture = await makeApp({ username: "conv-a1" });
  try {
    seedWorkspace(fixture);
    const agent = await createAgent(fixture);
    const created = await createConversation(fixture, agent.id, { title: "排班问答" });

    // 契约键集合：多一键（污染壳）/ 少一键（前端拿到 undefined）都红
    assert.deepEqual(Object.keys(created).sort(), CONVERSATION_KEYS);
    assert.equal(created.status, "ACTIVE", "契约 ConversationResponse.status default");
    assert.equal(created.tenant_id, TENANT_ID, "tenant_id 由 scope 注入");
    assert.equal(created.user_id, fixture.userId, "user_id = 当前登录用户（py 同口径）");
    assert.equal(created.workspace_id, WORKSPACE_ID);
    assert.equal(created.agent_id, agent.id);
    assert.equal(created.title, "排班问答");
    assert.match(created.created_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/, "ISO-8601（两档同形）");
    assert.match(created.updated_at, /^\d{4}-\d{2}-\d{2}T/);

    const row = rawConversation(fixture, created.id);
    assert.equal(row.title, "排班问答", "对照：真的落库了");
    assert.equal(row.tenant_id, TENANT_ID);
  } finally {
    await fixture.close();
  }
});

test("A-2 · create 校验：缺 agent_id ⇒ 422（契约 required）；workspace_id 空 ⇒ 422（py 服务层守卫）；超长 title ⇒ 422", async () => {
  const fixture = await makeApp({ username: "conv-a2" });
  try {
    seedWorkspace(fixture);
    const agent = await createAgent(fixture);

    const noAgent = await request(fixture, "POST", "/api/v1/conversations", {
      payload: { workspace_id: WORKSPACE_ID },
    });
    assert.equal(noAgent.statusCode, 422, "契约 CreateConversationRequest.required = agent_id");

    // 契约把 workspace_id 标成 default "" 且不在 required ⇒ schema 放行，由服务层挡
    for (const payload of [
      { agent_id: agent.id },
      { agent_id: agent.id, workspace_id: "" },
    ]) {
      const res = await request(fixture, "POST", "/api/v1/conversations", { payload });
      assert.equal(res.statusCode, 422, `workspace_id 缺失/空必须 422（${res.body}）`);
      const body = JSON.parse(res.body);
      assert.equal(body.code, "VALIDATION_ERROR", "复用既有契约错误码，不新增");
      assert.equal(body.data.field, "workspace_id", "py 同形：data.field 指出缺哪个字段");
    }

    const longTitle = await request(fixture, "POST", "/api/v1/conversations", {
      payload: { agent_id: agent.id, workspace_id: WORKSPACE_ID, title: "x".repeat(256) },
    });
    assert.equal(longTitle.statusCode, 422, "契约 title maxLength = 255");
  } finally {
    await fixture.close();
  }
});

test("A-3 · list：200 数组、本租户全量、跨租户不可见；契约无分页参数（page/page_size 被忽略而非 422）", async () => {
  const fixture = await makeApp({ username: "conv-a3" });
  try {
    seedWorkspace(fixture);
    seedOtherTenantGraph(fixture);
    const agent = await createAgent(fixture);
    const first = await createConversation(fixture, agent.id, { title: "会话一" });
    const second = await createConversation(fixture, agent.id, { title: "会话二" });

    const listed = JSON.parse((await request(fixture, "GET", "/api/v1/conversations")).body).data;
    assert.equal(Array.isArray(listed), true);
    assert.deepEqual(
      listed.map((item) => item.id).sort(),
      [first.id, second.id].sort(),
      "只列本租户两条；隔壁租户那条不得出现",
    );
    for (const item of listed) {
      assert.deepEqual(Object.keys(item).sort(), CONVERSATION_KEYS);
    }

    // 对照：隔壁租户的行确实存在（否则"看不见"无法区分于"没插进去"）
    assert.ok(rawConversation(fixture, OTHER_CONVERSATION_ID));

    // 契约 parameters=[] ⇒ 传分页参数是「无效果」，不是「422」也不是「截断」
    const paged = await request(fixture, "GET", "/api/v1/conversations?page=2&page_size=1");
    assert.equal(paged.statusCode, 200, paged.body);
    assert.equal(JSON.parse(paged.body).data.length, 2, "无分页语义：参数被忽略（不自造契约外行为）");

    // 次序稳定（updated_at desc + id asc 兜底：两次调用逐字一致）
    const again = JSON.parse((await request(fixture, "GET", "/api/v1/conversations")).body).data;
    assert.deepEqual(
      again.map((item) => item.id),
      listed.map((item) => item.id),
      "同参数两次调用次序必须一致",
    );
  } finally {
    await fixture.close();
  }
});

test("A-4 · get：200；未知 id / 跨租户 id ⇒ 404 NOT_FOUND（I-1：不是 403，不区分存在性）", async () => {
  const fixture = await makeApp({ username: "conv-a4" });
  try {
    seedWorkspace(fixture);
    seedOtherTenantGraph(fixture);
    const agent = await createAgent(fixture);
    const created = await createConversation(fixture, agent.id);

    const own = await request(fixture, "GET", `/api/v1/conversations/${created.id}`);
    assert.equal(own.statusCode, 200, own.body);
    assert.deepEqual(Object.keys(JSON.parse(own.body).data).sort(), CONVERSATION_KEYS);

    for (const id of [MISSING_CONVERSATION_ID, OTHER_CONVERSATION_ID]) {
      const res = await request(fixture, "GET", `/api/v1/conversations/${id}`);
      assert.equal(res.statusCode, 404, `${id} 必须 404（${res.body}）`);
      const body = JSON.parse(res.body);
      assert.equal(body.code, "NOT_FOUND", "跨租户不用 403（I-1 口径）");
      assert.equal(body.data.conversation_id, id);
    }
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B · op 4：PUT 只改 title（验收 ①②）
// ---------------------------------------------------------------------------

test("B-1 · PUT：title 生效 + updated_at 被推进；缺 title / 空串 / 超长 ⇒ 422", async () => {
  const fixture = await makeApp({ username: "conv-b1" });
  try {
    seedWorkspace(fixture);
    const agent = await createAgent(fixture);
    const created = await createConversation(fixture, agent.id, { title: "旧标题" });

    // 把 updated_at 拨到过去：rename 必须**显式**推进它（SQLite 无 ON UPDATE 触发器）
    fixture.raw
      .prepare("update conversation set updated_at = ? where id = ?")
      .run("2020-01-01 00:00:00", created.id);

    const renamed = JSON.parse(
      (await request(fixture, "PUT", `/api/v1/conversations/${created.id}`, {
        payload: { title: "新标题" },
      })).body,
    ).data;
    assert.equal(renamed.title, "新标题");
    assert.notEqual(renamed.updated_at, "2020-01-01T00:00:00.000Z", "rename 必须推进 updated_at");
    assert.deepEqual(Object.keys(renamed).sort(), CONVERSATION_KEYS);
    assert.equal(rawConversation(fixture, created.id).title, "新标题", "对照：真的改到库里了");

    for (const payload of [{}, { title: "" }, { title: "x".repeat(256) }]) {
      const res = await request(fixture, "PUT", `/api/v1/conversations/${created.id}`, { payload });
      assert.equal(res.statusCode, 422, `payload=${JSON.stringify(payload)} 必须 422`);
    }
    assert.equal(rawConversation(fixture, created.id).title, "新标题", "422 不得改动行");
  } finally {
    await fixture.close();
  }
});

test("B-2 · PUT 跨租户 / 不存在 ⇒ 404 且隔壁行标题一字未变（验收 ②）", async () => {
  const fixture = await makeApp({ username: "conv-b2" });
  try {
    seedWorkspace(fixture);
    seedOtherTenantGraph(fixture);

    for (const id of [MISSING_CONVERSATION_ID, OTHER_CONVERSATION_ID]) {
      const res = await request(fixture, "PUT", `/api/v1/conversations/${id}`, {
        payload: { title: "越权改名" },
      });
      assert.equal(res.statusCode, 404, `${id} 必须 404（${res.body}）`);
      assert.equal(JSON.parse(res.body).code, "NOT_FOUND");
    }
    assert.equal(
      rawConversation(fixture, OTHER_CONVERSATION_ID).title,
      "隔壁会话",
      "跨租户写入必须一行都不落地",
    );
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// C · op 5：messages（验收 ③ 分页稳定）
// ---------------------------------------------------------------------------

test("C-1 · messages：空会话 ⇒ 200 []；字段 8 键、content_parts 缺省回落 []", async () => {
  const fixture = await makeApp({ username: "conv-c1" });
  try {
    seedWorkspace(fixture);
    const agent = await createAgent(fixture);
    const created = await createConversation(fixture, agent.id);

    const empty = await request(fixture, "GET", `/api/v1/conversations/${created.id}/messages`);
    assert.equal(empty.statusCode, 200, empty.body);
    assert.deepEqual(JSON.parse(empty.body).data, [], "无消息 ⇒ 空数组（不是 404）");

    seedMessage(fixture, created.id, {
      id: "4b4b4b4b-0000-4000-8000-0000000000b1",
      role: "user",
      content: "你好",
      createdAt: "2026-10-22 00:00:01",
    });
    const listed = JSON.parse(
      (await request(fixture, "GET", `/api/v1/conversations/${created.id}/messages`)).body,
    ).data;
    assert.equal(listed.length, 1);
    assert.deepEqual(Object.keys(listed[0]).sort(), MESSAGE_KEYS);
    assert.deepEqual(listed[0].content_parts, [], "列值为 null ⇒ 契约要求 array ⇒ 回落 []");
    assert.equal(listed[0].token_count, null, "未统计 ≠ 统计为 0");
    assert.equal(listed[0].run_id, null);
    assert.equal(listed[0].conversation_id, created.id);
  } finally {
    await fixture.close();
  }
});

test("C-2 · 分页稳定（验收 ③）：同 created_at 用 id 作次序键 —— 不丢行、不重行、两次调用逐字一致", async () => {
  const fixture = await makeApp({ username: "conv-c2" });
  try {
    seedWorkspace(fixture);
    const agent = await createAgent(fixture);
    const created = await createConversation(fixture, agent.id);

    // ① 6 条**同一秒**（CURRENT_TIMESTAMP 秒粒度下的真实形态）+ 2 条更早的
    const tied = [
      "4c4c4c4c-0000-4000-8000-0000000000c9",
      "4c4c4c4c-0000-4000-8000-0000000000c3",
      "4c4c4c4c-0000-4000-8000-0000000000c7",
      "4c4c4c4c-0000-4000-8000-0000000000c1",
      "4c4c4c4c-0000-4000-8000-0000000000c5",
      "4c4c4c4c-0000-4000-8000-0000000000c2",
    ];
    // 故意**乱序**插入：若次序由插入时间/rowid 决定，下面期望值就不可能对上
    for (const id of tied) {
      seedMessage(fixture, created.id, {
        id,
        role: "user",
        content: `并列 ${id.slice(-2)}`,
        createdAt: "2026-10-22 00:00:05",
      });
    }
    const earlier = ["4d4d4d4d-0000-4000-8000-0000000000d2", "4d4d4d4d-0000-4000-8000-0000000000d1"];
    for (const id of earlier) {
      seedMessage(fixture, created.id, {
        id,
        role: "assistant",
        content: `更早 ${id.slice(-2)}`,
        createdAt: "2026-10-22 00:00:01",
      });
    }

    const first = JSON.parse(
      (await request(fixture, "GET", `/api/v1/conversations/${created.id}/messages`)).body,
    ).data;
    const second = JSON.parse(
      (await request(fixture, "GET", `/api/v1/conversations/${created.id}/messages`)).body,
    ).data;

    // A) 不丢行、不重行：条数与集合都对得上（分页反例的第一半）
    assert.equal(first.length, tied.length + earlier.length, "行数必须等于插入数（丢行即红）");
    assert.equal(new Set(first.map((m) => m.id)).size, first.length, "不得出现重复行（重行即红）");
    assert.deepEqual(
      first.map((m) => m.id).sort(),
      [...tied, ...earlier].sort(),
      "集合必须与插入集合逐字相等",
    );

    // B) 次序是数据的函数：(created_at asc, id asc)
    const expected = [...earlier].sort().concat([...tied].sort());
    assert.deepEqual(first.map((m) => m.id), expected, "次序必须是 (created_at asc, id asc)");

    // C) 稳定性：同参数两次调用逐字一致（分页反例的第二半 —— 不稳定就必然丢/重）
    assert.deepEqual(second.map((m) => m.id), first.map((m) => m.id), "两次调用次序必须一致");

    // D) 交叉验证："同秒并列段"内部确实是 id 升序（而不是碰巧按 rowid 排的）
    const tiedSlice = first.filter((m) => m.role === "user").map((m) => m.id);
    assert.deepEqual(tiedSlice, [...tiedSlice].sort(), "同秒记录的次序键 = id 升序");
  } finally {
    await fixture.close();
  }
});

test("C-3 · messages 跨租户 / 不存在 ⇒ 404（不是空数组）", async () => {
  const fixture = await makeApp({ username: "conv-c3" });
  try {
    seedWorkspace(fixture);
    seedOtherTenantGraph(fixture);
    // 隔壁会话里塞一条消息：若隔离失效，它就会出现在响应里
    seedMessage(fixture, OTHER_CONVERSATION_ID, {
      id: "4e4e4e4e-0000-4000-8000-0000000000e1",
      role: "user",
      content: "隔壁的消息",
      createdAt: "2026-10-22 00:00:01",
    });

    for (const id of [MISSING_CONVERSATION_ID, OTHER_CONVERSATION_ID]) {
      const res = await request(fixture, "GET", `/api/v1/conversations/${id}/messages`);
      assert.equal(res.statusCode, 404, `${id} 必须 404（不是空数组：${res.body}）`);
      assert.equal(JSON.parse(res.body).code, "NOT_FOUND");
    }
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// D · 消息写入：幂等（验收 ④）+ 不得绕过 conversation scope（反例 ②）
// ---------------------------------------------------------------------------

/**
 * 造一条本租户的 `agent_run`（`message.run_id` 的 FK 靶子）。
 *
 * 走真 HTTP publish 拿 `agent_version_id`（FK 要求版本行真实存在），再 raw 插 run：
 * run 的创建归 T3-08，本卡只需要一个"合法的 run_id"来验证幂等键。
 */
async function seedRun(fixture, agent, conversationId) {
  const published = await request(fixture, "POST", `/api/v1/agents/${agent.id}/publish`, {
    payload: { system_prompt: "会话测试" },
  });
  assert.equal(published.statusCode, 201, published.body);
  const version = JSON.parse(published.body).data;
  fixture.raw
    .prepare(
      "insert into agent_run (id, tenant_id, agent_id, agent_version_id, conversation_id, user_id, trigger, " +
        "run_mode, status, tool_error_count, cost_estimated, cost_status) values " +
        "(?, ?, ?, ?, ?, ?, 'USER', 'INLINE', 'COMPLETED', 0, 0, 'SKIPPED')",
    )
    .run(RUN_ID, TENANT_ID, agent.id, version.id, conversationId, fixture.userId);
}

test("D-1 · 幂等（验收 ④）：同一 run_id 重复提交 assistant 消息不产生第二行", async () => {
  const fixture = await makeApp({ username: "conv-d1" });
  try {
    seedWorkspace(fixture);
    const agent = await createAgent(fixture);
    const created = await createConversation(fixture, agent.id);
    await seedRun(fixture, agent, created.id);

    const service = new ConversationService({ db: fixture.connection.db, dialect: "sqlite" });

    // ★ 口径④ 的**可直调入口**：`appendAssistantMessage(tenantId, input)`（QA / T3-08 用同一个）。
    //   入参是纯值对象（`AppendAssistantMessageInput`），**不含任何 HTTP 请求/回复对象** ——
    //   T3-08 的 RunEventWriter 直接构造即可，不需要经过 Fastify。
    const payload = {
      conversation_id: created.id,
      run_id: RUN_ID,
      content: "你好，我是助手",
    };

    const first = await service.appendAssistantMessage(TENANT_ID, payload);
    const second = await service.appendAssistantMessage(TENANT_ID, payload);
    const third = await service.appendAssistantMessage(TENANT_ID, { ...payload, content: "换一段文本" });

    assert.equal(first.created, true, "首次必须真的插入");
    assert.equal(second.created, false, "第二次命中幂等键 ⇒ 不插入");
    assert.equal(third.created, false, "同一 (会话, run, role) 恒定幂等，与 content 无关");
    assert.equal(second.message.id, first.message.id, "返回的必须是**既有**那一行");
    assert.equal(third.message.id, first.message.id);
    assert.equal(countMessages(fixture, created.id), 1, "库里必须只有 1 行（幂等的硬判据）");

    // 幂等键的边界（文档化）：换个 run_id ⇒ 新行；role=user 同 run ⇒ 新行（幂等只覆盖 assistant）
    const otherRun = await service.appendMessage(TENANT_ID, {
      conversation_id: created.id,
      role: "assistant",
      run_id: null,
      content: "无 run 的助手回执",
    });
    assert.equal(otherRun.created, true, "run_id 为空 ⇒ 无幂等键 ⇒ 正常追加");
    const userSameRun = await service.appendMessage(TENANT_ID, {
      conversation_id: created.id,
      role: "user",
      run_id: RUN_ID,
      content: "我的手打",
    });
    assert.equal(userSameRun.created, true, "user 消息不参与 assistant 幂等（同一 run 的用户输入必须能落）");
    assert.equal(countMessages(fixture, created.id), 3);

    // 契约面：写入结果是 8 键视图
    assert.deepEqual(Object.keys(first.message).sort(), MESSAGE_KEYS);
    assert.equal(first.message.run_id, RUN_ID);
    assert.equal(first.message.role, "assistant");
    // 读路径（op 5）能看到这三行，且次序 = (created_at, id)
    const listed = JSON.parse(
      (await request(fixture, "GET", `/api/v1/conversations/${created.id}/messages`)).body,
    ).data;
    assert.equal(listed.length, 3);
    assert.equal(
      listed.filter((m) => m.content === "你好，我是助手").length,
      1,
      "读侧也只看到 1 行 assistant（幂等在读侧同样可见）",
    );
  } finally {
    await fixture.close();
  }
});

test("D-2 · 反例：message 写入绕过 conversation scope ⇒ 必须被拦（404 且一行不写）", async () => {
  const fixture = await makeApp({ username: "conv-d2" });
  try {
    seedWorkspace(fixture);
    seedOtherTenantGraph(fixture);
    const agent = await createAgent(fixture);
    const mine = await createConversation(fixture, agent.id);

    const service = new ConversationService({ db: fixture.connection.db, dialect: "sqlite" });

    // ① 跨租户会话：本租户 scope 下不可见 ⇒ 404，且**一行都不许写进隔壁会话**
    await assert.rejects(
      () =>
        service.appendMessage(TENANT_ID, {
          conversation_id: OTHER_CONVERSATION_ID,
          role: "assistant",
          content: "越权写入",
          run_id: null,
        }),
      (error) => {
        assert.equal(error.statusCode, 404, "跨租户写入必须是 404（不是 403、不是静默成功）");
        assert.equal(error.code, "NOT_FOUND");
        assert.deepEqual(error.data, { conversation_id: OTHER_CONVERSATION_ID });
        return true;
      },
    );
    assert.equal(countMessages(fixture, OTHER_CONVERSATION_ID), 0, "隔壁会话必须一行都没有");

    // ② 不存在的会话：同样 404（与①同形，防存在性探测）
    await assert.rejects(
      () =>
        service.appendMessage(TENANT_ID, {
          conversation_id: MISSING_CONVERSATION_ID,
          role: "user",
          content: "无主消息",
          run_id: null,
        }),
      (error) => error.statusCode === 404,
    );

    // ③ 对照：本租户自己的会话写得进去（否则①②的 404 可能只是"整个写路径坏了"）
    const ok = await service.appendMessage(TENANT_ID, {
      conversation_id: mine.id,
      role: "user",
      content: "正常写入",
      run_id: null,
    });
    assert.equal(ok.created, true);
    assert.equal(countMessages(fixture, mine.id), 1);

    // ④ 跨会话不串流：隔壁会话的消息数仍是 0（写路径没顺手漏到别处）
    assert.equal(countMessages(fixture, OTHER_CONVERSATION_ID), 0);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// E · 契约面核查（5 op 逐字）+ 范围红线（无 DELETE / 无消息写路由）
// ---------------------------------------------------------------------------

test("E-1 · 契约面：5 op 的 operationId / method / path / 成功码 / 键集合逐字对齐", () => {
  const expected = [
    ["list_conversations_api_v1_conversations_get", "GET", "/api/v1/conversations", 200],
    ["create_conversation_api_v1_conversations_post", "POST", "/api/v1/conversations", 201],
    ["get_conversation_api_v1_conversations__conversation_id__get", "GET", "/api/v1/conversations/{conversation_id}", 200],
    ["update_conversation_api_v1_conversations__conversation_id__put", "PUT", "/api/v1/conversations/{conversation_id}", 200],
    [
      "list_messages_api_v1_conversations__conversation_id__messages_get",
      "GET",
      "/api/v1/conversations/{conversation_id}/messages",
      200,
    ],
  ];
  for (const [operationId, method, path, successStatus] of expected) {
    const op = OPERATION_SCHEMAS[operationId];
    assert.ok(op !== undefined, `schema 字典缺 ${operationId}`);
    assert.equal(op.method, method);
    assert.equal(op.path, path);
    assert.equal(op.successStatus, successStatus);
  }

  // 响应键集合（数组 op 取 items）
  const conv = OPERATION_SCHEMAS.get_conversation_api_v1_conversations__conversation_id__get.response;
  assert.deepEqual(Object.keys(conv.properties).sort(), CONVERSATION_KEYS);
  const list = OPERATION_SCHEMAS.list_conversations_api_v1_conversations_get.response;
  assert.deepEqual(Object.keys(list.items.properties).sort(), CONVERSATION_KEYS);
  const messages = OPERATION_SCHEMAS.list_messages_api_v1_conversations__conversation_id__messages_get.response;
  assert.deepEqual(Object.keys(messages.items.properties).sort(), MESSAGE_KEYS);

  // 请求体必填集合（契约：create 只 required agent_id；update 只 required title）
  assert.deepEqual([...CreateConversationRequestSchema.required], ["agent_id"]);
  assert.deepEqual(Object.keys(CreateConversationRequestSchema.properties).sort(), [
    "agent_id",
    "title",
    "workspace_id",
  ]);
  assert.deepEqual([...UpdateConversationRequestSchema.required], ["title"]);
  assert.deepEqual(Object.keys(UpdateConversationRequestSchema.properties), ["title"]);
});

test("E-2 · 范围红线：无 DELETE 会话、无消息写路由（契约无 ⇒ 不许有）", async () => {
  const fixture = await makeApp({ username: "conv-e2" });
  try {
    assert.equal(
      fixture.app.hasRoute({ method: "DELETE", url: "/api/v1/conversations/:conversation_id" }),
      false,
      "契约 5 op 里没有 DELETE ⇒ 不许注册",
    );
    assert.equal(
      fixture.app.hasRoute({ method: "POST", url: "/api/v1/conversations/:conversation_id/messages" }),
      false,
      "契约没有消息写 op ⇒ 服务层入口不挂路由",
    );

    // 运行期证据（不只是路由表）：两条路径都是 404 Route not found
    seedWorkspace(fixture);
    const agent = await createAgent(fixture);
    const created = await createConversation(fixture, agent.id);
    for (const [method, url] of [
      ["DELETE", `/api/v1/conversations/${created.id}`],
      ["POST", `/api/v1/conversations/${created.id}/messages`],
    ]) {
      const res = await request(fixture, method, url, { payload: { content: "x" } });
      assert.equal(res.statusCode, 404, `${method} ${url} 不该存在（${res.body}）`);
    }
    assert.equal(rawConversation(fixture, created.id).id, created.id, "会话仍在（没被删）");
  } finally {
    await fixture.close();
  }
});
