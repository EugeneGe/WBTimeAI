/**
 * T3-12 · Approval **4 op** 的行为证明（真库 + `buildApp` + `app.inject`）。
 *
 * 判据（任务卡验收 ①–④ + 反例）—— 每条都给出**可复跑的断言**：
 *   ① **4 op 全通**：`GET /approvals` 200 / `GET {id}` 200 / `POST approve` 200 /
 *      `POST reject` 200（A / B / C / D 组）；
 *   ② **列表只返 `PENDING`**：插一条 `APPROVED` 的对照行，列表里**不得**出现（A-2）；
 *   ③ **分页是契约的**：`limit`(1..200, 缺省 50) / `offset`(≥0) 真实生效（A-3 / A-4），
 *      越界 ⇒ **422**（A-5）—— 这是全仓唯一带分页参数的列表 op，不能只做样子；
 *   ④ **二次决议 ⇒ 409 `CONFLICT`**（不是幂等返回、不是 500）：
 *      approve 两次 / approve 后 reject / reject 两次，三种都断 409 + `data.status`
 *      （C-2 / C-3 / D-2）。**不得**自造错误码，也**不得**返回原行把"别人早批了"
 *      伪装成"我刚批的"；
 *   ⑤ **决议不触发执行**（卡面反例）：两个面
 *      - 静态：`routes/approvals.ts` 与 `modules/approval/service.ts` 的源码里
 *        **不得**出现任何执行器 / 沙箱 / AgentLoop 标识（E-1，读文件断言）；
 *      - 行为：决议前后 `tool_call` 表行数不变（E-2，决议只改状态与时间戳）；
 *   ⑥ **认证面**：4 op 无令牌 ⇒ **401**；未认证 + 非法 query ⇒ **仍是 401**
 *      （`preValidation` 早于 schema 校验，F 组）。
 *
 * 反例（注入即红）：
 *   - 「approve 直接调执行器」：在 `routes/approvals.ts` 里 import 任一执行器标识 ⇒
 *     E-1 的静态断言立刻变红（这是"审批与执行分离"的机器可读形态）；
 *   - 「二次决议做成幂等返回」：把 409 分支改成 `return current` ⇒ C-2/C-3/D-2 三红。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/routes-approvals.test.mjs`
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import test from "node:test";

import { OPERATION_SCHEMAS } from "../dist/routes/schemas.js";
import {
  errorOf,
  makeApp,
  OTHER_TENANT_ID,
  request,
  ROOT,
  TENANT_ID,
} from "./routes-harness.mjs";

// ---------------------------------------------------------------------------
// 夹具
// ---------------------------------------------------------------------------

/** 契约 `ApprovalResponse` 的 12 键（逐字；多一键少一键都红）。 */
const APPROVAL_KEYS = [
  "created_at",
  "decided_at",
  "decided_by",
  "expires_at",
  "id",
  "payload",
  "requested_by",
  "status",
  "subject_ref",
  "subject_type",
  "tenant_id",
  "updated_at",
];

/**
 * 直接插一条 approval 行。
 *
 * 为什么不经服务层：本卡**没有**创建审批的 op（契约 4 条 path 全是读 / 决议），
 * 审批行由 run 的审批挂点产生（T3-13）。测试要验"读"与"决议"，就得自己造行
 * —— 用 raw 插是最短路径，且**不依赖**被测代码。
 *
 * @param fixture 夹具（需要 `raw`）。
 * @param overrides 覆盖字段（id / status / tenant_id）。
 * @returns 插入的 id。
 */
