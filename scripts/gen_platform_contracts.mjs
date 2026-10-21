// T1-02 · 平台基座的契约派生代码生成器（Node 标准库 only，零依赖）。
//
// 为什么必须有这个脚本
// --------------------
// 平台的三份「与契约全等」判据（错误码 / 响应壳字段 / SSE 通道）在 TS 侧不能手抄：
// 手抄 = 契约一改就静默漂移，而门禁 `check_platform_parity.py` 只在事后比对，
// 修一次漂移要改两处。所以这里让 `contracts/` 成为**唯一 oracle**，
// 由本脚本把 JSON 直接翻译成 TS 源文本，生成的 *.generated.ts 一律标注
// `@generated` 并禁止手改（`--check` 模式下若内容不一致即退出非 0）。
//
// 用法::
//
//     node scripts/gen_platform_contracts.mjs            # 写入生成物并打印摘要
//     node scripts/gen_platform_contracts.mjs --check    # 只比对，不写盘
//
// Python: 本脚本是 Node 脚本，因为消费方是 TS；比对门禁另见
// scripts/check_platform_parity.py（Python 标准库 only）。

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const CHECK_ONLY = process.argv.includes("--check");

/** 读取 contracts/ 下的 JSON（相对 contracts/ 的路径）。 */
function contract(relPath) {
  return JSON.parse(readFileSync(join(ROOT, "contracts", relPath), "utf8"));
}

/** TS 字符串字面量：JSON 的字符串转义规则与 TS 双引号字面量兼容。 */
const q = (s) => JSON.stringify(s);

// ─────────────────────────────────────────────────────────────────────────────
// 1. contracts/errors.json → packages/core/src/generated/errors.generated.ts
// ─────────────────────────────────────────────────────────────────────────────

