/**
 * T3-05 · Agent 族 **7 op** 的行为证明（真库 + `buildApp` + `app.inject`）。
 *
 * 判据（任务卡验收 ①–④ + 裁决 #2）：
 *   ① 7 op 全通（create 201 / list 分页 / get / put / publish 201 / run 200 / versions 200；
 *      run **只做入口与前置校验** —— `agent_run` 计数恒 0，执行归 T3-08）；
 *   ② 版本快照不可变：publish 后旧版本行**逐列不变**（raw 直读对照）；
 *   ③ `harness='coding'` ⇒ 422 + `reason_code='harness_unsupported'` 且 `agent_run`
 *      计数不变；缺省 ⇒ `general` ∧ `audit_log` 有 `agent.harness_routed`（R3-13）；
 *   ④ `run_mode` 非 INLINE ⇒ 422 + `run_mode_unsupported`（R3-06）；
 *   ⑤ PUT `status` 走状态机（裁决 #2）：非法迁移 / 词表外 ⇒ 422 +
 *      `agent_status_transition_invalid`，且**行未被改动**。
 *
 * 每个"查不到"的断言都配对照路径（同租户看得到），否则"空/404"可能只是"没插进去"。
 */

import assert from "node:assert/strict";
import test from "node:test";

import { RunRequestSchema } from "../dist/routes/schemas-run.js";
import { makeApp, OTHER_TENANT_ID, request } from "./routes-harness.mjs";
import { seedWorkspace, WORKSPACE_ID } from "./fixtures/run-fixture.mjs";

/** 契约 `RunResponse` 的 21 键（v0018 的 20 + v0019 的 `stop_reason`）。 */
const RUN_KEYS = [
  "agent_id",
  "agent_version_id",
  "completed_at",
  "conversation_id",
  "cost",
  "cost_status",
  "duration_ms",
  "error",
  "error_type",
  "id",
  "run_mode",
  "started_at",
  "status",
  "stop_reason",
  "success",
  "task_id",
  "tenant_id",
  "token_usage",
  "trace_id",
  "trigger",
  "user_id",
];

/** 终态集合（与 DDL 口径同源；此处只用于轮询退出条件）。 */
const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELLED"];

/**
 * 等 run 落到终态（后台驱动是异步的 ⇒ 断言前必须先等它收尾）。
 *
 * @param {object} fixture {@link makeApp} 产物（要 `raw`）。
 * @param {string} runId run 标识。
 * @param {number} [timeoutMs] 上限（缺省 15s；超时抛错并带上当前行，便于排障）。
 * @returns {Promise<Record<string, unknown>>} 终态行。
 */
