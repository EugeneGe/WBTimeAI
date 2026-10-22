/**
 * T3-12 · `ModelRepo`（`model` 子表）+ `ModelProviderRepo.disable`（软删）的仓储层证明。
 *
 * 为什么单独立文件：`b2-*.test.mjs` 覆盖的是 T3-03 的 11 张身份表与运行时族，
 * `model` 表在 T3-12 之前**根本没有仓储**（只有 provider / credential 两张）。
 * 这一层的判据与本卡的服务层判据不同（那里证 HTTP 形状，这里证**隔离与写语义**），
 * 混写会让"哪一条红了"说不清 —— 同 T3-07 的 `message-order.test.mjs` 先例。
 *
 * 判据（6 条，名字即判据）：
 *   1. `create` **注入父列**：调用方传不进 `provider_id`（类型层 `never` + 库里等于父引用）；
 *   2. `list` 只返**本 provider** 的模型（同租户另一个 provider 的行不得混入）；
 *   3. 父是**别租户**的 provider ⇒ `ScopeError`（父不可见，不是"返回空数组"）；
 *   4. 父 id **不存在** ⇒ `ScopeError`（同上，且与"跨租户"同一形态，不泄漏存在性）；
 *   5. `disable` 是**软删**：`status = DISABLED` 且行仍在、可重复（幂等）；
 *   6. `disable` 打**别租户**的 provider ⇒ `null`（→ 服务层折 404），且那一行**不被改动**。
 *
 * 反例（注入即红）：
 *   - 把 `ModelRepo` 的 `parentExists` 换成恒 `true` ⇒ 第 3/4 条红（父谓词失效）；
 *   - 把 `disable` 改成 `remove` ⇒ 第 5 条"行仍在"红（软删变真删）。
 *
 * 复跑：`cd packages/db && npx tsc -b && node --experimental-sqlite --test tests/model-repo.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { ModelProviderRepo, ModelRepo, Scope, ScopeError } from "../dist/repositories/index.js";

import { DIALECT, freshConnection, seedParents, T_A, T_B } from "./fixtures/runtime-fixture.mjs";

/** 本文件的 provider id（两租户各一 + 同租户第二个）。 */
const P_A = "aaaa0000-0000-4000-8000-0000000000e1";
const P_A2 = "aaaa0000-0000-4000-8000-0000000000e2";
const P_B = "bbbb0000-0000-4000-8000-0000000000e3";

/** 不存在的 provider id（"父真的没有"的对照）。 */
const P_MISSING = "f0000000-0000-4000-8000-0000000000ef";

/** 直接插 provider 行（不走被测仓储 —— 夹具必须独立于被测代码）。 */
function seedProviders(connection) {
  const insert = connection.raw.prepare(
    `insert into model_provider (id, tenant_id, organization_id, workspace_id, name, type, endpoint, credential_id, status, config)
     values (?, ?, null, null, ?, ?, null, null, ?, '{}')`
  );
  insert.run(P_A, T_A, "provider-a", "openai", "ACTIVE");
  insert.run(P_A2, T_A, "provider-a2", "openai", "ACTIVE");
  insert.run(P_B, T_B, "provider-b", "openai", "ACTIVE");
}

/** 建好两租户父链 + 三个 provider 的连接。 */
function seeded() {
  const connection = freshConnection();
  seedParents(connection);
  seedProviders(connection);
  return connection;
}

test("1 · create 注入父列：调用方传不进 provider_id，库里等于父引用", async () => {
  const connection = seeded();
  try {
    const scope = new Scope(T_A);
    const repo = new ModelRepo(connection.db, scope, scope.ref(P_A), DIALECT);

    const created = await repo.create({ name: "gpt-4o", contextWindow: 128000 });
    assert.equal(created.provider_id, P_A, "父列必须由基类注入");
    assert.equal(created.name, "gpt-4o");
    assert.equal(created.type, "CHAT", "缺省 modelType ⇒ CHAT（契约 default）");
    assert.equal(created.context_window, 128000);
    assert.equal(created.status, "ACTIVE");

    // 对照：库里就一行，且 provider_id 对得上
    const rows = connection.raw.prepare("select provider_id from model").all();
    assert.equal(rows.length, 1);
    assert.equal(rows[0].provider_id, P_A);
  } finally {
    connection.close();
  }
});

