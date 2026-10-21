// T3-02 · A01 —— `model_provider` / `credential` 的 Gateway 解析读方法。
//
// 判据（施工记录 §6-1「按 provider / credential 解析」）：
//   · 按 kind（`type` 列）取供应商配置；按状态过滤；kind+状态取首个可用；
//   · 按 credential 归属取可用 key 载体，并**区分** bound / unbound / missing / inactive；
//   · 租户 scope 过滤：跨租户 ⇒ `ScopeError`（**不是**空数组 / `null`）；
//   · 零 DDL：本文件用**仓内既有** `output/ddl.sqlite.sql` 建库，不加列不加索引。
//
// 防假绿的「非空档」自检：每个查询用例都先断言夹具真的存在（行数 > 0），
// 否则"查不到"可能只是夹具没插进去，而不是 scope 生效。

import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createSqliteDb } from "@wbtime/db/connection";
import {
  ModelCredentialRepo,
  ModelProviderRepo,
  Scope,
  ScopeError,
  TenantRepo,
} from "@wbtime/db/repositories";

/**
 * `credential` / `model_provider` 都有 `tenant_id → tenant.id` 外键，而 `node:sqlite`
 * **默认开启**外键约束（实测 `PRAGMA foreign_keys = 1`）—— 所以夹具必须先有租户行，
 * 否则插入会以 `FOREIGN KEY constraint failed` 失败（不是仓储的问题）。
 *
 * `TenantRepo.create` 是 protected（租户自举归 V0.6.0，不允许随便建租户），
 * 这里按既有 `packages/db/tests/identity-repos.test.mjs` 的同款写法显式开一个出口。
 */
class WritableTenantRepo extends TenantRepo {
  create(row) {
    return super.insertRow(row);
  }
}

// 说明：`CREDENTIAL_STATUS_ACTIVE` / `PROVIDER_STATUS_ACTIVE` 两个常量**没有**从
// `repositories/index.ts` 透出（该 index 属 T3-03 独占，本任务不得改），故本文件用
// 字面量 `"ACTIVE"`，并把"默认值 == ACTIVE"改成**行为断言**（见 `findActiveByType`
// 与 `resolveKeyCarrier` 两例）—— 比 `assert.equal(CONST, "ACTIVE")` 更有意义：
// 它证明的是"默认口径真的生效"，而不是"常量字符串没被改"。

const DDL = readFileSync(
  fileURLToPath(new URL("../../../output/ddl.sqlite.sql", import.meta.url)),
  "utf8",
);

const DIALECT = "sqlite";

function freshDb() {
  const connection = createSqliteDb(":memory:");
  connection.raw.exec(DDL);
  return connection.db;
}

const T_A = "11111111-1111-4111-8111-111111111111";
const T_B = "22222222-2222-4222-8222-222222222222";

// 供应商（tenant A）
const P_COMPAT = "aaaaaaaa-0000-4000-8000-0000000000a1"; // openai-compatible + ACTIVE + 已绑凭据
const P_OPENAI = "aaaaaaaa-0000-4000-8000-0000000000a2"; // openai + ACTIVE + 未绑
const P_DISABLED = "aaaaaaaa-0000-4000-8000-0000000000a3"; // anthropic + DISABLED
/**
 * google + ACTIVE + `credential_id` 指向**别的租户**的凭据。
 *
 * 为什么不是「指向一个不存在的 id」：PG / SQLite 的 `credential_id → credential.id`
 * 外键**真的生效**（node:sqlite 实测 `PRAGMA foreign_keys = 1`），插入悬空 id 会被
 * 数据库拒绝。所以真库里 `missing` 状态唯一可达的路径就是**跨租户引用** ——
 * 行存在，但本租户的 scope 看不见。本夹具按这条真实路径构造。
 */
const P_FOREIGN = "aaaaaaaa-0000-4000-8000-0000000000a4";
const P_INACTIVE_KEY = "aaaaaaaa-0000-4000-8000-0000000000a5"; // openai + ACTIVE + 绑了被禁用的 key