function genErrors() {
  const doc = contract("errors.json");
  const codes = doc.codes;
  const names = Object.keys(codes).sort();
  if (names.length === 0) {
    throw new Error("contracts/errors.json: codes 为空 —— 空集合必须红，不得生成");
  }

  const rows = names.map((name) => {
    const e = codes[name];
    if (e.code !== name) {
      throw new Error(`errors.json: 键 ${name} 与 code 字段 ${e.code} 不一致`);
    }
    const status = e.http_status;
    if (!Number.isInteger(status)) {
      throw new Error(`errors.json: ${name} 缺少整数 http_status（实测 ${status}）`);
    }
    return { name, status, description: e.description ?? "" };
  });

  const constRows = rows
    .map((r) => `  ${r.name}: ${q(r.name)},`)
    .join("\n");
  const statusRows = rows
    .map((r) => `  ${r.name}: ${r.status}, // ${r.description}`)
    .join("\n");
  const descRows = rows
    .map((r) => `  ${r.name}: ${q(r.description)},`)
    .join("\n");
  const listRows = rows.map((r) => `  ${q(r.name)},`).join("\n");

  const digest = doc.meta?.codes_digest_sha256 ?? "unknown";
  const version = doc.contract_version ?? "unknown";

  return `// @generated —— 由 scripts/gen_platform_contracts.mjs 从 contracts/errors.json 生成。
// 请勿手改：改契约后重跑 \`node scripts/gen_platform_contracts.mjs\`。
//
// contract_version: ${version}
// codes_digest_sha256: ${digest}
// 错误码数量（实测，以读取为准）: ${rows.length}
// HTTP 状态来源: 逐码取 codes[*].http_status（字段在契约内，非推导、非编造）。

/** 全部错误码字面量集合（键 == 值，便于 \`ErrorCode.X\` 与字面量双向对齐）。 */
export const ERROR_CODES = {
${constRows}
} as const;

/** 错误码联合类型：与 \`ERROR_CODES\` 同源，新增/删码即刻类型级可见。 */
export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

/** 错误码 → HTTP 状态码映射（来源：contracts/errors.json → codes[*].http_status）。 */
export const ERROR_HTTP_STATUS: Readonly<Record<ErrorCode, number>> = {
${statusRows}
};

/** 错误码 → 中文描述（来源：contracts/errors.json → codes[*].description）。 */
export const ERROR_DESCRIPTIONS: Readonly<Record<ErrorCode, string>> = {
${descRows}
};

/** 稳定顺序（字典序）的错误码清单，供门禁逐项比对。 */
export const ERROR_CODE_LIST: readonly ErrorCode[] = [
${listRows}
];

/** 未登记的错误码一律回落到 UNKNOWN，并取 500。 */
export const UNKNOWN_ERROR_CODE: ErrorCode = "UNKNOWN";

/** 取 HTTP 状态码：未知码回落 UNKNOWN 的状态码（不静默给 500 字面量）。 */
export function httpStatusFor(code: string): number {
  return ERROR_HTTP_STATUS[code as ErrorCode] ?? ERROR_HTTP_STATUS[UNKNOWN_ERROR_CODE];
}
`;
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. contracts/envelope.schema.json → packages/core/src/generated/envelope.generated.ts
//    字段集合 + typebox schema 都由 \$defs 的 properties/required 翻译而来。
// ─────────────────────────────────────────────────────────────────────────────

function resolveRef(ref, defs) {
  const prefix = "#/$defs/";
  if (!ref.startsWith(prefix)) throw new Error(`不支持的 \$ref: ${ref}`);
  let cur = defs;
  for (const seg of ref.slice(prefix.length).split("/")) {
    if (cur == null) throw new Error(`\$ref 解析失败: ${ref}`);
    cur = cur[seg];
  }
  if (cur == null) throw new Error(`\$ref 解析失败: ${ref}`);
  return cur;
}

function primType(t) {
  switch (t) {
    case "string":
      return "Type.String()";
    case "integer":
      return "Type.Integer()";
    case "number":
      return "Type.Number()";
    case "boolean":
      return "Type.Boolean()";
    case "null":
      return "Type.Null()";
    default:
      throw new Error(`不支持的 JSON Schema 类型: ${t}`);
  }
}

/** JSON Schema 节点 → typebox 表达式源码（递归）。 */
function emitSchema(node, defs, indent) {
  if (typeof node !== "object" || node === null) throw new Error("schema 节点不是对象");
  if (typeof node.$ref === "string") return emitSchema(resolveRef(node.$ref, defs), defs, indent);
  if (Object.prototype.hasOwnProperty.call(node, "const")) {
    return `Type.Literal(${JSON.stringify(node.const)})`;
  }
  if (Array.isArray(node.enum)) {
    const members = node.enum.map((v) => `Type.Literal(${JSON.stringify(v)})`).join(", ");
    return `Type.Union([${members}])`;
  }
  if (Array.isArray(node.anyOf)) {
    return `Type.Union([${node.anyOf.map((n) => emitSchema(n, defs, indent)).join(", ")}])`;
  }
  if (Array.isArray(node.type)) {
    return `Type.Union([${node.type.map((t) => primType(t)).join(", ")}])`;
  }
  if (node.type === "array") {
    const item = node.items ? emitSchema(node.items, defs, indent) : "Type.Unknown()";
    return `Type.Array(${item})`;
  }
  if (node.type === "object") {
    const props = node.properties ?? {};
    const keys = Object.keys(props);
    if (keys.length === 0) {
      // 无声明属性的对象：additionalProperties 为 true 时是自由字典，否则是「任意对象」。
      return node.additionalProperties === true
        ? "Type.Record(Type.String(), Type.Unknown())"
        : "Type.Object({})";
    }
    const inner = keys
      .map(
        (k) =>
          `${indent}  ${JSON.stringify(k)}: ${emitSchema(props[k], defs, `${indent}  `)},`,
      )
      .join("\n");
    const extra =
      node.additionalProperties === false
        ? `,\n${indent}  {\n${indent}    additionalProperties: false\n${indent}  }`
        : "";
    return `Type.Object({\n${inner}\n${indent}}${extra})`;
  }
  if (typeof node.type === "string") return primType(node.type);
  return "Type.Unknown()";
}

function genEnvelope() {
  const doc = contract("envelope.schema.json");
  const defs = doc.$defs ?? {};
  const okDef = defs.successEnvelope;
  const errDef = defs.errorEnvelope;
  if (!okDef || !errDef) throw new Error("envelope.schema.json: 缺少 successEnvelope / errorEnvelope");

  const okFields = okDef.required ?? [];
  const errFields = errDef.required ?? [];
  if (okFields.length === 0 || errFields.length === 0) {
    throw new Error("envelope.schema.json: required 为空 —— 空集合必须红，不得生成");
  }
  // 契约断言：两种壳的顶层字段集合必须全等（总纲 §11.1「四顶层键恒在」）。
  const setEq = okFields.length === errFields.length && okFields.every((f) => errFields.includes(f));
  if (!setEq) {
    throw new Error(
      `envelope.schema.json: 成功壳字段 [${okFields}] 与失败壳字段 [${errFields}] 不全等，需裁定`,
    );
  }
  // 与 properties 键集合交叉校验（required ⊆ properties 且此处要求相等）。
  const okProps = Object.keys(okDef.properties ?? {});
  const errProps = Object.keys(errDef.properties ?? {});
  for (const [label, req, props] of [
    ["successEnvelope", okFields, okProps],
    ["errorEnvelope", errFields, errProps],
  ]) {
    if (req.length !== props.length || !req.every((f) => props.includes(f))) {
      throw new Error(`envelope.schema.json: ${label} 的 required 与 properties 键集合不等`);
    }
  }

  const fieldRows = okFields.map((f) => `  ${q(f)},`).join("\n");

  return `// @generated —— 由 scripts/gen_platform_contracts.mjs 从 contracts/envelope.schema.json 生成。
// 请勿手改。
//
// \$id: ${doc.$id ?? "unknown"}
// 响应壳顶层字段（实测，成功壳 required == 失败壳 required == properties 键集）: ${okFields.length}
// 字段清单: ${okFields.join(", ")}

import { Type } from "@sinclair/typebox";

/** 响应壳的四顶层键：成功壳与失败壳同构（总纲 §11.1「四顶层键恒在」）。 */
export const ENVELOPE_FIELD_NAMES = [
${fieldRows}
] as const;

export type EnvelopeFieldName = (typeof ENVELOPE_FIELD_NAMES)[number];

/** 成功壳（code 恒为整数 0，message 恒为 "ok"）。 */
export const OkEnvelopeSchema = ${emitSchema(okDef, defs, "")};

/** 失败壳（code 为 ErrorCode 字符串字面量，与成功壳的 0 **不同型**）。 */
export const ErrorEnvelopeSchema = ${emitSchema(errDef, defs, "")};
`;
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. contracts/sse/channels.json → packages/event/src/generated/channels.generated.ts
// ─────────────────────────────────────────────────────────────────────────────

/** 从 numeric_format.rules 里解析「定点小数位数」（不硬编码 6，从契约读）。 */
function parseFixedDecimals(numericFormat) {
  const rules = numericFormat?.rules ?? [];
  const rule = rules.find((r) => typeof r.example === "string" && typeof r.output === "string" && r.output.includes("定点十进制"));
  if (!rule) throw new Error("channels.json: 找不到定点十进制规则，无法解析小数位数");
  const m = /->\s*"([^"]+)"/.exec(rule.example);
  if (!m) throw new Error(`channels.json: 定点规则 example 无法解析: ${rule.example}`);
  const frac = m[1].split(".")[1];
  if (!frac) throw new Error(`channels.json: 定点规则 example 无小数部分: ${rule.example}`);
  return frac.length;
}