test("2 · list 只返本 provider 的模型（同租户另一个 provider 不串流）", async () => {
  const connection = seeded();
  try {
    const scope = new Scope(T_A);
    const first = new ModelRepo(connection.db, scope, scope.ref(P_A), DIALECT);
    const second = new ModelRepo(connection.db, scope, scope.ref(P_A2), DIALECT);

    await first.create({ name: "model-a-1" });
    await first.create({ name: "model-a-2" });
    await second.create({ name: "model-a2-1" });

    const firstRows = await first.list();
    const secondRows = await second.list();

    assert.deepEqual(firstRows.map((row) => row.name).sort(), ["model-a-1", "model-a-2"]);
    assert.deepEqual(secondRows.map((row) => row.name), ["model-a2-1"]);
  } finally {
    connection.close();
  }
});

test("3 · 父是别租户的 provider ⇒ ScopeError（不是返回空数组）", async () => {
  const connection = seeded();
  try {
    // 本 scope 铸造的 ref，但 id 指向别租户的 provider：
    // `owns()` 只看铸造来源（mint provenance），拦不住这一格 —— 只有父查询能拦。
    const scopeA = new Scope(T_A);
    const repo = new ModelRepo(connection.db, scopeA, scopeA.ref(P_B), DIALECT);

    await assert.rejects(
      () => repo.create({ name: "越权模型" }),
      (error) => {
        assert.ok(error instanceof ScopeError, "父不可见必须抛 ScopeError");
        return true;
      }
    );
    await assert.rejects(() => repo.list(), (error) => error instanceof ScopeError);

    // 越权行**没有**落地（这是比"抛没抛错"更硬的判据）
    assert.equal(connection.raw.prepare("select count(*) as n from model").get().n, 0);
  } finally {
    connection.close();
  }
});

test("4 · 父 id 不存在 ⇒ ScopeError（与跨租户同一形态，不泄漏存在性）", async () => {
  const connection = seeded();
  try {
    const scope = new Scope(T_A);
    const repo = new ModelRepo(connection.db, scope, scope.ref(P_MISSING), DIALECT);
    await assert.rejects(
      () => repo.create({ name: "x" }),
      (error) => error instanceof ScopeError
    );
    assert.equal(connection.raw.prepare("select count(*) as n from model").get().n, 0);
  } finally {
    connection.close();
  }
});

test("5 · disable 是软删：status=DISABLED、行仍在、可重复（幂等）", async () => {
  const connection = seeded();
  try {
    const scope = new Scope(T_A);
    const repo = new ModelProviderRepo(connection.db, scope, DIALECT);

    const disabled = await repo.disable(scope.ref(P_A));
    assert.notEqual(disabled, null);
    assert.equal(disabled.status, "DISABLED");

    // 硬判据：行仍在（真删这里会是 0）
    const rows = connection.raw
      .prepare("select status from model_provider where id = ?")
      .all(P_A);
    assert.equal(rows.length, 1, "软删：行必须仍在");
    assert.equal(rows[0].status, "DISABLED");

    // 重复禁用幂等（py 只看存在性、不看当前状态）
    const again = await repo.disable(scope.ref(P_A));
    assert.equal(again.status, "DISABLED");
  } finally {
    connection.close();
  }
});

test("6 · disable 打别租户 ⇒ null，且那一行不被改动", async () => {
  const connection = seeded();
  try {
    const scopeA = new Scope(T_A);
    const repoA = new ModelProviderRepo(connection.db, scopeA, DIALECT);

    const result = await repoA.disable(scopeA.ref(P_B));
    assert.equal(result, null, "跨租户 ⇒ null（→ 服务层折 404）");

    const row = connection.raw
      .prepare("select status from model_provider where id = ?")
      .get(P_B);
    assert.equal(row.status, "ACTIVE", "别租户的行不得被改动");
  } finally {
    connection.close();
  }
});