// 供应商（tenant B）
const P_B = "bbbbbbbb-0000-4000-8000-0000000000b1";

// 凭据（tenant A）
const C_ACTIVE = "cccccccc-0000-4000-8000-0000000000c1";
const C_DISABLED = "cccccccc-0000-4000-8000-0000000000c2";
/** 属于 **tenant B** 的凭据（被 A 的 P_FOREIGN 引用 ⇒ 跨租户引用夹具）。 */
const C_B = "cccccccc-0000-4000-8000-0000000000cb";

const SILICONFLOW_ENDPOINT = "https://api.siliconflow.cn/v1";

/** 凭据 / 供应商的「可用」状态字面量（与仓储内默认口径同源，见文件头说明）。 */
const ACTIVE = "ACTIVE";

/**
 * 建两租户夹具。
 *
 * @returns 两个 scope 下的仓储（provider / credential 各两套）。
 */
async function seed() {
  const db = freshDb();
  const scopeA = new Scope(T_A);
  const scopeB = new Scope(T_B);
  const providersA = new ModelProviderRepo(db, scopeA, DIALECT);
  const providersB = new ModelProviderRepo(db, scopeB, DIALECT);
  const credentialsA = new ModelCredentialRepo(db, scopeA, DIALECT);
  const credentialsB = new ModelCredentialRepo(db, scopeB, DIALECT);

  // 租户先行（外键约束真的生效 —— 这也是"夹具不是空壳"的旁证）
  await new WritableTenantRepo(db, scopeA, DIALECT).create({
    id: T_A,
    name: "tenant-a",
    slug: "tenant-a",
    is_active: true,
  });
  await new WritableTenantRepo(db, scopeB, DIALECT).create({
    id: T_B,
    name: "tenant-b",
    slug: "tenant-b",
    is_active: true,
  });

  await credentialsA.create({
    id: C_ACTIVE,
    provider: "siliconflow",
    key_type: "api_key",
    // 只放**信封**（密文串），与 service 层同口径：明文永不进仓储。
    encrypted_value: "env:v1:ZXhhbXBsZS1jaXBoZXI=",
    name: "siliconflow-main",
    status: "ACTIVE",
    metadata: { masked_value: "***abcd" },
  });
  await credentialsA.create({
    id: C_DISABLED,
    provider: "siliconflow",
    key_type: "api_key",
    encrypted_value: "env:v1:ZXhhbXBsZS1jaXBoZXIy",
    name: "siliconflow-old",
    status: "DISABLED",
    metadata: { masked_value: "***wxyz" },
  });

  await providersA.create({
    id: P_COMPAT,
    name: "siliconflow",
    type: "openai-compatible",
    endpoint: SILICONFLOW_ENDPOINT,
    credential_id: C_ACTIVE,
    status: "ACTIVE",
    config: { note: "V0.3.0 一次性真连烟测的目标供应商" },
  });
  await providersA.create({
    id: P_OPENAI,
    name: "openai-main",
    type: "openai",
    endpoint: null,
    credential_id: null,
    status: "ACTIVE",
  });
  await providersA.create({
    id: P_DISABLED,
    name: "anthropic-off",
    type: "anthropic",
    endpoint: null,
    credential_id: null,
    status: "DISABLED",
  });
  // 跨租户引用：行存在（外键满足），但 A 的 scope 查不到 ⇒ `missing`
  await credentialsB.create({
    id: C_B,
    provider: "google",
    key_type: "api_key",
    encrypted_value: "env:v1:dGVuYW50LWIta2V5",
    name: "google-tenant-b",
    status: "ACTIVE",
    metadata: { masked_value: "***bbbb" },
  });
  await providersA.create({
    id: P_FOREIGN,
    name: "google-foreign-credential",
    type: "google",
    endpoint: null,
    credential_id: C_B,
    status: "ACTIVE",
  });
  await providersA.create({
    id: P_INACTIVE_KEY,
    name: "openai-old-key",
    type: "openai",
    endpoint: null,
    credential_id: C_DISABLED,
    status: "ACTIVE",
  });

  await providersB.create({
    id: P_B,
    name: "openai-tenant-b",
    type: "openai",
    endpoint: null,
    credential_id: null,
    status: "ACTIVE",
  });

  return { db, scopeA, scopeB, providersA, providersB, credentialsA, credentialsB };
}

