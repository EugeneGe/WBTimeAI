// T1-02 · @wbtime/event：通道集合与 contracts/sse/channels.json 全等。

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

test("通道集合与契约逐项全等（数量 + 每个通道名，按契约 index 顺序）", () => {
  const expected = contract.channels.map((c) => c.channel);
  assert.equal(SSE_CHANNEL_LIST.length, expected.length, "通道数量必须与契约一致");
  assert.deepEqual([...SSE_CHANNEL_LIST], expected);
});

test("空集合必红：通道清单非空", () => {
  assert.ok(SSE_CHANNEL_LIST.length > 0, "通道清单不得为空");
});

test("每条通道的 payload 键序与契约一致", () => {
  for (const c of contract.channels) {
    assert.deepEqual(
      [...channelSpec(c.channel).payloadKeysInOrder],
      c.payload_keys_in_order,
      `${c.channel} 键序漂移`,
    );
  }
});

test("未知通道被拒绝，不静默降级", () => {
  assert.equal(isSseChannel("agent.started"), true);
  assert.equal(isSseChannel("agent.nonexistent"), false);
  assert.throws(() => channelSpec("agent.nonexistent"), /未知 SSE 通道/);
});