function seedApproval(fixture, overrides = {}) {
  const id = overrides.id ?? randomUUID();
  const status = overrides.status ?? "PENDING";
  const tenantId = overrides.tenant_id ?? TENANT_ID;
  const createdAt = overrides.created_at ?? "2026-10-22 00:00:00";
  fixture.raw
    .prepare(
      `INSERT INTO approval
         (id, tenant_id, subject_type, subject_ref, requested_by, status,
          decided_by, decided_at, payload, expires_at, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(
      id,
      tenantId,
      overrides.subject_type ?? "tool_call",
      overrides.subject_ref ?? randomUUID(),
      null,
      status,
      status === "PENDING" ? null : null,
      status === "PENDING" ? null : createdAt,
      "{}",
      null,
      createdAt,
      createdAt
    );
  return id;
}

/** 取某表的行数（绕开被测代码的独立读数）。 */
function countRows(fixture, table) {
  return fixture.raw.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n;
}

// ---------------------------------------------------------------------------
// A 组 · 列表（只返 PENDING + 分页）
// ---------------------------------------------------------------------------

test("A-1 · GET /approvals ⇒ 200 数组（空库 ⇒ []）", async () => {
  const fixture = await makeApp({ username: "appr-a1" });
  try {
    const response = await request(fixture, "GET", "/api/v1/approvals");
    assert.equal(response.statusCode, 200);
    const data = JSON.parse(response.body).data;
    assert.ok(Array.isArray(data), "响应 data 必须是数组");
    assert.equal(data.length, 0);
  } finally {
    await fixture.close();
  }
});

test("A-2 · 列表**只**返 PENDING：APPROVED / REJECTED 的行不得出现", async () => {
  const fixture = await makeApp({ username: "appr-a2" });
  try {
    const pending = seedApproval(fixture);
    const approved = seedApproval(fixture, { status: "APPROVED" });
    const rejected = seedApproval(fixture, { status: "REJECTED" });

    const response = await request(fixture, "GET", "/api/v1/approvals");
    assert.equal(response.statusCode, 200);
    const ids = JSON.parse(response.body).data.map((row) => row.id);
    assert.deepEqual(ids, [pending], "只应有 PENDING 那一条");
    assert.ok(!ids.includes(approved), "APPROVED 不得出现在待办列表");
    assert.ok(!ids.includes(rejected), "REJECTED 不得出现在待办列表");

    // 对照：决议过的行仍可经**详情**端点取到（"列表过滤"不等于"行不存在"）
    const detail = await request(fixture, "GET", `/api/v1/approvals/${approved}`);
    assert.equal(detail.statusCode, 200, "详情端点必须能取到已决议的行");
    assert.equal(JSON.parse(detail.body).data.status, "APPROVED");
  } finally {
    await fixture.close();
  }
});

test("A-3 · 分页真实生效：limit / offset 改变返回集合（契约唯一带分页的列表 op）", async () => {
  const fixture = await makeApp({ username: "appr-a3" });
  try {
    const ids = [
      seedApproval(fixture, { created_at: "2026-10-22 00:00:01" }),
      seedApproval(fixture, { created_at: "2026-10-22 00:00:02" }),
      seedApproval(fixture, { created_at: "2026-10-22 00:00:03" }),
    ];

    const all = await request(fixture, "GET", "/api/v1/approvals");
    assert.equal(JSON.parse(all.body).data.length, 3);

    const page1 = await request(fixture, "GET", "/api/v1/approvals?limit=2");
    const page1Ids = JSON.parse(page1.body).data.map((row) => row.id);
    assert.equal(page1Ids.length, 2, "limit=2 必须只回 2 条");
    // 次序 = created_at 倒序（`#page` 的口径）⇒ 最新的两条
    assert.deepEqual(page1Ids, [ids[2], ids[1]]);

    const page2 = await request(fixture, "GET", "/api/v1/approvals?limit=2&offset=2");
    const page2Ids = JSON.parse(page2.body).data.map((row) => row.id);
    assert.deepEqual(page2Ids, [ids[0]], "offset=2 只剩第 3 条");

    // 两页无交集（分页不得重行）
    assert.equal(
      page1Ids.filter((id) => page2Ids.includes(id)).length,
      0,
      "两页不得重叠"
    );

    // 缺省值：不给参数 ⇒ limit=50 / offset=0（契约 default）
    const missing = await request(fixture, "GET", "/api/v1/approvals?offset=0");
    assert.equal(JSON.parse(missing.body).data.length, 3);
  } finally {
    await fixture.close();
  }
});

