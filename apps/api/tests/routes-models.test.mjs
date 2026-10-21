/**
 * T2-07 · 模型/凭证族 5 op（§1 表 15–19）。
 *
 * 安全判据（§7.1-2 红线）：**凭据不得明文落库**。这条不能靠"我加密了"自证 ——
 * 测试把 `credential` 整表 dump 出来搜明文，搜到即失败。
 *
 * 另覆盖：掩码格式、204 零字节体、404（凭据 / 供应商不可见）与 200（绑定 / 解绑）。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { PROVIDER_ID, dataOf, errorOf, makeApp, request } from "./routes-harness.mjs";

/** 明文凭据（测试专用；断言它**绝不**出现在库表 dump 与任何响应里）。 */
const PLAINTEXT = "sk-very-secret-key-should-never-be-stored-0123456789";

test("⑯ POST /models/credentials ⇒ 201，只回掩码；整表 dump 不含明文（红线）", async () => {
  const fixture = await makeApp({ username: "tina" });

  const saved = await request(fixture, "POST", "/api/v1/models/credentials", {
    payload: { provider: "openai", value: PLAINTEXT, key_type: "api_key" },
  });
  assert.equal(saved.statusCode, 201, saved.body);
  const body = dataOf(saved);
  assert.deepEqual(Object.keys(body).sort(), [
    "created_at",
    "id",
    "key_type",
    "masked_value",
    "provider",
    "workspace_id",
  ]);
  assert.equal(body.masked_value, `****${PLAINTEXT.slice(-4)}`, "掩码保留末 4 位");
  assert.equal(body.provider, "openai");
  assert.equal(body.key_type, "api_key");

  // ① 响应体不得含明文（整个 body 搜一遍，含壳与 data）
  assert.equal(saved.body.includes(PLAINTEXT), false, "响应体泄漏了明文凭据");

  // ② 库表 dump 不得含明文
  const dump = JSON.stringify(fixture.raw.prepare("SELECT * FROM credential").all());
  assert.equal(dump.includes(PLAINTEXT), false, "库里出现了明文凭据 —— §7.1-2 红线");
  assert.equal(dump.includes("sk-very-secret"), false, "库里出现了明文前缀");

  // ③ 落库的必须是 v1 信封
  const row = fixture.raw.prepare("SELECT encrypted_value FROM credential").get();
  assert.match(row.encrypted_value, /^v1:[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+$/, "必须是 AES-GCM 信封");
  await fixture.close();
});

test("⑮ GET /models/credentials ⇒ 200 掩码列表（不解密、无明文）", async () => {
  const fixture = await makeApp({ username: "umar" });
  await request(fixture, "POST", "/api/v1/models/credentials", {
    payload: { provider: "anthropic", value: PLAINTEXT },
  });

  const listed = await request(fixture, "GET", "/api/v1/models/credentials");
  assert.equal(listed.statusCode, 200);
  const items = dataOf(listed);
  assert.equal(items.length, 1);
  assert.equal(items[0].masked_value, `****${PLAINTEXT.slice(-4)}`);
  assert.equal(listed.body.includes(PLAINTEXT), false);
  await fixture.close();
});

test("⑰ DELETE /models/credentials/{id} ⇒ 204 零字节；再删 ⇒ 404 CREDENTIAL_NOT_FOUND", async () => {
  const fixture = await makeApp({ username: "vera" });
  const saved = dataOf(
    await request(fixture, "POST", "/api/v1/models/credentials", {
      payload: { provider: "openai", value: PLAINTEXT },
    })
  );

  const removed = await request(fixture, "DELETE", `/api/v1/models/credentials/${saved.id}`);
  assert.equal(removed.statusCode, 204);
  assert.equal(removed.body, "", "204 必须零字节体（J-10）");

  const again = await request(fixture, "DELETE", `/api/v1/models/credentials/${saved.id}`);
  assert.equal(again.statusCode, 404);
  assert.equal(errorOf(again).code, "CREDENTIAL_NOT_FOUND");

  const missing = await request(
    fixture,
    "DELETE",
    "/api/v1/models/credentials/99999999-9999-4999-8999-999999999999"
  );
  assert.equal(missing.statusCode, 404, "不存在与跨租户同码（不区分，防存在性探测）");
  await fixture.close();
});

test("⑱⑲ 绑定 / 解绑供应商凭据 ⇒ 200，credential_id 往返", async () => {
  const fixture = await makeApp({ username: "wendy" });
  const saved = dataOf(
    await request(fixture, "POST", "/api/v1/models/credentials", {
      payload: { provider: "openai", value: PLAINTEXT },
    })
  );

  const bound = await request(fixture, "POST", `/api/v1/models/providers/${PROVIDER_ID}/credential`, {
    payload: { credential_id: saved.id },
  });
  assert.equal(bound.statusCode, 200, bound.body);
  const provider = dataOf(bound);
  assert.deepEqual(Object.keys(provider).sort(), [
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
  ]);
  assert.equal(provider.credential_id, saved.id);

  const unbound = await request(
    fixture,
    "DELETE",
    `/api/v1/models/providers/${PROVIDER_ID}/credential`
  );
  assert.equal(unbound.statusCode, 200);
  assert.equal(dataOf(unbound).credential_id, null, "解绑 = 置 null，不删供应商");
  await fixture.close();
});

test("绑定：凭据不存在 ⇒ 404 CREDENTIAL_NOT_FOUND；供应商不存在 ⇒ 404 NOT_FOUND（均非 403）", async () => {
  const fixture = await makeApp({ username: "xena" });

  const noCredential = await request(
    fixture,
    "POST",
    `/api/v1/models/providers/${PROVIDER_ID}/credential`,
    { payload: { credential_id: "99999999-9999-4999-8999-999999999999" } }
  );
  assert.equal(noCredential.statusCode, 404);
  assert.equal(errorOf(noCredential).code, "CREDENTIAL_NOT_FOUND");

  const saved = dataOf(
    await request(fixture, "POST", "/api/v1/models/credentials", {
      payload: { provider: "openai", value: PLAINTEXT },
    })
  );
  const noProvider = await request(
    fixture,
    "POST",
    "/api/v1/models/providers/99999999-9999-4999-8999-999999999999/credential",
    { payload: { credential_id: saved.id } }
  );
  assert.equal(noProvider.statusCode, 404);
  assert.equal(errorOf(noProvider).code, "NOT_FOUND");

  const unbindMissing = await request(
    fixture,
    "DELETE",
    "/api/v1/models/providers/99999999-9999-4999-8999-999999999999/credential"
  );
  assert.equal(unbindMissing.statusCode, 404);
  await fixture.close();
});

test("凭证族：无令牌一律 401；空 provider / 空 value ⇒ 422", async () => {
  const fixture = await makeApp({ username: "yuri" });

  for (const [method, url, payload] of [
    ["GET", "/api/v1/models/credentials", undefined],
    ["POST", "/api/v1/models/credentials", { provider: "openai", value: "x" }],
    ["DELETE", "/api/v1/models/credentials/99999999-9999-4999-8999-999999999999", undefined],
    ["POST", `/api/v1/models/providers/${PROVIDER_ID}/credential`, { credential_id: "x" }],
    ["DELETE", `/api/v1/models/providers/${PROVIDER_ID}/credential`, undefined],
  ]) {
    const response = await request(fixture, method, url, {
      auth: false,
      ...(payload === undefined ? {} : { payload }),
    });
    assert.equal(response.statusCode, 401, `${method} ${url} 无令牌必须 401`);
  }

  const emptyProvider = await request(fixture, "POST", "/api/v1/models/credentials", {
    payload: { provider: "", value: "x" },
  });
  assert.equal(emptyProvider.statusCode, 422);
  assert.equal(errorOf(emptyProvider).code, "VALIDATION_ERROR");

  const emptyValue = await request(fixture, "POST", "/api/v1/models/credentials", {
    payload: { provider: "openai", value: "" },
  });
  assert.equal(emptyValue.statusCode, 422);
  await fixture.close();
});
