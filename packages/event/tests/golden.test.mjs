// T2-08 · SSE 帧逐字节（K-7 / K-8 / K-9 / K-10）+ 错误码映射复跑（K-5）
//
// 口径来源：`docs/V1.0/V0.2.0-身份与HTTP垂直切片/01-计划/02-响应壳与SSE.md` §4 / §7。
//
// 两条硬纪律写在这里，避免后来人「顺手优化」：
//   1. **遍历只许 `channels[].golden`**（19 条）。**禁** `glob("golden/*.txt")` ——
//      `contracts/sse/golden/` 实有 **20** 个文件，第 20 个是
//      `_guard-float-normalization.txt`（契约 `guard.is_official_channel_golden === false`），
//      glob 会把它误当第 20 条通道，于是「19 通道」的断言变成「20 条里有 19 条通过」。
//   2. 期望值**全部运行时读契约**。写死 sha / 字节数 = 自己跟自己比，契约一变照样绿。
//
// 数字是判据本身：`Σbytes` 差一个字节也必须红，不接受「基本一致」。

import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import assert from "node:assert/strict";
import { test } from "node:test";

import { ERROR_HTTP_STATUS } from "@wbtime/core";

import {
  DATA_FRAME_TEMPLATE,
  EventPayloadError,
  HEARTBEAT_TEMPLATE,
  NUMERIC_FIXED_DECIMALS,
  PAYLOAD_PROJECTIONS,
  SSE_CHANNEL_LIST,
  UnknownChannelError,
  buildEventPayload,
  encodeDataFrame,
  encodeHeartbeat,
  normalizePayload,
  projectPayload,
} from "../dist/index.js";

/** 仓库根（packages/event/tests → packages/event → packages → 根）。 */
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const SSE_DIR = join(ROOT, "contracts", "sse");
const GOLDEN_DIR = join(SSE_DIR, "golden");

function readJson(absolutePath) {
  return JSON.parse(readFileSync(absolutePath, "utf8"));
}

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

const channels = readJson(join(SSE_DIR, "channels.json"));
const errorsContract = readJson(join(ROOT, "contracts", "errors.json"));

/** 正式通道 golden 的绝对路径（**只**从 `channels[].golden` 取，不用 glob）。 */
function goldenPathOf(channelSpec) {
  return join(SSE_DIR, channelSpec.golden);
}

/** 用契约 `constructor.kwargs` 造出该通道的线上 payload（装配 + 归一化 + 投影）。 */
function payloadOf(channelSpec) {
  return buildEventPayload(channelSpec.channel, channelSpec.constructor.kwargs ?? {});
}

function frameOf(channelSpec, seq = channelSpec.frame.seq) {
  return encodeDataFrame(seq, channelSpec.channel, payloadOf(channelSpec));
}

// ─────────────────────────────────────────────────────────────────────────────
// K-7 · 19/19 逐字节
// ─────────────────────────────────────────────────────────────────────────────

test("K-7 遍历面：契约 19 条通道、19 个 golden，且 guard 帧不在通道清单里", () => {
  assert.equal(channels.channels.length, 19, "契约通道数量必须是 19");
  assert.equal(channels.meta.golden_file_count, 19);
  assert.ok(channels.channels.length > 0, "通道清单不得为空（空集不是 PASS）");

  const declared = channels.channels.map((spec) => spec.golden);
  assert.equal(new Set(declared).size, 19, "19 条通道的 golden 路径不得重复");
  assert.ok(
    !declared.includes("golden/_guard-float-normalization.txt"),
    "guard 帧不得出现在 channels[].golden 里（它不是第 20 条通道）",
  );

  // 磁盘上确实有 23 个 .txt：19 正式 + 1 guard + 2 delta（V0.3.1 · T031-01）+ 1 keys 序列化。
  // 这条断言的作用是**记录**这个陷阱：若有人把遍历改成 glob，条数会从 19 跳成 23。
  // delta 三个文件不是第 20+ 条通道 —— 它们只由下方的 K-9-delta 校验，不进本文件的
  // `channels[].golden` 遍历（channels.json 的 19 项与 delta 是两份契约、两套校验）。
  const onDisk = readdirSync(GOLDEN_DIR).filter((name) => name.endsWith(".txt"));
  assert.equal(
    onDisk.length,
    23,
    "golden 目录应为 19 正式 + 1 guard + 2 delta（subagent.started/finished）+ 1 keys = 23 个文件",
  );
  assert.equal(channels.meta.guard_file_count, 1);
});