test("A-4 · limit / offset 越界 ⇒ 422（不静默夹取）", async () => {
  const fixture = await makeApp({ username: "appr-a4" });
  try {
    for (const query of ["limit=0", "limit=201", "offset=-1"]) {
      const response = await request(fixture, "GET", `/api/v1/approvals?${query}`);
      assert.equal(response.statusCode, 422, `${query} 必须 422，实测 ${response.statusCode}`);
      assert.equal(errorOf(response).code, "VALIDATION_ERROR");
    }
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B 组 · 详情（404 口径）
// ---------------------------------------------------------------------------

test("B-1 · GET /approvals/{id} ⇒ 200 + 12 键逐字", async () => {
  const fixture = await makeApp({ username: "appr-b1" });
  try {
    const id = seedApproval(fixture);
    const response = await request(fixture, "GET", `/api/v1/approvals/${id}`);
    assert.equal(response.statusCode, 200);
    const data = JSON.parse(response.body).data;
    assert.deepEqual(Object.keys(data).sort(), APPROVAL_KEYS);
    assert.equal(data.id, id);
    assert.equal(data.status, "PENDING");
    assert.deepEqual(data.payload, {});
    assert.equal(data.decided_by, null);
    assert.equal(data.decided_at, null);
  } finally {
    await fixture.close();
  }
});

test("B-2 · 跨租户 / 不存在 ⇒ 404 `NOT_FOUND`（不是 403、不是空体）", async () => {
  const fixture = await makeApp({ username: "appr-b2" });
  try {
    const otherId = seedApproval(fixture, { tenant_id: OTHER_TENANT_ID });

    const cross = await request(fixture, "GET", `/api/v1/approvals/${otherId}`);
    assert.equal(cross.statusCode, 404, "跨租户必须是 404");
    assert.equal(errorOf(cross).code, "NOT_FOUND");
    assert.deepEqual(errorOf(cross).data, { approval_id: otherId });

    const missing = await request(
      fixture,
      "GET",
      "/api/v1/approvals/f0000000-0000-4000-8000-0000000000de"
    );
    assert.equal(missing.statusCode, 404);

    // 对照：该行在库里确实存在（否则上面的 404 可能只是"没插进去"）
    assert.equal(countRows(fixture, "approval"), 1);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// C / D 组 · 决议（200 + 409）
// ---------------------------------------------------------------------------

test("C-1 · POST approve ⇒ 200 + APPROVED + decided_by=当前用户 + decided_at 非空", async () => {
  const fixture = await makeApp({ username: "appr-c1" });
  try {
    const id = seedApproval(fixture);
    const response = await request(fixture, "POST", `/api/v1/approvals/${id}/approve`);
    assert.equal(response.statusCode, 200, "契约成功码是 200（不是 201/204）");
    const data = JSON.parse(response.body).data;
    assert.equal(data.status, "APPROVED");
    assert.equal(data.decided_by, fixture.userId, "决议人必须是当前登录用户");
    assert.ok(data.decided_at !== null, "decided_at 必须落值");
    assert.deepEqual(Object.keys(data).sort(), APPROVAL_KEYS);
  } finally {
    await fixture.close();
  }
});

test("C-2 · 二次 approve ⇒ **409 CONFLICT**（不是幂等返回、不是 500）", async () => {
  const fixture = await makeApp({ username: "appr-c2" });
  try {
    const id = seedApproval(fixture);
    const first = await request(fixture, "POST", `/api/v1/approvals/${id}/approve`);
    assert.equal(first.statusCode, 200);

    const second = await request(fixture, "POST", `/api/v1/approvals/${id}/approve`);
    assert.equal(second.statusCode, 409, "已决议再决议必须 409");
    assert.equal(errorOf(second).code, "CONFLICT");
    // `data` 键集合与 py `_decide` 逐字一致
    assert.deepEqual(errorOf(second).data, { approval_id: id, status: "APPROVED" });

    // 库内仍是那一行、状态没被二次改写
    assert.equal(countRows(fixture, "approval"), 1);
  } finally {
    await fixture.close();
  }
});

test("C-3 · approve 之后 reject ⇒ 409（跨决议方向同样拒绝）", async () => {
  const fixture = await makeApp({ username: "appr-c3" });
  try {
    const id = seedApproval(fixture);
    await request(fixture, "POST", `/api/v1/approvals/${id}/approve`);
    const rejected = await request(fixture, "POST", `/api/v1/approvals/${id}/reject`);
    assert.equal(rejected.statusCode, 409);
    assert.deepEqual(errorOf(rejected).data, { approval_id: id, status: "APPROVED" });
  } finally {
    await fixture.close();
  }
});

test("D-1 · POST reject ⇒ 200 + REJECTED", async () => {
  const fixture = await makeApp({ username: "appr-d1" });
  try {
    const id = seedApproval(fixture);
    const response = await request(fixture, "POST", `/api/v1/approvals/${id}/reject`);
    assert.equal(response.statusCode, 200);
    const data = JSON.parse(response.body).data;
    assert.equal(data.status, "REJECTED");
    assert.equal(data.decided_by, fixture.userId);
  } finally {
    await fixture.close();
  }
});

test("D-2 · 二次 reject ⇒ 409（reject 侧同样不幂等）", async () => {
  const fixture = await makeApp({ username: "appr-d2" });
  try {
    const id = seedApproval(fixture);
    await request(fixture, "POST", `/api/v1/approvals/${id}/reject`);
    const second = await request(fixture, "POST", `/api/v1/approvals/${id}/reject`);
    assert.equal(second.statusCode, 409);
    assert.deepEqual(errorOf(second).data, { approval_id: id, status: "REJECTED" });
  } finally {
    await fixture.close();
  }
});

test("D-3 · 跨租户决议 ⇒ 404（先判归属再判状态：跨租户的已决议行不得回 409）", async () => {
  const fixture = await makeApp({ username: "appr-d3" });
  try {
    // 别租户 + 已决议：若先判 `status !== PENDING` 就回 409，等于泄漏了该行存在
    const otherId = seedApproval(fixture, { tenant_id: OTHER_TENANT_ID, status: "APPROVED" });
    const response = await request(fixture, "POST", `/api/v1/approvals/${otherId}/approve`);
    assert.equal(response.statusCode, 404, "跨租户必须 404（顺序：404 先于 409）");
    assert.equal(errorOf(response).code, "NOT_FOUND");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// E 组 · 「决议不触发执行」（卡面反例：审批与执行分离）
// ---------------------------------------------------------------------------

test("E-1 · 静态：审批路由与服务**不得**从任何执行器 / 沙箱 / Run 模块导入", () => {
  const files = [
    join(ROOT, "apps/api/src/routes/approvals.ts"),
    join(ROOT, "apps/api/src/modules/approval/service.ts"),
  ];
  // 判据是**导入面**而不是全文：注释里提到 "AgentLoop" 只是说明文字，不构成依赖；
  // 真正会"顺手把工具跑了"的是 import 了执行器模块。
  // ⚠️ 用**路径片段**而不是 `modules/xxx`：`modules/approval/service.ts` 里的同层导入
  //     写的是 `../tool/service.js`，用 `modules/tool` 匹配会漏（T3-08 的 CE-T8-2 实证）。
  const forbiddenPaths = ["/tool/", "/sandbox/", "/run/", "/runtime/"];

  for (const file of files) {
    const source = readFileSync(file, "utf8");
    const specifiers = [...source.matchAll(/from\s+"([^"]+)"/g)].map((match) => match[1]);
    assert.ok(specifiers.length > 0, `${file} 应至少有一个 import（否则断言本身失效）`);
    for (const specifier of specifiers) {
      for (const forbidden of forbiddenPaths) {
        assert.equal(
          specifier.includes(forbidden),
          false,
          `${file} 从 "${specifier}" 导入了执行器面（命中 "${forbidden}"）—— 审批与执行必须分离`
        );
      }
    }
  }
});

test("E-2 · 行为：决议前后 `tool_call` 表行数不变（只改状态与时间戳）", async () => {
  const fixture = await makeApp({ username: "appr-e2" });
  try {
    const id = seedApproval(fixture);
    const before = countRows(fixture, "tool_call");

    await request(fixture, "POST", `/api/v1/approvals/${id}/approve`);

    assert.equal(
      countRows(fixture, "tool_call"),
      before,
      "决议不得产生任何工具调用行（执行在 T3-08 的恢复路径）"
    );
    // 对照：审批行本身确实被改了（否则"零增长"可能只是"什么都没发生"）
    const detail = await request(fixture, "GET", `/api/v1/approvals/${id}`);
    assert.equal(JSON.parse(detail.body).data.status, "APPROVED");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// F 组 · 认证面
// ---------------------------------------------------------------------------

test("F-1 · 4 op 无令牌 ⇒ 401 `UNAUTHORIZED`", async () => {
  const fixture = await makeApp({ username: "appr-f1" });
  try {
    const id = seedApproval(fixture);
    const cases = [
      ["GET", "/api/v1/approvals"],
      ["GET", `/api/v1/approvals/${id}`],
      ["POST", `/api/v1/approvals/${id}/approve`],
      ["POST", `/api/v1/approvals/${id}/reject`],
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

test("F-2 · 未认证 + 非法 query ⇒ **仍是 401**（preValidation 早于 schema 校验）", async () => {
  const fixture = await makeApp({ username: "appr-f2" });
  try {
    const response = await fixture.app.inject({
      method: "GET",
      url: "/api/v1/approvals?limit=0",
    });
    assert.equal(response.statusCode, 401, "认证必须早于入参校验");

    // 反向对照：**已认证** + 同一非法 query ⇒ 422（证明 401 不是"端点恒 401"）
    const authed = await request(fixture, "GET", "/api/v1/approvals?limit=0");
    assert.equal(authed.statusCode, 422);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// G 组 · 契约面
// ---------------------------------------------------------------------------

test("G-1 · 4 个 operationId 的成功码与响应形状与契约一致", () => {
  const cases = [
    ["list_approvals_api_v1_approvals_get", "GET", "/api/v1/approvals", 200],
    ["get_approval_api_v1_approvals__approval_id__get", "GET", "/api/v1/approvals/{approval_id}", 200],
    ["approve_approval_api_v1_approvals__approval_id__approve_post", "POST", "/api/v1/approvals/{approval_id}/approve", 200],
    ["reject_approval_api_v1_approvals__approval_id__reject_post", "POST", "/api/v1/approvals/{approval_id}/reject", 200],
  ];
  for (const [operationId, method, path, successStatus] of cases) {
    const entry = OPERATION_SCHEMAS[operationId];
    assert.ok(entry !== undefined, `缺少 operationId ${operationId}`);
    assert.equal(entry.method, method);
    assert.equal(entry.path, path);
    assert.equal(entry.successStatus, successStatus);
    assert.equal(entry.body, undefined, `${operationId} 契约无请求体`);
  }
});
