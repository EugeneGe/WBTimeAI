/**
 * AUD-17 · `CredentialService` 的**服务层**单测（P3）。
 *
 * 为什么需要它：`credential-crypto.test.mjs` 证的是**加密原语**（`encryptValue` /
 * `decryptValue` / `maskValue`），而"服务层有没有把明文漏出去"是另一件事 ——
 * 加密再正确，只要 `list()` 顺手解密一次、或者 `metadata` 里存了明文，泄露照样发生。
 * 这条链路的判据只能在服务层写。
 *
 * 四段（AUD-17 要求的"创建 → 脱敏回读 → 更新 → 删除"）
 * ------------------------------------------------
 *   ① **创建**：`save()` 落库的是**信封密文**，回参只有掩码；
 *   ② **脱敏回读**：`list()` 不回明文、不回密文（`masked_value` 只含末 4 位）；
 *   ③ **更新**：冻结契约里凭据只有 list / save / delete 三个 op（没有 PATCH）⇒
 *      "更新"的真实形态是**同 provider 轮换（再 save 一条）**。判据：新行独立落库、
 *      密文随明文变化（新 IV ⇒ 密文不同）、旧行不被改写；
 *   ④ **删除**：真删行；再删 ⇒ `CREDENTIAL_NOT_FOUND`（404，且不区分"不存在"与
 *      "跨租户"—— 区分会泄露存在性）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/credential-service.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { CredentialService } from "../dist/modules/credential/service.js";
import { makeApp, TENANT_ID, TEST_SECRET } from "./routes-harness.mjs";

/** 明文凭据（**不是**任何真实部署的 key）。 */
const PLAINTEXT = "sk-live-0123456789abcdef";
/** 轮换后的明文。 */
const ROTATED = "sk-live-fedcba9876543210";

/** 建服务（与路由层同参数：同一 db / dialect / 主密钥）。 */
function buildService(fixture) {
  return new CredentialService({
    db: fixture.connection.db,
    dialect: "sqlite",
    secretKey: TEST_SECRET,
  });
}

/** 读凭据表的原始行（用来看"库里到底存了什么"）。 */
function rawRows(fixture, provider) {
  return fixture.raw
    .prepare("select id, provider, key_type, encrypted_value, metadata, workspace_id from credential where provider = ?")
    .all(provider);
}

test("① 创建：落库是信封密文，回参只有掩码（无明文）", async () => {
  const fixture = await makeApp({ username: "cred-svc-a1" });
  try {
    const service = buildService(fixture);
    const created = await service.save(TENANT_ID, { provider: "openai", value: PLAINTEXT });

    // 回参：契约 CredentialResponse 的 6 键
    assert.deepEqual(
      Object.keys(created).sort(),
      ["created_at", "id", "key_type", "masked_value", "provider", "workspace_id"],
      "回参键集合必须与契约一致（多一个字段就可能是泄漏通道）"
    );
    assert.equal(created.provider, "openai");
    assert.equal(created.key_type, "api_key", "key_type 缺省 = api_key");
    assert.equal(created.masked_value, "****cdef", "掩码 = 四星 + 末 4 位");
    assert.equal(
      JSON.stringify(created).includes(PLAINTEXT),
      false,
      "回参任何字段都不得含明文"
    );

    // 落库：密文不是明文，且**不存**明文任何片段（除末 4 位在掩码里）。
    const rows = rawRows(fixture, "openai");
    assert.equal(rows.length, 1);
    assert.notEqual(rows[0].encrypted_value, PLAINTEXT, "落库值必须是信封密文");
    assert.equal(
      String(rows[0].encrypted_value).includes(PLAINTEXT.slice(0, 8)),
      false,
      "密文里不得出现明文前缀（否则等于没加密）"
    );
    const metadata = JSON.parse(rows[0].metadata);
    assert.equal(metadata.masked_value, "****cdef");
    assert.equal(
      JSON.stringify(metadata).includes(PLAINTEXT),
      false,
      "metadata 不得存明文"
    );
  } finally {
    await fixture.close();
  }
});

