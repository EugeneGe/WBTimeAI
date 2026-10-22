/**
 * V0.2.0 审计 #23 · SQLite 布尔列读回兜底的**行为锁**（仅测试档）。
 *
 * 三条判据（逐条可断言）：
 *  ① SQLite 裸读回（`node:sqlite` 原生行）：`tenant.is_active` 是 **integer 1**，
 *     naive `=== true` 在它上面**恒 false**（这正是 #23 的缺陷形态，钉成断言），
 *     兜底谓词 `boolFromDriver` 判真 —— 「空档不再静默」；
 *  ② PG 真 boolean 形状不受影响：`boolFromDriver(true) === true` 且
 *     `boolFromDriver(false) === false`（同一谓词，两档同断言）；
 *  ③ 谓词不是永真：其他形状（0 / "1" / "true" / null / undefined）一律判假，
 *     防止兜底被放宽成「有值就算真」。
 *
 * 用真库（DDL 61 表 + 真插入 + 真读回），不 mock 驱动行。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { boolFromDriver } from "./support/bool-readback.mjs";
import { freshDb, seedTenant, TENANT_ID } from "./auth-harness.mjs";

test("#23 ① SQLite 裸读回是 integer 1：naive === true 恒 false（缺陷形态钉死），兜底判真", () => {
  const connection = freshDb();
  try {
    seedTenant(connection.raw, { id: TENANT_ID, slug: "bool-readback", isActive: 1 });

    const row = connection.raw
      .prepare("SELECT is_active FROM tenant WHERE id = ?")
      .get(TENANT_ID);

    // 裸读回形状自证：SQLite 原生行给的是 number，不是 boolean。
    assert.equal(typeof row.is_active, "number", "SQLite 裸读回的布尔列是 integer");
    assert.equal(row.is_active, 1, "启用租户读回 1");

    // #23 缺陷形态（钉死，防回归）：naive 判等在裸读回上静默失败。
    assert.equal(
      row.is_active === true,
      false,
      "naive `is_active === true` 在 SQLite 裸读回上必须为 false —— 这就是 #23 要兜的底；若这里变 true，说明驱动行为已变，应改判据而非放宽",
    );

    // 兜底判真：同一份测试代码在 SQLite 档拿到正确语义。
    assert.equal(boolFromDriver(row.is_active), true, "兜底谓词对 SQLite integer 1 判真");
  } finally {
    connection.close();
  }
});

test("#23 ② PG 真 boolean 形状不受影响（同一谓词，两档同断言）", () => {
  // PG 档 `tenant.is_active` 读回 JS boolean（pg 驱动类型解析）；PG 真跑由
  // `test:parity:pg`（需 WBTIME_PG_URL）承载 —— 这里锁的是**谓词形状**：
  // 真 boolean 走同一个兜底时语义不变（true 进 true 出）。
  assert.equal(boolFromDriver(true), true, "PG 真 boolean true 判真");
  assert.equal(boolFromDriver(false), false, "PG 真 boolean false 判假");
  assert.equal(boolFromDriver(0), false, "SQLite 停用行（0）判假");
});

test("#23 ③ 兜底不是永真：其他形状一律判假", () => {
  for (const value of [0, "1", "true", "true ", 2, -1, null, undefined, NaN, {}, []]) {
    assert.equal(
      boolFromDriver(value),
      false,
      `兜底谓词对 ${String(value)}（${typeof value}）必须判假 —— 只放行 true / 1`,
    );
  }
});
