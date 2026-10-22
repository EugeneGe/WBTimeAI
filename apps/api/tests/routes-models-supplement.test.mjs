/**
 * T3-12 · 模型目录 **6 op** 的行为证明（真库 + `buildApp` + `app.inject`）。
 *
 * 这 6 个 op 是补 T2-07 那 5 个凭证 op 留下的目录缺口：
 *   `GET|POST /models/providers` · `GET|DELETE /models/providers/{id}` ·
 *   `GET|POST /models/providers/{id}/models`。
 *
 * 判据（任务卡验收 ①–③ + 反例）：
 *   ① **6 op 全通**，成功码逐字：列表 / 详情 200、注册 **201**、禁用 **200**（不是 204）；
 *   ② **两条服务层 422**（契约不约束、py 才是判据）：
 *      - `name` trim 后为空（`"   "` 能过 schema 的长度检查）⇒ 422 + `data.field="name"`；
 *      - `provider_type` 不在白名单 ⇒ 422 + `data.field="type"` + `data.allowed` 七项
 *        （**注意键是 `type` 不是 `provider_type`** —— py 原文如此）；
 *   ③ **禁用是软删**：`DELETE` 回 **200 + 整行**、`status=DISABLED`，**行仍在**；
 *      重复禁用幂等（仍 200）。这条用"删完还能 GET 到"来证明，比只看状态码硬。
 *   ④ **跨租户 404**（I-1）：别租户的 provider 在详情 / 禁用 / 模型列表 / 注册模型
 *      四个面上都是 404 `NOT_FOUND`。
 *
 * 反例（注入即红）：
 *   - 「`GET /tools` 回落到 4 个」类似地，这里对应「`DELETE` 写成真删行」：
 *     删完 `GET {id}` 会变 404 ⇒ G-2 的"删完还能取到"当场红；
 *   - 「白名单放宽」：把 `PROVIDER_TYPES` 加一项 ⇒ D 组 `allowed` 数组不等长，红。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/routes-models-supplement.test.mjs`
 */

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";

import { OPERATION_SCHEMAS } from "../dist/routes/schemas.js";
import {
  errorOf,
  makeApp,
  OTHER_TENANT_ID,
  PROVIDER_ID,
  request,
} from "./routes-harness.mjs";

/** 契约 `ModelProviderResponse` 的 10 键（逐字）。 */
const PROVIDER_KEYS = [
  "config",
  "created_at",
  "credential_id",
  "endpoint",
  "id",
  "name",
  "status",
  "tenant_id",
  "type",
  "workspace_id",
];

/** 契约 `ModelResponse` 的 9 键（逐字）。 */
const MODEL_KEYS = [
  "capabilities",
  "context_window",
  "created_at",
  "id",
  "name",
  "provider_id",
  "status",
  "tenant_id",
  "type",
];

/** py `MODEL_PROVIDER_TYPES` 的七项（顺序也照抄 —— `allowed` 会原样出现在 422 的 data 里）。 */
const PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "gemini",
  "deepseek",
  "qwen",
  "ollama",
  "openai_compatible",
];

