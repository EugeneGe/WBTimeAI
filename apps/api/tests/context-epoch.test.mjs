/**
 * T3-09 · 上下文构建（**从持久化重建** + epoch/压缩可审计 + 缓存观测）。
 *
 * 判据（卡面验收 ④ ⑤ + 反例 3）
 * --------------------------
 *   ① **从持久化消息重建，不靠内存**（反例 3）：A-1 用**两个互相看不见的 builder 实例**
 *      对同一批行各建一次，产物必须逐字相同 —— 若实现里有任何跨调用的内存态
 *      （缓存、上一轮的数组、模块级变量），第二次就会不同。
 *   ② **epoch / 压缩是可审计事实**：A-2 断压缩只丢"最早的非 system 消息"、
 *      system 与最近 N 条必须保留；A-3 断 epoch 只在压缩时 +1。
 *   ③ **缓存观测**（验收 ⑤）：A-6 断"动态字段不进上下文"—— 两次构建逐字相同，
 *      且消息内容与库里的 `content` **逐字相等**（不 trim、不加时间戳、不加 run_id）。
 *      这一条与 T3-02 的稳定前缀断言同源：前缀里一旦混进时间戳，prompt cache 命中率归零。
 *   ④ **非法 role 必须抛错**（不许按 user 处理 —— 那会让系统消息冒充用户发言）。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/context-epoch.test.mjs`
 */

import assert from "node:assert/strict";
import test from "node:test";

import { buildContext } from "../dist/modules/runtime/context-builder.js";
import { compactMessages, estimateTokens } from "../dist/modules/runtime/compaction.js";
import { conversationRows, messageRow } from "./fixtures/loop-fixture.mjs";

/** 宽松预算（不触发压缩）。 */
const ROOMY = { maxChars: 10_000, keepRecent: 4 };

// ---------------------------------------------------------------------------
// A 组 · 从持久化重建（反例 3）
// ---------------------------------------------------------------------------

test("A-1 · 两个**互不相识**的 builder 对同一批行产出逐字相同 ⇒ 没有内存态", () => {
  const rows = conversationRows(2); // system + 2×(user, assistant) = 5 条

  // 第一次：一个「全新」的调用（本文件没有模块级缓存，但这里显式强调语义）
  const first = buildContext(rows, ROOMY);
  // 第二次：同输入再建一次。若 builder 里有 `lastMessages` 之类的内存态，这里会漂移。
  const second = buildContext([...rows], { ...ROOMY });

  assert.deepEqual(
    second.messages,
    first.messages,
    "同一批持久化消息必须重建出逐字相同的上下文（反例 3：靠内存重建 ⇒ 红）"
  );
  assert.equal(first.messages.length, rows.length, "未压缩时条数不变");
  assert.equal(first.epoch, second.epoch);
});

test("A-2 · 输入只认 `MessageRow[]`：行序即上下文序（不重排）", () => {
  const rows = [
    messageRow("m1", "system", "S"),
    messageRow("m2", "user", "U1"),
    messageRow("m3", "assistant", "A1"),
  ];
  const built = buildContext(rows, ROOMY);
  assert.deepEqual(
    built.messages.map((message) => message.content),
    ["S", "U1", "A1"],
    "次序必须等于输入行序（仓储给的是 (created_at,id) 全序）"
  );
  assert.deepEqual(
    built.messages.map((message) => message.role),
    ["system", "user", "assistant"]
  );
});

// ---------------------------------------------------------------------------
// B 组 · 压缩与 epoch（验收 ④ 的可审计面）
// ---------------------------------------------------------------------------

test("B-1 · 超预算 ⇒ 丢最早的非 system 消息；system 与最近 N 条必须保留", () => {
  const rows = [
    messageRow("s1", "system", "你是助手"), // 10 字符
    messageRow("u1", "user", "第一条很长的用户消息"), // 11
    messageRow("a1", "assistant", "第一条很长的助手回复"), // 11
    messageRow("u2", "user", "最近一条用户"), // 6
    messageRow("a2", "assistant", "最近一条助手"), // 6
  ];
  const total = rows.reduce((sum, row) => sum + row.content.length, 0); // 44
  // ⚠️ 阈值要**小于** "system + 最近 N 条" 的字符数（10 + 12 = 22），否则实现
  // 会正确地判定"已经落回预算、无需丢弃" —— 首版写 30 就是这样假红的。
  const maxChars = 15;
  const keepRecent = 2; // 只保 u2 / a2

  const outcome = compactMessages(rows, { maxChars, keepRecent });

  assert.equal(outcome.applied, true);
  assert.ok(outcome.dropped.length > 0, "超预算必须丢");
  const keptIds = outcome.kept.map((row) => row.id);
  assert.ok(keptIds.includes("s1"), "system 永不丢（它是行为约束）");
  assert.ok(keptIds.includes("u2") && keptIds.includes("a2"), "最近 N 条永不丢");
  assert.ok(!keptIds.includes("u1"), "从**最早**的非 system 开始丢（u1 比 a1 早）");
  // a1 可能保留也可能被丢（取决于预算），但**丢的必须来自头部且按原序**
  const droppedIds = outcome.dropped.map((row) => row.id);
  assert.deepEqual(droppedIds, droppedIds.slice().sort((a, b) => rows.findIndex((r) => r.id === a) - rows.findIndex((r) => r.id === b)), "丢弃集必须按原序（从最早开始）");
  assert.equal(droppedIds[0], "u1", "第一条被丢的必须是最早的非 system 消息");
  assert.match(outcome.reason, /dropped \d+ 条/);

  // 丢的是**完整消息**，不是截断内容
  for (const row of outcome.kept) {
    const origin = rows.find((item) => item.id === row.id);
    assert.equal(row.content, origin.content, "保留的消息内容必须逐字不变");
  }
  assert.ok(total > maxChars, "前置：确实超预算");
});