function genChannels() {
  const doc = contract("sse/channels.json");
  const list = doc.channels ?? [];
  if (list.length === 0) {
    throw new Error("contracts/sse/channels.json: channels 为空 —— 空集合必须红，不得生成");
  }

  const byChannel = doc.by_channel ?? {};
  const fixedDecimals = parseFixedDecimals(doc.numeric_format);
  const policy = doc.numeric_format?.policy;
  const ruleVersion = doc.numeric_format?.rule_version;
  if (typeof policy !== "string" || !Number.isInteger(ruleVersion)) {
    throw new Error("channels.json: numeric_format.policy / rule_version 缺失");
  }

  // 通道名 → TS 常量名：agent.started → AGENT_STARTED
  const constName = (channel) => channel.toUpperCase().replace(/[^A-Z0-9]+/g, "_");

  const constRows = list
    .map((c) => `  ${constName(c.channel)}: ${q(c.channel)},`)
    .join("\n");
  const listRows = list.map((c) => `  ${q(c.channel)},`).join("\n");

  const specEntries = list
    .map((c) => {
      const keys = (c.payload_keys_in_order ?? []).map((k) => `      ${q(k)},`).join("\n");
      // 必填键：从 payload_fields 里取 required === true 的键，**按契约键序**排列。
      //
      // 为什么必须由生成器算而不是运行期现算：payload_fields 是「字段 → 元信息」的
      // 字典，JS 对象遍历序虽然通常等于插入序，但契约并没有把这一点写进承诺；
      // 键序是 `payload_keys_in_order` 独有的事实，所以这里以它为遍历轴再查
      // payload_fields 的 required 标记 —— 顺序可证，不是撞运气。
      const payloadFields = c.payload_fields ?? {};
      const requiredKeys = (c.payload_keys_in_order ?? []).filter(
        (k) => payloadFields[k]?.required === true,
      );
      // 契约自洽性守卫：required 键必须落在键序里，否则「按键序输出必填键」这条
      // 规则本身失效（会静默丢键）。生成期红，比运行期少一个必填校验要好。
      const strayRequired = Object.keys(payloadFields).filter(
        (k) => payloadFields[k]?.required === true && !(c.payload_keys_in_order ?? []).includes(k),
      );
      if (strayRequired.length > 0) {
        throw new Error(
          `channels.json: ${c.channel} 的必填键 [${strayRequired}] 不在 payload_keys_in_order 中，需裁定`,
        );
      }
      const requiredRows =
        requiredKeys.length === 0
          ? ""
          : `\n${requiredKeys.map((k) => `      ${q(k)},`).join("\n")}\n    `;
      const domainType = byChannel[c.channel] ?? c.domain_type ?? c.channel;
      const eventClass = c.event_class ?? "";
      const phase = c.phase ?? "unknown";
      return [
        `  ${q(c.channel)}: {`,
        `    channel: ${q(c.channel)},`,
        `    eventClass: ${q(eventClass)},`,
        `    domainType: ${q(domainType)},`,
        `    phase: ${q(phase)},`,
        `    payloadKeysInOrder: [`,
        keys,
        `    ],`,
        `    requiredPayloadKeys: [${requiredRows}],`,
        `  },`,
      ].join("\n");
    })
    .join("\n");

  const digest = doc.meta?.channels_digest_sha256 ?? "unknown";

  return `// @generated —— 由 scripts/gen_platform_contracts.mjs 从 contracts/sse/channels.json 生成。
// 请勿手改。
//
// contract_version: ${doc.contract_version ?? "unknown"}
// channels_digest_sha256: ${digest}
// 通道数量（实测，以读取为准）: ${list.length}
// payload 键序 = payload_keys_in_order：TS 侧必须保序（契约键序 == 插入序）。

/** 全部 SSE 通道（19 条正式通道；浮点归一化 guard 帧不在内）。 */
export const SSE_CHANNELS = {
${constRows}
} as const;

export type SseChannel = (typeof SSE_CHANNELS)[keyof typeof SSE_CHANNELS];

/** 稳定顺序（契约 index 升序）的通道清单，供门禁逐项比对。 */
export const SSE_CHANNEL_LIST: readonly SseChannel[] = [
${listRows}
];

/** 单通道规格：payload 键序是契约的一部分（sort_keys=False，字节可比的前提）。 */
export interface SseChannelSpec {
  readonly channel: string;
  readonly eventClass: string;
  readonly domainType: string;
  readonly phase: string;
  readonly payloadKeysInOrder: readonly string[];
  /** 必填键（契约 payload_fields[*].required === true），按 payloadKeysInOrder 顺序。 */
  readonly requiredPayloadKeys: readonly string[];
}

export const SSE_CHANNEL_SPECS: Readonly<Record<string, SseChannelSpec>> = {
${specEntries}
};

/**
 * 数值上线策略（contracts/sse/channels.json → numeric_format）。
 * 目的：Python \`json.dumps(1.0) == '1.0'\` 而 JS \`JSON.stringify(1.0) == '1'\`，
 * 只要整数值浮点能上帧，「golden 帧逐字节相同」就原理上不可达，故定死为
 * 「线上只走整数」，非整数浮点转定点十进制字符串。
 */
export const NUMERIC_FORMAT_POLICY = ${q(policy)};
export const NUMERIC_FORMAT_RULE_VERSION = ${ruleVersion};
/** 定点十进制字符串的小数位数（从契约 example 解析，非硬编码）。 */
export const NUMERIC_FIXED_DECIMALS = ${fixedDecimals};
`;
}