/** 直接插一条别租户的 provider 行（跨租户 404 的靶子）。 */
function seedOtherProvider(fixture) {
  const id = randomUUID();
  fixture.raw
    .prepare(
      `INSERT INTO model_provider
         (id, tenant_id, organization_id, workspace_id, name, type, endpoint,
          credential_id, status, config)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .run(id, OTHER_TENANT_ID, null, null, `other-${id.slice(0, 8)}`, "openai", null, null, "ACTIVE", "{}");
  return id;
}

// ---------------------------------------------------------------------------
// A 组 · 供应商目录
// ---------------------------------------------------------------------------

test("A-1 · GET /models/providers ⇒ 200 数组（夹具预置 1 条）", async () => {
  const fixture = await makeApp({ username: "mdl-a1" });
  try {
    const response = await request(fixture, "GET", "/api/v1/models/providers");
    assert.equal(response.statusCode, 200);
    const data = JSON.parse(response.body).data;
    assert.ok(Array.isArray(data), "响应 data 必须是数组");
    // 夹具 `seedTenants` 预置了一条 `openai-main`（`PROVIDER_ID`）——它也是本租户的行，
    // 断言"只有它"比断言"空"更硬：既证明列表可用，也证明没有凭空多出别的东西。
    assert.equal(data.length, 1);
    assert.equal(data[0].id, PROVIDER_ID);
    assert.equal(data[0].name, "openai-main");
    assert.deepEqual(Object.keys(data[0]).sort(), PROVIDER_KEYS);
  } finally {
    await fixture.close();
  }
});

test("A-2 · POST /models/providers ⇒ 201 + 10 键 + status=ACTIVE", async () => {
  const fixture = await makeApp({ username: "mdl-a2" });
  try {
    const response = await request(fixture, "POST", "/api/v1/models/providers", {
      payload: { name: "siliconflow", provider_type: "openai_compatible", endpoint: "https://api.example/v1" },
    });
    assert.equal(response.statusCode, 201, "契约成功码是 201");
    const data = JSON.parse(response.body).data;
    assert.deepEqual(Object.keys(data).sort(), PROVIDER_KEYS);
    assert.equal(data.name, "siliconflow");
    assert.equal(data.type, "openai_compatible");
    assert.equal(data.endpoint, "https://api.example/v1");
    assert.equal(data.status, "ACTIVE");
    assert.equal(data.credential_id, null);
    assert.deepEqual(data.config, {}, "缺省 config 应落 {}（py `dict(config) if config else {}`）");
    assert.equal(data.created_at, null, "model_provider 表无 created_at 列 ⇒ 恒 null");

    // 列表能取回来（证明真的落库了）：预置 1 条 + 本用例新建 1 条
    const list = await request(fixture, "GET", "/api/v1/models/providers");
    const ids = JSON.parse(list.body).data.map((row) => row.id);
    assert.equal(ids.length, 2);
    assert.ok(ids.includes(data.id), "新建的 provider 必须出现在列表里");
  } finally {
    await fixture.close();
  }
});

test("A-3 · 名称 trim 后为空 ⇒ 422 + `data.field=name`（schema 只挡长度）", async () => {
  const fixture = await makeApp({ username: "mdl-a3" });
  try {
    const response = await request(fixture, "POST", "/api/v1/models/providers", {
      payload: { name: "   ", provider_type: "openai" },
    });
    assert.equal(response.statusCode, 422);
    assert.equal(errorOf(response).code, "VALIDATION_ERROR");
    assert.deepEqual(errorOf(response).data, { field: "name" });
  } finally {
    await fixture.close();
  }
});

test("A-4 · provider_type 不在白名单 ⇒ 422 + `data.field=type` + `allowed` 七项", async () => {
  const fixture = await makeApp({ username: "mdl-a4" });
  try {
    const response = await request(fixture, "POST", "/api/v1/models/providers", {
      payload: { name: "x", provider_type: "vertex" },
    });
    assert.equal(response.statusCode, 422);
    assert.equal(errorOf(response).code, "VALIDATION_ERROR");
    const data = errorOf(response).data;
    assert.equal(data.field, "type", "py 的 data 键是 `type`，不是 `provider_type`");
    assert.deepEqual(data.allowed, PROVIDER_TYPES, "白名单必须与 py 逐字同序");
  } finally {
    await fixture.close();
  }
});

test("A-5 · GET /models/providers/{id} ⇒ 200；跨租户 / 不存在 ⇒ 404", async () => {
  const fixture = await makeApp({ username: "mdl-a5" });
  try {
    const created = await request(fixture, "POST", "/api/v1/models/providers", {
      payload: { name: "p", provider_type: "openai" },
    });
    const id = JSON.parse(created.body).data.id;

    const detail = await request(fixture, "GET", `/api/v1/models/providers/${id}`);
    assert.equal(detail.statusCode, 200);
    assert.equal(JSON.parse(detail.body).data.id, id);

    const otherId = seedOtherProvider(fixture);
    const cross = await request(fixture, "GET", `/api/v1/models/providers/${otherId}`);
    assert.equal(cross.statusCode, 404, "跨租户必须 404");
    assert.equal(errorOf(cross).code, "NOT_FOUND");
    assert.deepEqual(errorOf(cross).data, { provider_id: otherId });

    const missing = await request(
      fixture,
      "GET",
      "/api/v1/models/providers/f0000000-0000-4000-8000-0000000000de"
    );
    assert.equal(missing.statusCode, 404);

    // 对照：别租户那行确实在库里（否则 404 可能只是"没插进去"）：预置 1 + 新建 1 + 别租户 1
    assert.equal(fixture.raw.prepare("SELECT COUNT(*) AS n FROM model_provider").get().n, 3);
  } finally {
    await fixture.close();
  }
});

test("A-6 · DELETE /models/providers/{id} ⇒ **200 软删**：status=DISABLED 且行仍在、可重复", async () => {
  const fixture = await makeApp({ username: "mdl-a6" });
  try {
    const created = await request(fixture, "POST", "/api/v1/models/providers", {
      payload: { name: "to-disable", provider_type: "openai" },
    });
    const id = JSON.parse(created.body).data.id;

    const disabled = await request(fixture, "DELETE", `/api/v1/models/providers/${id}`);
    assert.equal(disabled.statusCode, 200, "契约是 200 + 整行（不是 204 零字节）");
    assert.notEqual(disabled.body, "", "必须回整行，不能是空体");
    const data = JSON.parse(disabled.body).data;
    assert.equal(data.status, "DISABLED");
    assert.deepEqual(Object.keys(data).sort(), PROVIDER_KEYS);

    // 软删的硬证据：删完还能 GET 到，且状态是 DISABLED（真删这里会 404）
    const after = await request(fixture, "GET", `/api/v1/models/providers/${id}`);
    assert.equal(after.statusCode, 200, "软删：行必须仍在");
    assert.equal(JSON.parse(after.body).data.status, "DISABLED");

    // 重复禁用幂等（py 只看存在性、不看当前状态）
    const again = await request(fixture, "DELETE", `/api/v1/models/providers/${id}`);
    assert.equal(again.statusCode, 200);
    assert.equal(JSON.parse(again.body).data.status, "DISABLED");
  } finally {
    await fixture.close();
  }
});

test("A-7 · DELETE 跨租户 / 不存在 ⇒ 404", async () => {
  const fixture = await makeApp({ username: "mdl-a7" });
  try {
    const otherId = seedOtherProvider(fixture);
    const cross = await request(fixture, "DELETE", `/api/v1/models/providers/${otherId}`);
    assert.equal(cross.statusCode, 404);
    assert.equal(errorOf(cross).code, "NOT_FOUND");

    // 对照：那一行**没被**改动（跨租户的禁用不得落到别租户的行上）
    const row = fixture.raw
      .prepare("SELECT status FROM model_provider WHERE id = ?")
      .get(otherId);
    assert.equal(row.status, "ACTIVE");
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// B 组 · 模型目录
// ---------------------------------------------------------------------------

test("B-1 · GET .../{id}/models ⇒ 200 空数组；POST ⇒ 201 + 9 键", async () => {
  const fixture = await makeApp({ username: "mdl-b1" });
  try {
    const provider = await request(fixture, "POST", "/api/v1/models/providers", {
      payload: { name: "p", provider_type: "openai" },
    });
    const providerId = JSON.parse(provider.body).data.id;

    const empty = await request(
      fixture,
      "GET",
      `/api/v1/models/providers/${providerId}/models`
    );
    assert.equal(empty.statusCode, 200);
    assert.deepEqual(JSON.parse(empty.body).data, []);

    const created = await request(
      fixture,
      "POST",
      `/api/v1/models/providers/${providerId}/models`,
      { payload: { name: "gpt-4o", context_window: 128000, capabilities: { vision: true } } }
    );
    assert.equal(created.statusCode, 201);
    const model = JSON.parse(created.body).data;
    assert.deepEqual(Object.keys(model).sort(), MODEL_KEYS);
    assert.equal(model.provider_id, providerId);
    assert.equal(model.name, "gpt-4o");
    assert.equal(model.type, "CHAT", "契约 model_type 缺省 CHAT");
    assert.equal(model.context_window, 128000);
    assert.deepEqual(model.capabilities, { vision: true });
    assert.equal(model.status, "ACTIVE");
    assert.equal(model.tenant_id, null, "model 表无 tenant_id 列 ⇒ 恒 null");
    assert.equal(model.created_at, null, "model 表无 created_at 列 ⇒ 恒 null");

    const list = await request(
      fixture,
      "GET",
      `/api/v1/models/providers/${providerId}/models`
    );
    assert.equal(JSON.parse(list.body).data.length, 1);
  } finally {
    await fixture.close();
  }
});

test("B-2 · 供应商不可见 ⇒ 模型列表 / 注册模型都是 404（不是 500）", async () => {
  const fixture = await makeApp({ username: "mdl-b2" });
  try {
    const otherId = seedOtherProvider(fixture);

    const list = await request(fixture, "GET", `/api/v1/models/providers/${otherId}/models`);
    assert.equal(list.statusCode, 404, "跨租户必须 404（ScopeError 不得冒成 500）");
    assert.equal(errorOf(list).code, "NOT_FOUND");

    const create = await request(
      fixture,
      "POST",
      `/api/v1/models/providers/${otherId}/models`,
      { payload: { name: "x" } }
    );
    assert.equal(create.statusCode, 404);

    // 越权没落地：别租户 provider 下**零**模型行
    assert.equal(fixture.raw.prepare("SELECT COUNT(*) AS n FROM model").get().n, 0);
  } finally {
    await fixture.close();
  }
});

test("B-3 · 两个 provider 的模型互不串流（父谓词生效）", async () => {
  const fixture = await makeApp({ username: "mdl-b3" });
  try {
    const create = async (name) => {
      const response = await request(fixture, "POST", "/api/v1/models/providers", {
        payload: { name, provider_type: "openai" },
      });
      return JSON.parse(response.body).data.id;
    };
    const providerA = await create("a");
    const providerB = await create("b");

    await request(fixture, "POST", `/api/v1/models/providers/${providerA}/models`, {
      payload: { name: "model-a" },
    });

    const listB = await request(fixture, "GET", `/api/v1/models/providers/${providerB}/models`);
    assert.deepEqual(JSON.parse(listB.body).data, [], "B 下不得看到 A 的模型");

    const listA = await request(fixture, "GET", `/api/v1/models/providers/${providerA}/models`);
    assert.equal(JSON.parse(listA.body).data.length, 1);
  } finally {
    await fixture.close();
  }
});

// ---------------------------------------------------------------------------
// C 组 · 认证面 + 契约面
// ---------------------------------------------------------------------------

test("C-1 · 6 op 无令牌 ⇒ 401", async () => {
  const fixture = await makeApp({ username: "mdl-c1" });
  try {
    const cases = [
      ["GET", "/api/v1/models/providers"],
      ["POST", "/api/v1/models/providers"],
      ["GET", "/api/v1/models/providers/f0000000-0000-4000-8000-0000000000de"],
      ["DELETE", "/api/v1/models/providers/f0000000-0000-4000-8000-0000000000de"],
      ["GET", "/api/v1/models/providers/f0000000-0000-4000-8000-0000000000de/models"],
      ["POST", "/api/v1/models/providers/f0000000-0000-4000-8000-0000000000de/models"],
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

test("C-2 · 6 个 operationId 的 method / path / 成功码与契约一致", () => {
  const cases = [
    ["list_providers_api_v1_models_providers_get", "GET", "/api/v1/models/providers", 200],
    ["register_provider_api_v1_models_providers_post", "POST", "/api/v1/models/providers", 201],
    ["get_provider_api_v1_models_providers__provider_id__get", "GET", "/api/v1/models/providers/{provider_id}", 200],
    ["disable_provider_api_v1_models_providers__provider_id__delete", "DELETE", "/api/v1/models/providers/{provider_id}", 200],
    ["list_models_api_v1_models_providers__provider_id__models_get", "GET", "/api/v1/models/providers/{provider_id}/models", 200],
    ["register_model_api_v1_models_providers__provider_id__models_post", "POST", "/api/v1/models/providers/{provider_id}/models", 201],
  ];
  for (const [operationId, method, path, successStatus] of cases) {
    const entry = OPERATION_SCHEMAS[operationId];
    assert.ok(entry !== undefined, `缺少 operationId ${operationId}`);
    assert.equal(entry.method, method, `${operationId} 的 method`);
    assert.equal(entry.path, path, `${operationId} 的 path`);
    assert.equal(entry.successStatus, successStatus, `${operationId} 的成功码`);
  }
});
