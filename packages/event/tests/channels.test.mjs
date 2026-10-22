// T1-02 · @wbtime/event：通道集合与 contracts/sse/channels.json（+ V0.3.1 delta）全等。

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SSE_CHANNEL_LIST,
  SSE_CHANNEL_SPECS,
  channelSpec,
  isSseChannel,
} from "../dist/index.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const contract = JSON.parse(
  readFileSync(join(ROOT, "contracts", "sse", "channels.json"), "utf8"),
);
// V0.3.1 · T031-05：生成面 = 基线 19 项 + delta 2 项（subagent.*，T031-01 契约）。
const delta = JSON.parse(
  readFileSync(join(ROOT, "contracts", "sse", "channels.delta.json"), "utf8"),
);
const allChannels = [...contract.channels, ...delta.channels];

test("通道集合与契约逐项全等（数量 + 每个通道名，按契约 index 顺序：基线在前、delta 追加）", () => {
  const expected = allChannels.map((c) => c.channel);
  assert.equal(SSE_CHANNEL_LIST.length, expected.length, "通道数量必须与契约（基线 + delta）一致");
  assert.deepEqual([...SSE_CHANNEL_LIST], expected);
});

test("空集合必红：通道清单非空", () => {
  assert.ok(SSE_CHANNEL_LIST.length > 0, "通道清单不得为空");
});

test("每条通道的 payload 键序与契约一致（基线 + delta 逐条）", () => {
  for (const c of allChannels) {
    assert.deepEqual(
      [...channelSpec(c.channel).payloadKeysInOrder],
      c.payload_keys_in_order,
      `${c.channel} 键序漂移`,
    );
  }
});

// ---------------------------------------------------------------------------
// 必填键：逐通道 19/19 全等，而不是"生成器大致算对了"
//
// 上面两条（键序全等 + 行为用例）能证明"键序对"和"缺键会抛"，但都不能证明
// **生成器把 required 标记算对了**：假如生成器漏掉某个通道的必填键，
// `buildEventPayload` 只会少校验一个键 —— 行为用例照样绿。这条把判据提升为
// 「逐项全等」：期望值直接从契约现算，与生成物逐通道比对。
// ---------------------------------------------------------------------------
test("每条通道的 requiredPayloadKeys ≡ 契约 payload_fields[*].required（逐项全等，基线 + delta）", () => {
  assert.equal(allChannels.length, SSE_CHANNEL_LIST.length, "先确认两边通道数同源");

  for (const c of allChannels) {
    const expected = c.payload_keys_in_order.filter(
      (key) => (c.payload_fields ?? {})[key]?.required === true,
    );
    assert.deepEqual(
      [...channelSpec(c.channel).requiredPayloadKeys],
      expected,
      `${c.channel} 的必填键漂移（期望 = 键序中 required === true 的键，保持键序）`,
    );
  }
});

test("未知通道被拒绝，不静默降级", () => {
  assert.equal(isSseChannel("agent.started"), true);
  assert.equal(isSseChannel("agent.nonexistent"), false);
  assert.throws(() => channelSpec("agent.nonexistent"), /未知 SSE 通道/);
});