// ─────────────────────────────────────────────────────────────────────────────
// 写盘 / 比对
// ─────────────────────────────────────────────────────────────────────────────

const TARGETS = [
  { file: "packages/core/src/generated/errors.generated.ts", gen: genErrors },
  { file: "packages/core/src/generated/envelope.generated.ts", gen: genEnvelope },
  { file: "packages/event/src/generated/channels.generated.ts", gen: genChannels },
];

let drift = 0;
const summary = [];
for (const t of TARGETS) {
  const abs = join(ROOT, t.file);
  const next = t.gen();
  let prev = null;
  try {
    prev = readFileSync(abs, "utf8");
  } catch {
    prev = null;
  }
  if (prev === next) {
    summary.push(`  UNCHANGED  ${t.file}`);
    continue;
  }
  if (CHECK_ONLY) {
    drift += 1;
    summary.push(`  DRIFT      ${t.file}（--check：未写盘）`);
    continue;
  }
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, next, "utf8");
  summary.push(`  WROTE      ${t.file}${prev === null ? "（新建）" : "（已更新）"}`);
}

const errors = contract("errors.json");
const envelope = contract("envelope.schema.json");
const channels = contract("sse/channels.json");

console.log("gen_platform_contracts: 生成目标与状态");
console.log(summary.join("\n"));
console.log("gen_platform_contracts: 契约实测口径（数据源 = contracts/）");
console.log(`  errors.json            codes = ${Object.keys(errors.codes ?? {}).length}`);
console.log(
  `  envelope.schema.json   字段 = ${(envelope.$defs?.successEnvelope?.required ?? []).length} (${(envelope.$defs?.successEnvelope?.required ?? []).join(",")})`,
);
console.log(`  sse/channels.json      channels = ${(channels.channels ?? []).length}`);

if (CHECK_ONLY && drift > 0) {
  console.error(`gen_platform_contracts: --check 发现 ${drift} 处生成物与契约不一致`);
  process.exit(1);
}