test("B-2 · 未超预算 ⇒ 不压缩（`applied=false` 且 dropped 为空）", () => {
  const rows = conversationRows(1);
  const outcome = compactMessages(rows, ROOMY);
  assert.equal(outcome.applied, false);
  assert.deepEqual(outcome.dropped, []);
  assert.equal(outcome.reason, "within-budget");
  assert.equal(outcome.kept.length, rows.length);
});

test("B-3 · epoch：压缩才 +1；未压缩沿用父级", () => {
  const rows = conversationRows(3);
  const roomy = buildContext(rows, { ...ROOMY, parentEpoch: 7 });
  assert.equal(roomy.epoch, 7, "未压缩 ⇒ 沿用父级 epoch");

  // 同 B-1：阈值必须小于 "system + 最近 2 条"（6 + 8 = 14），取 10 才会真的丢。
  const tight = buildContext(rows, { maxChars: 10, keepRecent: 2, parentEpoch: 7 });
  assert.equal(tight.compaction.applied, true, "前置：确实压缩了");
  assert.equal(tight.epoch, 8, "压缩 ⇒ epoch +1（上下文换了一版）");
});

test("B-4 · 压到底仍超限 ⇒ `oversize=true` 且**不再继续丢**（交由 tokens 预算收尾）", () => {
  const rows = [
    messageRow("s1", "system", "一个非常非常非常长的系统提示词".repeat(10)),
    messageRow("u1", "user", "短"),
  ];
  const outcome = compactMessages(rows, { maxChars: 10, keepRecent: 2 });
  // keepRecent=2 时尾部包含 s1 与 u1 ⇒ 整条都在保留区，没有可丢的
  assert.equal(outcome.dropped.length, 0, "没有可丢的（system 与最近 N 条都被锁定）");
  assert.equal(outcome.oversize, true, "必须显式标记超限，让 tokens 预算去收尾");
  assert.match(outcome.reason, /still-oversize/);
});

// ---------------------------------------------------------------------------
// C 组 · 缓存观测（验收 ⑤）
// ---------------------------------------------------------------------------

test("C-1 · 上下文里**没有动态字段**：消息内容与库里的 content 逐字相等", () => {
  const rows = conversationRows(2);
  const built = buildContext(rows, ROOMY);

  for (let index = 0; index < built.messages.length; index += 1) {
    const message = built.messages[index];
    const origin = rows[index];
    assert.equal(
      message.content,
      origin.content,
      "内容必须逐字等于库里的 content（trim / 拼接时间戳 / 插 run_id 都会破坏 prompt cache 前缀）"
    );
    // 不允许出现时间戳样式的注入
    assert.equal(
      /\[\d{2}:\d{2}:\d{2}\]|\d{4}-\d{2}-\d{2}T\d{2}/.test(message.content),
      false,
      "上下文不得注入时间戳"
    );
    // ModelMessage 只应有 role / content（本卡不产出 toolCalls —— 那是 assistant 历史的一部分，
    // 由 message.content_parts 承载，归 T3-09 之后的回放增强；现在带上会让前缀不稳定）
    assert.deepEqual(Object.keys(message).sort(), ["content", "role"]);
  }
});

test("C-2 · 同一批行连续构建 5 次，产物完全一致（稳定前缀的直接判据）", () => {
  const rows = conversationRows(3);
  const first = JSON.stringify(buildContext(rows, ROOMY).messages);
  for (let round = 0; round < 5; round += 1) {
    assert.equal(
      JSON.stringify(buildContext(rows, ROOMY).messages),
      first,
      `第 ${round + 2} 次构建与第 1 次不同 —— 前缀不稳定`
    );
  }
});

// ---------------------------------------------------------------------------
// D 组 · 输入防御
// ---------------------------------------------------------------------------

test("D-1 · 非法 role ⇒ 抛错（不得按 user 处理：那会让消息冒充用户发言）", () => {
  const rows = [messageRow("x1", "robot", "我不是四种角色之一")];
  assert.throws(
    () => buildContext(rows, ROOMY),
    /不在 system\/user\/assistant\/tool 内/,
    "未知角色必须抛错"
  );
});

test("D-2 · `content` 为空 / null 也不崩（回落空串）", () => {
  const rows = [
    { ...messageRow("n1", "user", ""), content: null },
    messageRow("n2", "assistant", ""),
  ];
  const built = buildContext(rows, ROOMY);
  assert.deepEqual(
    built.messages.map((message) => message.content),
    ["", ""]
  );
});

test("D-3 · token 估算是**保守上界**（字符/4 向上取整），只用于压缩阈值", () => {
  assert.equal(estimateTokens(0), 0);
  assert.equal(estimateTokens(1), 1);
  assert.equal(estimateTokens(4), 1);
  assert.equal(estimateTokens(5), 2);
  assert.equal(estimateTokens(4000), 1000);
});