async function waitForTerminal(fixture, runId, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const row = fixture.raw.prepare("select * from agent_run where id = ?").get(runId);
    if (row !== undefined && TERMINAL.includes(row.status)) return row;
    if (Date.now() > deadline) {
      throw new Error(`run ${runId} 在 ${timeoutMs}ms 内未到终态：${JSON.stringify(row)}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

/** 造一个 agent（真 HTTP 路由；返回响应 data）。 */
async function createAgent(fixture, overrides = {}) {
  const res = await request(fixture, "POST", "/api/v1/agents", {
    payload: { name: overrides.name ?? "测试 Agent", ...overrides },
  });
  assert.equal(res.statusCode, 201, res.body);
  return JSON.parse(res.body).data;
}

/** 发布一个版本（真 HTTP 路由）。 */
async function publish(fixture, agentId, overrides = {}) {
  const res = await request(fixture, "POST", `/api/v1/agents/${agentId}/publish`, {
    payload: overrides,
  });
  assert.equal(res.statusCode, 201, res.body);
  return JSON.parse(res.body).data;
}

/** 直读 agent 行（对照"库里到底有什么"）。 */
function rawAgent(raw, id) {
  return raw.prepare("select * from agent where id = ?").get(id);
}

/** 直读 agent_version 行。 */
function rawVersions(raw, agentId) {
  return raw.prepare("select * from agent_version where agent_id = ? order by id").all(agentId);
}

// ---------------------------------------------------------------------------
// A · create / list / get（op 1–3）
// ---------------------------------------------------------------------------

test("A · create：201 + DRAFT + type 缺省 PRIMARY + 无当前版本 + tenant_id 注入", async () => {
  const fixture = await makeApp({ username: "agent-a" });
  try {
    const created = await createAgent(fixture, { name: "部署排班", description: "描述" });
    assert.equal(created.status, "DRAFT", "契约：创建即 DRAFT");
    assert.equal(created.type, "PRIMARY", "契约 CreateAgentRequest.type default");
    assert.equal(created.current_version_id, null, "契约：无当前版本");
    assert.equal(created.tenant_id, fixture.userId ? "11111111-1111-4111-8111-111111111111" : null);
    assert.equal(created.created_by, fixture.userId, "created_by = 当前登录用户");

    const row = rawAgent(fixture.raw, created.id);
    assert.equal(row.status, "DRAFT", "对照：真的落库了");
  } finally {
    await fixture.close();
  }
});

test("A · create：缺 name ⇒ 422（契约 required）；非法 page / page_size ⇒ 422（不静默夹取）", async () => {
  const fixture = await makeApp({ username: "agent-b" });
  try {
    const noName = await request(fixture, "POST", "/api/v1/agents", { payload: {} });
    assert.equal(noName.statusCode, 422, noName.body);

    for (const [key, value] of [["page", "0"], ["page", "1.5"], ["page_size", "0"], ["page_size", "101"]]) {
      const res = await request(fixture, "GET", `/api/v1/agents?${key}=${value}`);
      assert.equal(res.statusCode, 422, `${key}=${value} 必须 422（${res.body}）`);
    }
    // 边界合法值不抛
    assert.equal((await request(fixture, "GET", "/api/v1/agents?page=1&page_size=100")).statusCode, 200);
  } finally {
    await fixture.close();
  }
});

test("A · list 分页：page/page_size 生效；get 未知 id ⇒ 404；跨租户 ⇒ 404（I-1）", async () => {
  const fixture = await makeApp({ username: "agent-c" });
  try {
    const a = await createAgent(fixture);
    await createAgent(fixture);

    const page1 = JSON.parse(
      (await request(fixture, "GET", "/api/v1/agents?page=1&page_size=1")).body,
    ).data;
    const page2 = JSON.parse(
      (await request(fixture, "GET", "/api/v1/agents?page=2&page_size=1")).body,
    ).data;
    assert.equal(page1.length, 1);
    assert.equal(page2.length, 1);
    assert.notEqual(page1[0].id, page2[0].id, "两页不得出现同一行");

    // 对照：本租户 get 得到；未知 id 与跨租户 id 都是 404（不区分，防存在性探测）
    const own = await request(fixture, "GET", `/api/v1/agents/${a.id}`);
    assert.equal(own.statusCode, 200);

    // 跨租户行：先造租户 B 的用户（agent.created_by 的 FK 需要真实 user 行）
    const crossUserId = "bbbb0000-0000-4000-8000-0000000000b2";
    fixture.raw
      .prepare(
        "insert into user (id, tenant_id, username, email, password_hash, display_name, is_active, is_superuser) " +
          "values (?, ?, 'bob', 'b@b.example', 'x', 'bob', 1, 0)",
      )
      .run(crossUserId, OTHER_TENANT_ID);
    const crossId = "bbbb0000-0000-4000-8000-0000000000b1";
    fixture.raw
      .prepare(
        "insert into agent (id, tenant_id, organization_id, workspace_id, name, description, type, status, current_version_id, created_by, created_at, updated_at) " +
          "values (?, ?, null, null, '隔壁', null, 'PRIMARY', 'DRAFT', null, ?, '2026-10-22 00:00:00', '2026-10-22 00:00:00')",
      )
      .run(crossId, OTHER_TENANT_ID, crossUserId);
    assert.ok(rawAgent(fixture.raw, crossId), "对照：跨租户行确实存在");

    for (const id of ["f0000000-0000-4000-8000-0000000000dead", crossId]) {
      const res = await request(fixture, "GET", `/api/v1/agents/${id}`);
      assert.equal(res.statusCode, 404);
      assert.equal(JSON.parse(res.body).code, "NOT_FOUND");
    }
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B · update（op 4）：缺省不变 / 元数据直改 / status 走状态机（裁决 #2）
// ---------------------------------------------------------------------------

test("B · PUT 缺省字段不变；name / description 直改生效", async () => {
  const fixture = await makeApp({ username: "agent-d" });
  try {
    const created = await createAgent(fixture);

    const untouched = await request(fixture, "PUT", `/api/v1/agents/${created.id}`, { payload: {} });
    assert.equal(untouched.statusCode, 200);
    assert.equal(JSON.parse(untouched.body).data.status, "DRAFT", "缺省字段不变");

    const updated = JSON.parse(
      (
        await request(fixture, "PUT", `/api/v1/agents/${created.id}`, {
          payload: { name: "改名", description: "新描述" },
        })
      ).body,
    ).data;
    assert.equal(updated.name, "改名");
    assert.equal(updated.description, "新描述");
    assert.equal(updated.status, "DRAFT", "没传 status 就不该动状态");
  } finally {
    await fixture.close();
  }
});

test("B · PUT status 走状态机：合法迁移成功；矩阵外 / 词表外 ⇒ 422 且行未变（裁决 #2）", async () => {
  const fixture = await makeApp({ username: "agent-e" });
  try {
    const created = await createAgent(fixture);
    const url = `/api/v1/agents/${created.id}`;

    // DRAFT → ACTIVE 合法
    const active = JSON.parse((await request(fixture, "PUT", url, { payload: { status: "ACTIVE" } })).body).data;
    assert.equal(active.status, "ACTIVE");

    // ACTIVE → DRAFT 矩阵外 ⇒ 422 + 内部 reason_code + 行未变
    const back = await request(fixture, "PUT", url, { payload: { status: "DRAFT" } });
    assert.equal(back.statusCode, 422, back.body);
    const backBody = JSON.parse(back.body);
    assert.equal(backBody.code, "VALIDATION_ERROR", "复用既有契约错误码，不新增");
    assert.equal(backBody.data.reason_code, "agent_status_transition_invalid");
    assert.equal(rawAgent(fixture.raw, created.id).status, "ACTIVE", "非法迁移不得改动行");

    // 词表外值 ⇒ 422 同形
    for (const bogus of ["active", "PUBLISHED", null]) {
      const res = await request(fixture, "PUT", url, { payload: { status: bogus } });
      assert.equal(res.statusCode, 422, `status=${String(bogus)} 必须 422`);
      assert.equal(JSON.parse(res.body).data.reason_code, "agent_status_transition_invalid");
    }

    // ACTIVE → ARCHIVED → ACTIVE 都是矩阵内的合法边
    assert.equal(
      JSON.parse((await request(fixture, "PUT", url, { payload: { status: "ARCHIVED" } })).body).data.status,
      "ARCHIVED",
    );
    assert.equal(
      JSON.parse((await request(fixture, "PUT", url, { payload: { status: "ACTIVE" } })).body).data.status,
      "ACTIVE",
    );

    // name + status 同时给：两个都生效（transition 在前，失败时元数据一字未动）
    const both = JSON.parse(
      (await request(fixture, "PUT", `/api/v1/agents/${created.id}`, { payload: { name: "新名", status: "ARCHIVED" } })).body,
    ).data;
    assert.equal(both.status, "ARCHIVED");
    assert.equal(both.name, "新名");

    // 不存在的 agent ⇒ 404（先于状态校验）
    const missing = await request(fixture, "PUT", "/api/v1/agents/f0000000-0000-4000-8000-0000000000dead", {
      payload: { status: "ACTIVE" },
    });
    assert.equal(missing.statusCode, 404);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// C · publish / versions（op 5 / 7）：一次发布 = 一个新行；快照不可变（验收 ②）
// ---------------------------------------------------------------------------

test("C · publish：201 + PUBLISHED + agent 转 ACTIVE + 指针回写；版本号缺省 v{n+1}", async () => {
  const fixture = await makeApp({ username: "agent-f" });
  try {
    const created = await createAgent(fixture);
    const v1 = await publish(fixture, created.id, { system_prompt: "第一版", model_config: { a: 1 } });
    assert.equal(v1.status, "PUBLISHED", "契约 AgentVersionResponse.status default");
    assert.equal(v1.version, "v1", "缺省版本号 = 既有版本数 + 1（py 同口径）");
    assert.deepEqual(v1.model_config, { a: 1 });

    const row = rawAgent(fixture.raw, created.id);
    assert.equal(row.current_version_id, v1.id, "发布后指针指向新版本");
    assert.equal(row.status, "ACTIVE", "发布即启用（py publish 实证路径）");

    const v2 = await publish(fixture, created.id, { version: "v9" });
    assert.equal(v2.version, "v9");
    assert.equal(rawVersions(fixture.raw, created.id).length, 2, "一次发布 = 一个新行");
  } finally {
    await fixture.close();
  }
});

test("C · 版本快照不可变（验收 ②）：第二次 publish 后旧版本行逐列不变", async () => {
  const fixture = await makeApp({ username: "agent-g" });
  try {
    const created = await createAgent(fixture);
    const v1 = await publish(fixture, created.id, { system_prompt: "第一版", runtime_config: { k: 1 } });
    const v2 = await publish(fixture, created.id, { system_prompt: "第二版" });

    const oldRow = rawVersions(fixture.raw, created.id).find((r) => r.id === v1.id);
    assert.equal(oldRow.version, v1.version, "旧版本号不变");
    assert.equal(oldRow.system_prompt, "第一版", "旧 system_prompt 不变");
    assert.deepEqual(JSON.parse(oldRow.runtime_config), { k: 1 }, "旧 runtime_config 不变");
    assert.equal(oldRow.status, "PUBLISHED", "旧版本 status 不变");
    assert.ok(oldRow.created_at, "旧版本行还在（未被删/未重建）");

    // GET versions：created_at 升序（同秒并列由 id 兜底 —— 时间戳由测试显式拉平，
    // 不靠运气：CURRENT_TIMESTAMP 秒粒度 + 版本 id 是随机 uuid）
    const stamp = (row, at) =>
      fixture.raw.prepare("update agent_version set created_at = ? where id = ?").run(at, row.id);
    const allRows = rawVersions(fixture.raw, created.id);
    stamp(allRows.find((r) => r.id === v1.id), "2026-10-22 00:00:01");
    stamp(allRows.find((r) => r.id === v2.id), "2026-10-22 00:00:02");
    const listed = JSON.parse((await request(fixture, "GET", `/api/v1/agents/${created.id}/versions`)).body).data;
    assert.equal(listed.length, 2);
    assert.deepEqual(listed.map((v) => v.system_prompt), ["第一版", "第二版"], "created_at 升序");

    // 全并列 ⇒ 次序由 id 兜底，且两次调用一致（稳定性，不假设具体次序）
    stamp(allRows.find((r) => r.id === v1.id), "2026-10-22 00:00:00");
    stamp(allRows.find((r) => r.id === v2.id), "2026-10-22 00:00:00");
    const tied = JSON.parse((await request(fixture, "GET", `/api/v1/agents/${created.id}/versions`)).body).data;
    const tiedAgain = JSON.parse((await request(fixture, "GET", `/api/v1/agents/${created.id}/versions`)).body).data;
    assert.deepEqual(tied.map((v) => v.id), tiedAgain.map((v) => v.id), "同参数两次调用次序必须一致");
    assert.deepEqual(
      tied.map((v) => v.id),
      [...tied.map((v) => v.id)].sort(),
      "时间全并列时次序 = id 升序",
    );

    // 发布不存在的 agent ⇒ 404
    const missing = await request(fixture, "POST", "/api/v1/agents/f0000000-0000-4000-8000-0000000000dead/publish", {
      payload: {},
    });
    assert.equal(missing.statusCode, 404);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// D · run（op 6）：只做入口与前置校验（验收 ③④；执行归 T3-08）
// ---------------------------------------------------------------------------

test("D · run 前置校验：无当前版本 ⇒ 422；AGENT 不存在 ⇒ 404；message 空 ⇒ 422", async () => {
  const fixture = await makeApp({ username: "agent-h" });
  try {
    const created = await createAgent(fixture);

    const noVersion = await request(fixture, "POST", `/api/v1/agents/${created.id}/run`, {
      payload: { message: "你好" },
    });
    assert.equal(noVersion.statusCode, 422, noVersion.body);

    const missing = await request(fixture, "POST", "/api/v1/agents/f0000000-0000-4000-8000-0000000000dead/run", {
      payload: { message: "你好" },
    });
    assert.equal(missing.statusCode, 404);

    await publish(fixture, created.id);
    const noMessage = await request(fixture, "POST", `/api/v1/agents/${created.id}/run`, { payload: {} });
    assert.equal(noMessage.statusCode, 422, "message 必填（py RunRequest.message 必填同口径）");
    const emptyMessage = await request(fixture, "POST", `/api/v1/agents/${created.id}/run`, {
      payload: { message: "   " },
    });
    assert.equal(emptyMessage.statusCode, 422, "空串 message 不得放行");
  } finally {
    await fixture.close();
  }
});

test("D · run 缺省 harness ⇒ general + 真建 run + audit_log 有 agent.harness_routed（R3-13 ②/⑤；T3-14 起）", async () => {
  // T3-14：run 入口不再返回 `execution:"deferred"` 回执，而是**真建 run**（21 键
  // `RunResponse`）并在后台驱动。故本用例需要 ① 一个真网关 ② 一个 workspace
  // （新建会话的 `conversation.workspace_id` NOT NULL）。
  const fixture = await makeApp({ username: "agent-i", model: true });
  try {
    seedWorkspace(fixture);
    const created = await createAgent(fixture);
    const version = await publish(fixture, created.id, { runtime_config: {} });

    const res = await request(fixture, "POST", `/api/v1/agents/${created.id}/run`, {
      payload: { message: "你好", workspace_id: WORKSPACE_ID },
    });
    assert.equal(res.statusCode, 200, res.body);
    const run = JSON.parse(res.body).data;
    assert.deepEqual(Object.keys(run).sort(), RUN_KEYS, "入口回执 = RunResponse 21 键（与 GET /runs/{id} 同形）");
    assert.equal(run.agent_id, created.id);
    assert.equal(run.agent_version_id, version.id);
    assert.ok(["QUEUED", "RUNNING", "SUCCEEDED"].includes(run.status), `实测 status=${run.status}`);

    // 对照：run 真的落库了（不是回执里编出来的一个 id）
    assert.equal(
      fixture.raw.prepare("select count(*) as n from agent_run where id = ?").get(run.id).n,
      1,
      "agent_run 必须真有一行（T3-14 前这里是 0）",
    );

    // R3-13 ⑤：audit_log 一行 agent.harness_routed，且 run_id / resource_id 指向真 run
    const audit = fixture.raw
      .prepare("select * from audit_log where action = 'agent.harness_routed'")
      .all();
    assert.equal(audit.length, 1, `实测 ${audit.length} 行`);
    assert.equal(audit[0].agent_id, created.id);
    assert.equal(audit[0].resource_type, "agent_run");
    assert.equal(audit[0].outcome, "success");
    assert.deepEqual(JSON.parse(audit[0].metadata).route_reason, "default");
    assert.equal(audit[0].run_id, run.id, "T3-05 遗留：run_id 不再是 null");
    assert.equal(audit[0].resource_id, run.id);

    // ---- 后台驱动收尾（终态 + model_finish）------------------------------
    const final = await waitForTerminal(fixture, run.id);
    assert.equal(final.status, "SUCCEEDED", JSON.stringify(final));
    assert.equal(final.stop_reason, "model_finish");
    // 12 帧里的 4 个主链帧必须真的发出来（其余见 e2e 的 12/7 双向断言）
    const channels = fixture.raw
      .prepare("select type from agent_event where run_id = ? order by seq")
      .all(run.id)
      .map((row) => row.type);
    for (const channel of ["agent.started", "agent.thinking", "message.delta", "agent.completed"]) {
      assert.ok(channels.includes(channel), `缺帧 ${channel}（实测 ${channels.join(",")}）`);
    }
  } finally {
    await fixture.close();
  }
});

test("D · run harness='coding' ⇒ 422 harness_unsupported 且 agent_run 计数不变（验收 ③）", async () => {
  const fixture = await makeApp({ username: "agent-j" });
  try {
    const created = await createAgent(fixture);
    await publish(fixture, created.id, { runtime_config: { harness: "coding" } });

    const res = await request(fixture, "POST", `/api/v1/agents/${created.id}/run`, {
      payload: { message: "你好" },
    });
    assert.equal(res.statusCode, 422, res.body);
    const body = JSON.parse(res.body);
    assert.equal(body.code, "VALIDATION_ERROR", "复用既有契约错误码，不新增");
    assert.equal(body.data.reason_code, "harness_unsupported", "R3-13 ③ 精确 reason");
    assert.equal(fixture.raw.prepare("select count(*) as n from agent_run").get().n, 0, "run 不创建");

    // audit 不得有成功路由（路由没成功）
    assert.equal(
      fixture.raw.prepare("select count(*) as n from audit_log where action = 'agent.harness_routed'").get().n,
      0,
    );
  } finally {
    await fixture.close();
  }
});

test("D · run run_mode 非 INLINE ⇒ 422 run_mode_unsupported（验收 ④ / R3-06）；未知会话 ⇒ 404", async () => {
  const fixture = await makeApp({ username: "agent-k" });
  try {
    const created = await createAgent(fixture);
    await publish(fixture, created.id);

    for (const runMode of ["BATCH", "CRON", "inline"]) {
      const res = await request(fixture, "POST", `/api/v1/agents/${created.id}/run`, {
        payload: { message: "你好", run_mode: runMode },
      });
      assert.equal(res.statusCode, 422, `run_mode=${runMode} 必须 422`);
      assert.equal(JSON.parse(res.body).data.reason_code, "run_mode_unsupported");
    }

    const noConv = await request(fixture, "POST", `/api/v1/agents/${created.id}/run`, {
      payload: { message: "你好", conversation_id: "f0000000-0000-4000-8000-0000000000dead" },
    });
    assert.equal(noConv.statusCode, 404, "会话不可见（不存在/跨租户）⇒ 404，不是 403");
  } finally {
    await fixture.close();
  }
});

test("D · RunRequest 契约面仍 4 键（R3-13 判据 ③：不许顺手加字段）", () => {
  const keys = Object.keys(RunRequestSchema.properties ?? {}).sort();
  assert.deepEqual(keys, ["conversation_id", "message", "run_mode", "workspace_id"]);
});
