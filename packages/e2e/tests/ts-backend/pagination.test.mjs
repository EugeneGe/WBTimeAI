/**
 * T2-10 · TS 后端冒烟 case 2 —— 列表语义（对齐 py `tests/e2e/pagination.test.mjs` 的裁定面）。
 *
 * **先读 py 版断言后的语义裁定**：py case-4 的可观测断言是「分页参数真的切集合」——
 * 两个对象经 `?page=1&page_size=1` / `?page=2&page_size=1` 必须给出**不同 id**，且同一页
 * 两次调用结果一致（确定性）。TS 后端 19 op **没有带 page/page_size/limit 查询参数的
 * 列表 op**（实测：`/organizations`、`/models/credentials`、`/tools/permissions` 均无
 * 分页入参；仓储层 limit 固定 500，非调用方可观测）。因此「切集合」语义在 TS 后端
 * 本版**不可测**，本 case 落在其可测的等价面 —— py 断言里不依赖分页参数的另一半：
 *
 *   1. **列表完整性**：新建 3 条凭据后，`GET /api/v1/models/credentials` 的 `data`
 *      必须恰好包含这 3 条 id（多 / 少 / 错都是红）；
 *   2. **确定性**：同一列表连打两次，id 序列逐位相等（排序不抖动 —— py case 的
 *      「page=1 两次调用返回同一对象」在无分页参数时的直译）；
 *   3. **响应形状**：200 + 四键壳 + `data` 为数组 + 行含 `masked_value`（列表不解密）。
 *
 * 「分页参数不可测」如实登记于 `T2-10.md`；不许 mock 一个假分页参数装作已验证。
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { assertTsEvidence, registerAndLogin, startTsBackend } from "./_backend.mjs";

test("case-2-ts-pagination：列表完整性 + 确定性（TS 后端无分页参数，等价面见文件头）", { timeout: 120_000 }, async () => {
  const backend = await startTsBackend("pagination");
  try {
    const { token } = await registerAndLogin(backend.baseUrl, `ts_page_${Date.now()}`);
    const headers = { authorization: `Bearer ${token}`, "content-type": "application/json" };

    // ── 建集合：3 条凭据（真实 HTTP 写入面） ────────────────────────────────
    const createdIds = [];
    for (const [index, value] of ["sk-smoke-aaa", "sk-smoke-bbb", "sk-smoke-ccc"].entries()) {
      const created = await fetch(`${backend.baseUrl}/api/v1/models/credentials`, {
        method: "POST",
        headers,
        body: JSON.stringify({ provider: "openai", value }),
        signal: AbortSignal.timeout(10_000),
      });
      assertTsEvidence(created, backend);
      assert.equal(created.status, 201, `第 ${index + 1} 条凭据期望 201，实得 ${created.status}`);
      const createdBody = await created.json();
      assert.equal(typeof createdBody.data?.id, "string", "create 必须回 id");
      assert.match(createdBody.data.masked_value, /^\*+/, "create 只回掩码，不回明文");
      createdIds.push(createdBody.data.id);
    }
    assert.equal(new Set(createdIds).size, 3, "3 条凭据的 id 应互不相同");

    // ── 1. 列表完整性 ──────────────────────────────────────────────────────
    const first = await fetch(`${backend.baseUrl}/api/v1/models/credentials`, {
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(10_000),
    });
    assertTsEvidence(first, backend);
    assert.equal(first.status, 200, `列表期望 200，实得 ${first.status}`);
    const firstBody = await first.json();
    assert.deepEqual(
      Object.keys(firstBody).sort(),
      ["code", "data", "message", "request_id"],
      "列表必须是契约四键成功壳",
    );
    assert.equal(firstBody.code, 0, "成功壳 code 必须 0");
    assert.ok(Array.isArray(firstBody.data), "data 应为数组");
    assert.equal(firstBody.data.length, 3, `空库新建 3 条后列表应恰 3 条，实得 ${firstBody.data.length}`);
    const listedIds = firstBody.data.map((row) => row?.id).sort();
    assert.deepEqual(listedIds, [...createdIds].sort(), "列表 id 集合必须与新建集合一致（完整性）");
    for (const row of firstBody.data) {
      assert.equal(typeof row.masked_value, "string", "列表行必须带 masked_value（掩码，不解密）");
      assert.equal(
        Object.prototype.hasOwnProperty.call(row, "encrypted_value"),
        false,
        "列表不得回信封/明文字段",
      );
    }

    // ── 2. 确定性：同一列表两次调用的 id 序列逐位相等 ────────────────────────
    const second = await fetch(`${backend.baseUrl}/api/v1/models/credentials`, {
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(10_000),
    });
    assertTsEvidence(second, backend);
    assert.equal(second.status, 200, `第二次列表期望 200，实得 ${second.status}`);
    const secondBody = await second.json();
    const firstSequence = firstBody.data.map((row) => row.id);
    const secondSequence = secondBody.data.map((row) => row.id);
    assert.deepEqual(
      secondSequence,
      firstSequence,
      `同一列表两次调用的顺序不一致（排序抖动）：${JSON.stringify(firstSequence)} vs ${JSON.stringify(secondSequence)}`,
    );
  } finally {
    await backend.stop();
  }
});