test("② 脱敏回读：list 不回明文、不回密文", async () => {
  const fixture = await makeApp({ username: "cred-svc-a2" });
  try {
    const service = buildService(fixture);
    await service.save(TENANT_ID, { provider: "anthropic", value: PLAINTEXT });

    const listed = await service.list(TENANT_ID);
    assert.equal(listed.length, 1);
    const view = listed[0];
    assert.equal(view.masked_value, "****cdef");
    const serialized = JSON.stringify(listed);
    assert.equal(serialized.includes(PLAINTEXT), false, "list 不得回明文");
    // 密文信封以 `v1:` 开头（见 crypto.ts 的 ENVELOPE_VERSION）—— 出现它就说明解密/透传漏了。
    assert.equal(serialized.includes("v1:"), false, "list 不得回密文信封");
    assert.equal(Object.prototype.hasOwnProperty.call(view, "encrypted_value"), false, "视图不含密文字段");
  } finally {
    await fixture.close();
  }
});

test("③ 更新（同 provider 轮换）：新行独立落库、密文随明文变化、旧行不被改写", async () => {
  const fixture = await makeApp({ username: "cred-svc-a3" });
  try {
    const service = buildService(fixture);
    const first = await service.save(TENANT_ID, { provider: "openai", value: PLAINTEXT });
    const before = rawRows(fixture, "openai");

    const second = await service.save(TENANT_ID, { provider: "openai", value: ROTATED });

    assert.notEqual(second.id, first.id, "轮换产生新行（契约没有 PATCH，更新 = 再 save）");
    assert.equal(second.masked_value, "****3210", "掩码跟着新明文走");

    const after = rawRows(fixture, "openai");
    assert.equal(after.length, 2, "两条独立凭据（轮换不是覆盖写）");
    assert.equal(
      after[0].encrypted_value,
      before[0].encrypted_value,
      "旧行的密文必须逐字不变（历史凭据不得被静默改写）"
    );
    assert.notEqual(
      after[1].encrypted_value,
      before[0].encrypted_value,
      "新行密文必须不同（明文不同 + 每次新 IV）"
    );
    assert.equal(
      after[1].encrypted_value.includes(ROTATED),
      false,
      "新行同样不得含明文"
    );
  } finally {
    await fixture.close();
  }
});

test("④ 删除：真删行；再删 ⇒ CREDENTIAL_NOT_FOUND（404，不区分跨租户）", async () => {
  const fixture = await makeApp({ username: "cred-svc-a4" });
  try {
    const service = buildService(fixture);
    const created = await service.save(TENANT_ID, { provider: "openai", value: PLAINTEXT });

    await service.remove(TENANT_ID, created.id);
    assert.equal(rawRows(fixture, "openai").length, 0, "删除必须真删行");
    assert.equal((await service.list(TENANT_ID)).length, 0, "删除后列表为空");

    // 再删：404 + 专用错误码（不区分"不存在"与"跨租户"）。
    await assert.rejects(
      () => service.remove(TENANT_ID, created.id),
      (error) => {
        assert.equal(error.statusCode, 404, `实测 ${String(error)}`);
        assert.equal(error.body?.code ?? error.code, "CREDENTIAL_NOT_FOUND");
        return true;
      }
    );
  } finally {
    await fixture.close();
  }
});

test("⑤ 纵深防御：provider / value 为空 ⇒ RangeError（不落库、不加密）", async () => {
  const fixture = await makeApp({ username: "cred-svc-a5" });
  try {
    const service = buildService(fixture);
    await assert.rejects(() => service.save(TENANT_ID, { provider: "", value: PLAINTEXT }), RangeError);
    await assert.rejects(() => service.save(TENANT_ID, { provider: "openai", value: "" }), RangeError);
    assert.equal(rawRows(fixture, "openai").length, 0, "被拒的保存不得落库");
  } finally {
    await fixture.close();
  }
});