test("夹具自检（防空档）：两个租户各有行，且仓储只读得到本租户", async () => {
  const { providersA, providersB, credentialsA } = await seed();
  const allA = await providersA.list();
  const allB = await providersB.list();
  assert.ok(allA.length > 0, "A 租户必须有供应商行，否则后面的断言只是空集通过");
  assert.equal(allA.length, 5);
  assert.equal(allB.length, 1);
  assert.equal((await credentialsA.list()).length, 2);
});

test("findByType：按 kind 取供应商；type 无命中 ⇒ null", async () => {
  const { providersA } = await seed();
  const compat = await providersA.findByType("openai-compatible");
  assert.ok(compat, "openai-compatible 必须命中（真连烟测要靠它解析）");
  assert.equal(compat.id, P_COMPAT);
  assert.equal(compat.name, "siliconflow");
  assert.equal(compat.endpoint, SILICONFLOW_ENDPOINT, "endpoint 就是 factory 的 baseURL 来源");
  assert.equal(await providersA.findByType("no-such-kind"), null);
});

test("findByType：跨租户不可见（A 的仓库取不到 B 的同 type 行）", async () => {
  const { providersA, providersB } = await seed();
  const fromB = await providersB.findByType("openai");
  assert.equal(fromB.id, P_B, "B 的 scope 只能拿到 B 的行");
  const fromA = await providersA.findByType("openai");
  assert.ok(fromA, "A 有 openai 行（夹具自检：不是空集）");
  assert.notEqual(fromA.id, P_B, "A 绝不能看到 B 的 openai 行");
});

test("listByStatus：只列该状态的行，且恒带租户谓词", async () => {
  const { providersA } = await seed();
  const active = await providersA.listByStatus(ACTIVE);
  const ids = active.map((row) => row.id).sort();
  assert.deepEqual(ids, [P_COMPAT, P_FOREIGN, P_INACTIVE_KEY, P_OPENAI].sort());
  assert.ok(!ids.includes(P_DISABLED), "DISABLED 不得出现在 ACTIVE 列表里");
  assert.ok(!ids.includes(P_B), "B 租户的行不得出现在 A 的列表里");

  const disabled = await providersA.listByStatus("DISABLED");
  assert.deepEqual(
    disabled.map((row) => row.id),
    [P_DISABLED],
  );
});

test("findActiveByType：kind + 状态双命中；状态不命中 ⇒ null；状态值可覆盖", async () => {
  const { providersA } = await seed();
  const compat = await providersA.findActiveByType("openai-compatible");
  assert.equal(compat.id, P_COMPAT);

  assert.equal(
    await providersA.findActiveByType("anthropic"),
    null,
    "anthropic 那行是 DISABLED ⇒ 不可用于出网",
  );
  const forced = await providersA.findActiveByType("anthropic", { activeStatus: "DISABLED" });
  assert.equal(forced.id, P_DISABLED, "显式指定状态值时应当命中（口径可覆盖，不是硬编码）");
});

test("resolveKeyCarrier：bound —— 供应商 + 可用 key 载体（Gateway 解析链路）", async () => {
  const { providersA, credentialsA, scopeA } = await seed();
  const carrier = await providersA.resolveKeyCarrier(scopeA.ref(P_COMPAT), credentialsA);
  assert.equal(carrier.credentialState, "bound");
  assert.equal(carrier.provider.type, "openai-compatible", "type ⇒ factory 的 kind");
  assert.equal(carrier.provider.endpoint, SILICONFLOW_ENDPOINT, "endpoint ⇒ factory 的 baseURL");
  assert.equal(carrier.credential.id, C_ACTIVE);
  assert.equal(carrier.credential.status, ACTIVE);
  assert.equal(carrier.credential.encrypted_value, "env:v1:ZXhhbXBsZS1jaXBoZXI=");
});