test("K-7① 19 个 golden 的 sha256 与契约 golden_sha256 全等", () => {
  let checked = 0;
  for (const spec of channels.channels) {
    const bytes = readFileSync(goldenPathOf(spec));
    assert.equal(
      sha256(bytes),
      spec.golden_sha256,
      `${spec.channel}: 磁盘 golden 的 sha256 与契约不一致`,
    );
    assert.equal(bytes.length, spec.frame.bytes, `${spec.channel}: 字节数与契约 frame.bytes 不一致`);
    checked += 1;
  }
  assert.equal(checked, 19, "必须逐个校验完 19 条（少循环一条就是漏判）");
});

test("K-7② 19/19 帧字节全等（encodeDataFrame(Buffer).equals(golden)）", () => {
  const failures = [];
  for (const spec of channels.channels) {
    const golden = readFileSync(goldenPathOf(spec));
    const actual = frameOf(spec);
    if (!actual.equals(golden)) {
      failures.push(
        `${spec.channel}\n  got : ${JSON.stringify(actual.toString("utf8"))}\n  want: ${JSON.stringify(golden.toString("utf8"))}`,
      );
    }
  }
  assert.deepEqual(failures, [], `逐字节失配 ${failures.length} 条`);
});

test("K-7③ Σbytes === 2402（契约 meta.frame_bytes_total）", () => {
  let total = 0;
  for (const spec of channels.channels) {
    total += frameOf(spec).length;
  }
  assert.equal(total, 2402, "19 帧字节总和必须等于契约 2402");
  assert.equal(channels.meta.frame_bytes_total, 2402, "契约侧总数也必须是 2402");
  assert.equal(total, channels.meta.frame_bytes_total);
});

test("K-7 格式不变量：LF only / 以空行结尾 / 行布局逐字符合契约模板", () => {
  // 契约把模板以**转义形态**存放（`\n` 是两个字符：反斜杠 + n，见 `frame_format.data_frame.template`），
  // 而真实帧里的行尾是真的 LF。因此比对时先还原转义 —— 这不是放宽，因为真正的判据是
  // golden 字节与 sha256（K-7①/② 已逐条钉住），模板只用来核对行布局。
  const unescapeNewlines = (template) => template.replaceAll("\\n", "\n");
  assert.equal(DATA_FRAME_TEMPLATE, unescapeNewlines(channels.frame_format.data_frame.template));
  assert.equal(channels.frame_format.line_endings.startsWith("LF only"), true);

  for (const spec of channels.channels) {
    const text = frameOf(spec).toString("utf8");
    assert.equal(text.includes("\r"), false, `${spec.channel}: 帧内出现 CR`);
    assert.equal(text.endsWith("\n\n"), true, `${spec.channel}: 帧必须以空行结尾`);

    const lines = text.split("\n");
    assert.equal(lines[0], `id: ${spec.frame.seq}`, `${spec.channel}: id 行不符`);
    assert.equal(lines[1], `event: ${spec.channel}`, `${spec.channel}: event 行不符`);
    assert.equal(lines[2].startsWith("data: "), true, `${spec.channel}: data 行不符`);
    assert.equal(lines[3], "", `${spec.channel}: 第 4 行必须是空行`);
    assert.equal(lines[4], "", `${spec.channel}: 第 5 行必须是空行（帧尾）`);
    assert.equal(lines.length, 5, `${spec.channel}: 帧行数必须是 5（含末尾两个空行）`);
  }
});

test("K-7 JSON 口径：CJK 原样（禁 \\uXXXX）、紧凑无空格、键序 == 契约键序", () => {
  const messageDelta = channels.channels.find((spec) => spec.channel === "message.delta");
  const text = frameOf(messageDelta).toString("utf8");

  // ensure_ascii=False 的真陷阱：转义即红（契约 §4.2 实测佐证）
  assert.ok(text.includes("你好，世界"), "CJK 必须原样出现在帧里");
  assert.equal(/\\u[0-9a-fA-F]{4}/.test(text), false, "不得出现 \\uXXXX 转义");

  const json = text.split("\n")[2].slice("data: ".length);
  assert.equal(json.includes('": '), false, "separators=(',',':') ⇒ 冒号后不得有空格");
  assert.equal(json.includes('", "'), false, "separators=(',',':') ⇒ 逗号后不得有空格");
  assert.deepEqual(
    Object.keys(JSON.parse(json)),
    messageDelta.projected_fields,
    "线上键序必须等于契约 projected_fields",
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// K-8 · 浮点守卫帧
// ─────────────────────────────────────────────────────────────────────────────

test("K-8 浮点守卫帧字节全等（0.5 → \"0.500000\" / 1.0 → 1 / -0.0 → 0）", () => {
  const contractGuard = channels.guard;
  assert.equal(contractGuard.is_official_channel_golden, false, "guard 不是第 20 条通道");
  assert.equal(contractGuard.channel, "agent.completed");
  assert.equal(NUMERIC_FIXED_DECIMALS, 6, "定点小数位数由契约 example 解析而来");

  // 期望键序来自契约（归一化后的 JSON 串），不手写。
  const expectedJson = contractGuard.normalized_data_json;
  const order = Object.keys(JSON.parse(expectedJson));

  // 基础实例 = agent.completed 的契约 kwargs；再注入契约 guard.injected 的 4 个浮点
  // （契约原文：score=0.5 / ratio=1.0 / neg_zero=-0.0 / nested={'score': 0.25}）。
  const base = payloadOf(channels.channels.find((spec) => spec.channel === "agent.completed"));
  const injected = { score: 0.5, ratio: 1, neg_zero: -0, nested: { score: 0.25 } };
  const rawValues = { ...base, ...injected };

  // 按契约期望键序重排（键序是判据的一部分，不能靠对象字面量凑巧的顺序）
  const rawPayload = {};
  for (const key of order) rawPayload[key] = rawValues[key];

  const normalized = normalizePayload(rawPayload);
  assert.equal(
    JSON.stringify(normalized),
    expectedJson,
    "归一化结果必须与契约 guard.normalized_data_json 逐字相等",
  );

  const frame = encodeDataFrame(contractGuard.seq, contractGuard.channel, normalized);
  const golden = readFileSync(join(SSE_DIR, contractGuard.file));
  assert.equal(frame.equals(golden), true, "浮点守卫帧必须逐字节全等");
  assert.equal(sha256(frame), contractGuard.sha256, "浮点守卫帧 sha256 必须等于契约值");

  // 逐项点名（肉眼可核，不靠字符串整串比对兜住）
  const data = JSON.parse(frame.toString("utf8").split("\n")[2].slice("data: ".length));
  assert.equal(data.score, "0.500000");
  assert.equal(data.ratio, 1);
  assert.equal(data.neg_zero, 0);
  assert.equal(data.nested.score, "0.250000");
});

test("K-8 反例：不做归一化就不等（证明这条断言不是哑真）", () => {
  const contractGuard = channels.guard;
  const order = Object.keys(JSON.parse(contractGuard.normalized_data_json));
  const base = payloadOf(channels.channels.find((spec) => spec.channel === "agent.completed"));
  const rawValues = { ...base, score: 0.5, ratio: 1, neg_zero: -0, nested: { score: 0.25 } };
  const rawPayload = {};
  for (const key of order) rawPayload[key] = rawValues[key];

  const rawFrame = encodeDataFrame(contractGuard.seq, contractGuard.channel, rawPayload);
  const golden = readFileSync(join(SSE_DIR, contractGuard.file));
  assert.equal(
    rawFrame.equals(golden),
    false,
    "原始浮点直接上帧竟然等于 golden ⇒ 归一化断言是假绿",
  );
  assert.ok(rawFrame.toString("utf8").includes('"score":0.5'), "未归一化时 0.5 以 number 形态出现");
  assert.ok(rawFrame.toString("utf8").includes('"ratio":1'), "JS 无 1.0 形态，1.0 → 1 属天然行为");
});

test("K-8 编码器本体不做数值处理（归一化点唯一）", () => {
  // 契约 numeric_format.applied_where：归一化发生在「交给编码器之前」，编码器不改数值。
  const payload = { score: 0.5 };
  const frame = encodeDataFrame(1, "agent.completed", payload).toString("utf8");
  assert.ok(
    frame.includes('"score":0.5'),
    "编码器若擅自归一化，这一条就会变成 \"0.500000\" ⇒ 出现两个归一化点",
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// K-9 · 追加通道不改 19 项
// ─────────────────────────────────────────────────────────────────────────────

test("K-9 contracts/sse/channels.delta.json 不存在（本版不建第 20 通道）", () => {
  assert.equal(
    existsSync(join(SSE_DIR, "channels.delta.json")),
    true,
    "V0.3.1 已登记 delta 契约（T031-01）：恰 2 帧（subagent.started / subagent.finished）；缺失 = 契约未落地",
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// K-9-delta · V0.3.1 追加 2 帧（channels.delta.json）—— 与 19 项基线**叠加不替代**
// ─────────────────────────────────────────────────────────────────────────────

test("K-9-delta delta 恰 2 帧、golden 逐字节与磁盘全等、且不得漏进 19 通道生成白名单", () => {
  const delta = readJson(join(SSE_DIR, "channels.delta.json"));
  assert.equal(delta.channels.length, 2, "delta 恰 2 项（多一帧 = 未登记契约增量，判红）");
  assert.equal(delta.meta.count, 2);
  assert.equal(delta.meta.base_channels_count, 19, "delta 必须声明其基线是 19 项（叠加关系机器可查）");
  assert.equal(
    delta.meta.base_channels_digest_sha256,
    channels.meta.channels_digest_sha256,
    "delta 声明的基线 digest 必须与 channels.json 实际 digest 全等（基线漂移即红）",
  );

  const deltaNames = delta.channels.map((spec) => spec.channel);
  assert.deepEqual(
    [...deltaNames].sort(),
    ["subagent.finished", "subagent.started"],
    "delta 通道名单必须逐字同源（V0.3.1 计划 §1④）",
  );
  // 登记边界：通道名登记 ≠ 下发面注册。生成白名单仍钉死 19 项 ——
  // subagent.* 进 SSE_CHANNELS / event-writer 发帧注册归 T031-05，提前出现 = 越权。
  for (const name of deltaNames) {
    assert.equal(
      SSE_CHANNEL_LIST.includes(name),
      false,
      `${name} 不得在生成白名单里（注册归 T031-05；提前出现会让 payload 校验面悄然扩张）`,
    );
  }

  // delta golden：磁盘字节 sha256 / 长度与契约逐条全等（K-7① 的 delta 面）。
  let checked = 0;
  for (const spec of delta.channels) {
    const bytes = readFileSync(join(SSE_DIR, spec.golden));
    assert.equal(sha256(bytes), spec.golden_sha256, `${spec.channel}: delta golden sha 与契约不一致`);
    assert.equal(bytes.length, spec.frame.bytes, `${spec.channel}: delta golden 字节数与契约不一致`);
    checked += 1;
  }
  assert.equal(checked, 2, "必须逐个校验完 2 帧");
});

test("K-9-delta message.delta.keys 冻结件：键名版与键名:类型版 sha 全等、且反规范形态可复算", () => {
  // 只读冻结契约推导（§8.1(b)(c)：delta 类型继承投影源 content = "str | null"）。
  const spec = channels.channels.find((c) => c.channel === "message.delta");
  const p = spec.payload_fields;
  const types = {
    delta: p.content.type, // projection.rule = "content -> delta"；不得取缺省 str
    message_id: p.message_id.type,
    role: p.role.type,
    run_id: p.run_id.type,
  };
  const keys = Object.keys(types).sort();
  const typed = keys.map((k) => `${k}:${types[k]}`).join("\n") + "\n";
  const names = keys.join("\n") + "\n";

  const expectedTyped = "51a78dc60c5bb33ce5f049b206407db1cd439b336b0c6c97e4619b257e4949c1";
  const expectedNames = "ddf3eaae42f86234e4f67e602ffbba6957b3c696192885cb41a52fbb2983a031";
  assert.equal(sha256(Buffer.from(typed, "utf8")), expectedTyped, "键名:类型版 sha 漂移 ⇒ payload 类型面被改");
  assert.equal(sha256(Buffer.from(names, "utf8")), expectedNames, "键名版 sha 漂移 ⇒ payload 键集合被改");

  // 反规范形态（delta 误取 str）必须仍可复算出登记的实值 —— 钉死"这是错的那个值"。
  const wrong = keys.map((k) => `${k}:${k === "delta" ? "str" : types[k]}`).join("\n") + "\n";
  assert.equal(
    sha256(Buffer.from(wrong, "utf8")),
    "b7917f8b27aebb038e503cfc77333a1d4ac51edb63a7e5a90707b1c42c1ea355",
    "反规范参考值对不上 ⇒ 推导规范说明与实值脱钩，须回到 §8.1(c) 重定",
  );

  // 冻结件本体：keys.txt 字节与推导逐字全等，manifest（.sha256）里登记的正是它的哈希。
  const keysBytes = readFileSync(join(GOLDEN_DIR, "message.delta.keys.txt"));
  assert.equal(
    keysBytes.toString("utf8"),
    typed,
    "message.delta.keys.txt 内容与契约推导不一致 —— 冻结件被手改",
  );
  const manifestLines = readFileSync(join(ROOT, "contracts", "sse", "golden", "message.delta.keys.sha256"), "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "" && !line.trim().startsWith("#"));
  assert.equal(manifestLines.length, 1, "keys.sha256 只许一条校验行（其余必须是 # 注释）");
  const [hash, target] = manifestLines[0].trim().split(/\s+/);
  assert.equal(hash, expectedTyped, "keys.sha256 登记值与契约推导不一致");
  assert.equal(
    sha256(readFileSync(join(ROOT, target))),
    hash,
    `keys.sha256 校验行指向的 ${target} 与登记哈希不一致（即 sha256sum -c 必红的形态）`,
  );

  // 两条派生摘要 = **同一个 keys.txt** 的派生（裁定 2026-10-23 条件③，防两文件各自漂移）：
  // typed = keys.txt 文件字节本体；names = 逐行剥离 ":类型" 后取 sha。
  assert.equal(sha256(keysBytes), expectedTyped, "keys.txt 文件字节 sha ≠ 键:类型版参考值（防篡改锚失配）");
  const namesFromFile =
    keysBytes
      .toString("utf8")
      .split("\n")
      .filter((line) => line !== "")
      .map((line) => line.slice(0, line.indexOf(":")))
      .join("\n") + "\n";
  assert.equal(
    sha256(Buffer.from(namesFromFile, "utf8")),
    expectedNames,
    "从 keys.txt 剥离类型推导的键名版 sha ≠ 参考值 —— 两派生摘要不再同源",
  );
});

test("K-9-e0 · 模板组装 == encodeDataFrame：19/19 既有通道逐字节等价（E-0 常驻 gate）", () => {
  // 裁定 2026-10-23：模板组装是 delta golden（subagent.* 未进生成白名单）的唯一导出路径，
  // 其可信度 = 本断言 —— 生成器或编码器任何一侧被改动，这里必须仍 19/19 全等；
  // 失配 ⇒ delta golden 的导出路径失效，须回到导出探针重出（D:/Temp/WBTimeAI/2026-10-23-V031-spike/export-delta-golden.mjs）。
  let checked = 0;
  for (const spec of channels.channels) {
    const payload = buildEventPayload(spec.channel, spec.constructor.kwargs ?? {});
    const expected = encodeDataFrame(spec.frame.seq, spec.channel, payload);
    const text = DATA_FRAME_TEMPLATE
      .replaceAll("{seq}", String(spec.frame.seq))
      .replaceAll("{channel}", spec.channel)
      .replaceAll("{json}", JSON.stringify(projectPayload(spec.channel, payload)));
    assert.ok(
      Buffer.from(text, "utf8").equals(expected),
      `${spec.channel}: 模板组装与 encodeDataFrame 逐字节不等价 —— E-0 失效`,
    );
    checked += 1;
  }
  assert.equal(checked, 19, "必须逐个校验完 19 条");
});

test("K-9 通道数 19、digest 与生成物同源、19 项 sha 与 manifest 全等", () => {
  assert.equal(channels.channels.length, 19);
  assert.equal(channels.meta.count, 19);
  assert.equal(channels.meta.core_count + channels.meta.phase2_count, 19);

  const digest = channels.meta.channels_digest_sha256;
  assert.match(digest, /^[0-9a-f]{64}$/);
  assert.equal(digest.startsWith("9edda3ba"), true, "契约登记的冻结前缀必须是 9edda3ba");

  // 生成物头注里也写着同一个 digest ⇒ 契约与 TS 生成面同源（不是两份各自维护的值）。
  const generatedText = readFileSync(join(ROOT, "packages/event/src/generated/channels.generated.ts"), "utf8");
  const generatedDigest = /channels_digest_sha256:\s*([0-9a-f]{64})/.exec(generatedText);
  assert.ok(generatedDigest !== null, "生成物头注必须带 channels_digest_sha256");
  assert.equal(generatedDigest[1], digest, "生成物 digest 与契约必须全等");

  // 19 项 sha 与 contracts/manifest.sha256 全等（manifest 是冻结面的逐文件清单）
  const manifest = new Map(
    readFileSync(join(ROOT, "contracts", "manifest.sha256"), "utf8")
      .split("\n")
      .filter((line) => line.trim() !== "")
      .map((line) => {
        const [hash, path] = line.trim().split(/\s+/);
        return [path, hash];
      }),
  );
  let checked = 0;
  for (const spec of channels.channels) {
    const key = spec.golden; // 契约里已经是相对 contracts/sse 的路径，manifest 里是相对 contracts/
    const manifestHash = manifest.get(`sse/${key}`);
    assert.ok(manifestHash !== undefined, `manifest.sha256 缺条目: sse/${key}`);
    assert.equal(manifestHash, spec.golden_sha256, `${spec.channel}: manifest 与契约 sha 不一致`);
    checked += 1;
  }
  assert.equal(checked, 19, "必须逐个校验完 19 条");
  assert.equal(manifest.get(`sse/${channels.guard.file}`), channels.guard.sha256, "guard 帧也必须在 manifest 里且一致");
});

// ─────────────────────────────────────────────────────────────────────────────
// K-10 · 心跳帧
// ─────────────────────────────────────────────────────────────────────────────

test("K-10 encodeHeartbeat 字节 == \": hb 1700000000000\\n\\n\"，且不带 id:", () => {
  const heartbeat = channels.frame_format.heartbeat;
  // 同上：契约模板是转义形态，实际帧行尾是真 LF。
  assert.equal(HEARTBEAT_TEMPLATE, heartbeat.template.replaceAll("\\n", "\n"));
  assert.equal(heartbeat.carries_id, false, "心跳不得携带 id:（会污染 Last-Event-ID）");

  const frame = encodeHeartbeat(heartbeat.sample_now_ms);
  assert.equal(frame.toString("utf8"), ": hb 1700000000000\n\n");
  // 契约同时给了真实样本串与 sha256 —— 三者互证，任何一处漂移都会红。
  assert.equal(frame.equals(Buffer.from(heartbeat.sample, "utf8")), true);
  assert.equal(sha256(frame), heartbeat.sha256, "心跳帧 sha256 必须等于契约值");
  assert.equal(frame.toString("utf8").includes("id:"), false, "心跳帧出现 id: ⇒ 污染 Last-Event-ID");
  assert.equal(frame.toString("utf8").includes("\r"), false);
});

test("K-10 心跳间隔只读契约 15.0，代码里不留第二份", () => {
  assert.equal(channels.frame_format.heartbeat.default_interval_seconds, 15);
  assert.equal(channels.frame_format.heartbeat.only_when_idle, true);

  // 本版不实现发送调度（归 V0.3.0），因此生产代码里**不应**存在间隔常量 ——
  // 否则就是「契约一份、代码一份」的第二真相源。
  const encoderSource = readFileSync(join(ROOT, "packages/event/src/encoder.ts"), "utf8");
  assert.equal(
    /(?:heartbeat|Heartbeat)[A-Za-z]*Interval|INTERVAL_SECONDS/.test(encoderSource),
    false,
    "encoder.ts 不得复制心跳间隔常量（间隔属契约 + 运行面）",
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// K-5 复跑 · 30 码 / 13 类（本包视角再钉一次）
// ─────────────────────────────────────────────────────────────────────────────

test("K-5 复跑：契约 30 码 / 13 类与 TS ERROR_HTTP_STATUS 逐码相等", () => {
  const contractCodes = Object.keys(errorsContract.codes);
  assert.equal(contractCodes.length, 30);
  assert.equal(new Set(contractCodes.map((code) => errorsContract.codes[code].http_status)).size, 13);

  assert.equal(Object.keys(ERROR_HTTP_STATUS).length, 30);
  assert.equal(new Set(Object.values(ERROR_HTTP_STATUS)).size, 13);
  assert.deepEqual([...Object.keys(ERROR_HTTP_STATUS)].sort(), [...contractCodes].sort());
  for (const code of contractCodes) {
    assert.equal(ERROR_HTTP_STATUS[code], errorsContract.codes[code].http_status, `码 ${code} 不一致`);
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 投影表与契约全等（生成物缺口的兜底，见 encoder.ts 的 D 注释）
// ─────────────────────────────────────────────────────────────────────────────

test("投影表与契约 projection 全等（含「契约无投影的通道，表里也必须没有」）", () => {
  const withProjection = channels.channels.filter((spec) => spec.projection !== null && spec.projection !== undefined);

  assert.deepEqual(
    Object.keys(PAYLOAD_PROJECTIONS).sort(),
    withProjection.map((spec) => spec.channel).sort(),
    "投影表的通道集合必须与契约「有投影的通道」全等",
  );

  for (const spec of withProjection) {
    const ours = PAYLOAD_PROJECTIONS[spec.channel];
    const [from, to] = spec.projection.rule.split("->").map((part) => part.trim());

    assert.equal(spec.projection.rule, "content -> delta", "契约投影规则变了，本测试与实现都要重看");
    assert.deepEqual(Object.keys(ours.renames), [from], `${spec.channel}: renames 的源键不符`);
    assert.equal(ours.renames[from], to, `${spec.channel}: renames 的目标键不符`);
    assert.deepEqual([...ours.added].sort(), [...spec.projection.added].sort());
    assert.deepEqual([...ours.dropped].sort(), [...spec.projection.dropped].sort());
    // added 必须全部可由 dropped 改名得到，否则投影需要额外的取值来源（当前契约无此情形）
    assert.deepEqual(
      [...new Set(Object.values(ours.renames))].sort(),
      [...spec.projection.added].sort(),
      `${spec.channel}: added 里有无法由 renames 提供的键`,
    );
  }
});

test("19 条通道的线上键序都等于契约 projected_fields（投影 + 保序的合成检验）", () => {
  for (const spec of channels.channels) {
    const projected = projectPayload(spec.channel, payloadOf(spec));
    assert.deepEqual(
      Object.keys(projected),
      spec.projected_fields,
      `${spec.channel}: 线上键序必须等于契约 projected_fields`,
    );
  }
});

test("投影幂等：重复施加不改变结果", () => {
  const spec = channels.channels.find((item) => item.channel === "message.delta");
  const once = projectPayload(spec.channel, payloadOf(spec));
  const twice = projectPayload(spec.channel, once);
  assert.deepEqual(twice, once);
  assert.deepEqual(Object.keys(twice), spec.projected_fields);
});

// ─────────────────────────────────────────────────────────────────────────────
// 编码器入参守卫（帧一旦坏掉，downstream 无法恢复）
// ─────────────────────────────────────────────────────────────────────────────

test("encodeDataFrame 守卫：seq 必须是非负整数", () => {
  const spec = channels.channels[0];
  for (const bad of [-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.throws(() => encodeDataFrame(bad, spec.channel, payloadOf(spec)), RangeError, `seq=${String(bad)} 应被拒`);
  }
});

test("encodeDataFrame 守卫：未知通道 / 非对象 payload", () => {
  const spec = channels.channels[0];
  assert.throws(
    () => encodeDataFrame(1, "agent.unknown", {}),
    UnknownChannelError,
    "未知通道必须抛 UnknownChannelError（与 buildEventPayload 同一错误类）",
  );
  for (const bad of [null, [], "str", 42]) {
    assert.throws(() => encodeDataFrame(1, spec.channel, bad), EventPayloadError, `payload=${String(bad)} 应被拒`);
  }
});

test("encodeHeartbeat 守卫：now_ms 必须是非负整数", () => {
  for (const bad of [-1, 1.5, Number.NaN]) {
    assert.throws(() => encodeHeartbeat(bad), RangeError, `now_ms=${String(bad)} 应被拒`);
  }
});

test("SSE_CHANNEL_LIST 与契约通道顺序全等（编码器接受的通道面 === 冻结面）", () => {
  assert.deepEqual([...SSE_CHANNEL_LIST], channels.channels.map((spec) => spec.channel));
});