test("resolveKeyCarrier：unbound / missing / inactive 三种状态必须可区分", async () => {
  const { providersA, credentialsA, scopeA } = await seed();

  const unbound = await providersA.resolveKeyCarrier(scopeA.ref(P_OPENAI), credentialsA);
  assert.equal(unbound.credentialState, "unbound");
  assert.equal(unbound.credential, null);

  const missing = await providersA.resolveKeyCarrier(scopeA.ref(P_FOREIGN), credentialsA);
  assert.equal(
    missing.credentialState,
    "missing",
    "凭据行存在但不在本租户 scope 内 ⇒ missing，必须与「没绑」区分开（跨租户引用，不能当没配）",
  );
  assert.equal(missing.credential, null);
  assert.equal(missing.provider.credential_id, C_B, "外键满足（行存在），只是归属别的租户");

  const inactive = await providersA.resolveKeyCarrier(scopeA.ref(P_INACTIVE_KEY), credentialsA);
  assert.equal(inactive.credentialState, "inactive");
  assert.equal(inactive.credential, null);
  assert.equal(inactive.provider.credential_id, C_DISABLED, "凭据行存在，只是被禁用");
});

test("resolveKeyCarrier：供应商不可见 ⇒ null（而不是抛）", async () => {
  const { providersA, credentialsA, scopeA } = await seed();
  const carrier = await providersA.resolveKeyCarrier(scopeA.ref(P_B), credentialsA);
  assert.equal(carrier, null, "跨租户的 provider id ⇒ 查不到（→ 上层折 404）");
});

test("resolveKeyCarrier：跨租户 ref 抛 ScopeError（不是空结果）", async () => {
  const { providersA, credentialsA, scopeA, scopeB } = await seed();
  await assert.rejects(
    () => providersA.resolveKeyCarrier(scopeB.ref(P_B), credentialsA),
    (error) => {
      assert.ok(error instanceof ScopeError, `必须是 ScopeError，实测 ${String(error)}`);
      assert.match(error.message, /providerRef 不合法/);
      return true;
    },
  );
});

test("resolveKeyCarrier：凭据仓储属于别的租户 ⇒ ScopeError（fail loud）", async () => {
  const { providersA, credentialsB, scopeA } = await seed();
  await assert.rejects(
    () => providersA.resolveKeyCarrier(scopeA.ref(P_COMPAT), credentialsB),
    (error) => {
      assert.ok(error instanceof ScopeError, "跨租户取 key 载体必须炸，不能静默返回 null");
      assert.match(error.message, /仓储 scope 是/);
      return true;
    },
  );
});

test("裸 id / 伪造 ref 一律拒（品牌校验仍在）", async () => {
  const { providersA, credentialsA } = await seed();
  await assert.rejects(
    () => providersA.resolveKeyCarrier({ id: P_COMPAT, tenantId: T_A }, credentialsA),
    (error) => {
      assert.ok(error instanceof ScopeError);
      assert.match(error.message, /只接受 Scope#ref\(id\) 产出的 ScopedRef/);
      return true;
    },
  );
});

test("零 DDL 自证：本轮新增的读方法只用到既有列", async () => {
  const { providersA } = await seed();
  const columns = Object.keys(await providersA.findByType("openai-compatible"));
  assert.deepEqual(
    [...columns].sort(),
    [
      "config",
      "credential_id",
      "endpoint",
      "id",
      "name",
      "organization_id",
      "status",
      "tenant_id",
      "type",
      "workspace_id",
    ],
    "行键集合未变 ⇒ 本任务没有加列（零 DDL 的运行时证据）",
  );
});
