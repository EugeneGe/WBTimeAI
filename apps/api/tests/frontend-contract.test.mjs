// T2-09 · 前端契约面只读断言（K-11 / ⑤-a）
//
// 判据语义（`02-响应壳与SSE.md` §6 + §7 K-11）：
//
//   「从 `apps/web/src/lib/api.ts` 抽出的键集合 **⊆ `ENVELOPE_FIELD_NAMES`**；
//    并断言其判定形态是**键判定**（`"code" in value`）而非值判定。」
//
// 🔴 本文件的目的**不是**让前端「通过」，而是把「前端比契约弱」这件事**测出来**：
//    前端是 3 键键判定、`request_id?` 可选且不校验；契约是 4 键恒在、`already_shell`
//    是值判定。这些差异**只登记、不修正** —— 前端受 `gate:fdiff` 逐字节冻结
//    （243 文件 `git hash-object` + raw digest 双判），改一行即红。
//
// 反「哑真」措施：源文本抽不到函数体 / 抽不到键 ⇒ **立刻红**，绝不产生
// 「空集 ⊆ 任意集 ⇒ PASS」这种假绿。这也是本仓 §7 判据表反复强调的 empty-set floor。

import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import assert from "node:assert/strict";
import { test } from "node:test";

import { ENVELOPE_FIELD_NAMES } from "@wbtime/core";

/** 仓库根（apps/api/tests → apps/api → apps → 根）。 */
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const WEB_API_PATH = join(ROOT, "apps", "web", "src", "lib", "api.ts");
const WEB_SRC_PATH = join(ROOT, "apps", "web", "src");

const envelopeContract = JSON.parse(
  readFileSync(join(ROOT, "contracts", "envelope.schema.json"), "utf8"),
);

/**
 * 从源文本里抠出一个具名函数的函数体（花括号配对，不是贪婪正则）。
 *
 * 为什么不用 `/\{[\s\S]*?\}/`：函数体里本来就有嵌套花括号（对象字面量、模板串），
 * 非贪婪正则会停在第一个内层 `}`，于是「抽出 3 个键」变成「抽出 1 个键」而测试
 * 依然绿 —— 这正是本仓反复出现的「门禁只看了一半文件还报 PASS」失效模式。
 *
 * @param source 源文本。
 * @param functionName 函数名（`export function foo(` 或 `function foo(`）。
 * @returns 函数体文本（不含最外层花括号）。
 */
function extractFunctionBody(source, functionName) {
  const anchor = new RegExp(
    `(?:export\\s+)?function\\s+${functionName}\\s*(?:<[^>]*>)?\\s*\\([^)]*\\)[^{]*\\{`,
  );
  const match = anchor.exec(source);
  assert.ok(match !== null, `源文本里找不到函数 ${functionName}（前端契约面可能已改名）`);

  const start = match.index + match[0].length;
  let depth = 1;
  let index = start;
  while (index < source.length && depth > 0) {
    const char = source[index];
    if (char === "{") depth += 1;
    else if (char === "}") depth -= 1;
    index += 1;
  }
  assert.equal(depth, 0, `函数 ${functionName} 的花括号未配对（源文本被截断？）`);
  const body = source.slice(start, index - 1);
  assert.ok(body.trim().length > 0, `函数 ${functionName} 的函数体是空的`);
  return body;
}

/** 抽出函数体里 `"<key>" in <expr>` 形态的键字面量集合。 */
function extractInOperatorKeys(body) {
  const keys = new Set();
  const pattern = /(["'`])([A-Za-z_$][\w$]*)\1\s+in\s+/g;
  let match = pattern.exec(body);
  while (match !== null) {
    keys.add(match[2]);
    match = pattern.exec(body);
  }
  return keys;
}

test("K-11 前置：前端契约面源文件存在且非空（防「文件没了 ⇒ 空集 ⊆ 任意集」）", () => {
  assert.equal(existsSync(WEB_API_PATH), true, `缺少前端契约面文件: ${WEB_API_PATH}`);

  const source = readFileSync(WEB_API_PATH, "utf8");
  const lineCount = source.split("\n").length;
  assert.ok(lineCount > 0, "前端契约面源文本不得为空");
  assert.ok(
    source.includes("isResponseShell"),
    "源文本必须含 isResponseShell（K-11 的抽取锚点）",
  );

  // 契约侧 floor：4 键且含 request_id —— 否则下面的 ⊆ 断言会变成「3 ⊆ 3」的哑真。
  assert.equal(ENVELOPE_FIELD_NAMES.length, 4);
  assert.ok(ENVELOPE_FIELD_NAMES.includes("request_id"));
});

test("K-11 键集合 ⊆ ENVELOPE_FIELD_NAMES（成员级，且实测为 3 键不是 4 键）", () => {
  const source = readFileSync(WEB_API_PATH, "utf8");
  const body = extractFunctionBody(source, "isResponseShell");
  const keys = extractInOperatorKeys(body);

  // 空集必须 INVALID：抽不到键说明抽取逻辑或源文本结构变了，不能当「弱但合规」放过。
  assert.ok(keys.size > 0, "未能从 isResponseShell 抽出任何键字面量（抽取失效，不是 PASS）");

  for (const key of keys) {
    assert.ok(
      ENVELOPE_FIELD_NAMES.includes(key),
      `前端认的键 ${key} 不在契约四顶层键内（前端认了契约没有的键 ⇒ 解壳会解错）`,
    );
  }

  // 实测事实：前端只认 3 键，**缺 request_id**。这条断言把「比契约弱」钉成可测事实，
  // 而不是写在文档里靠人记。前端解冻版本补齐后，这里会红 —— 那时应同步更新
  // `03-台账/风险与决策.md` 与本文件，而不是悄悄放宽。
  assert.deepEqual(
    [...keys].sort(),
    ["code", "data", "message"],
    "前端键集合实测定为 {code,message,data}；若已变化，请同步登记差异变更",
  );
  assert.equal(keys.has("request_id"), false, "前端不校验 request_id（已登记的差异 ①）");
});

test("K-11 判定形态是**键判定**（不是契约要求的**值判定**）", () => {
  const source = readFileSync(WEB_API_PATH, "utf8");
  const body = extractFunctionBody(source, "isResponseShell");

  // 键判定：`"code" in value` 形态必须存在（这就是与契约 already_shell 的分歧点）
  assert.ok(/"code"\s+in\s+value/.test(body), '缺少 "code" in value 形态');
  assert.ok(/"message"\s+in\s+value/.test(body));

  // 值判定：契约 already_shell 要求 code === 0 && message === "ok" && hasOwn(data) && hasOwn(request_id)。
  // 前端**没有**这些值比较 —— 必须断言「没有」，否则等于假装前端已对齐。
  assert.equal(/\.code\s*===\s*0/.test(body), false, "前端出现值判定 code===0 ⇒ 差异已消除，须更新登记");
  assert.equal(/\.message\s*===\s*["']ok["']/.test(body), false, "前端出现值判定 message===\"ok\" ⇒ 差异已消除，须更新登记");
});

test("K-11 已登记差异 ①②：request_id 可选不校验 / 前端是键判定", () => {
  const source = readFileSync(WEB_API_PATH, "utf8");

  // 差异 ①：前端 ResponseShell.request_id 是**可选**且无校验；契约要求键恒在。
  assert.ok(
    /request_id\?\s*:/.test(source),
    "前端 ResponseShell.request_id 不再是可选 ⇒ 差异 ①已变化，须更新台账",
  );
  assert.equal(
    envelopeContract["x-wbtimeai"].enforcement.field_invariance.request_id.key_always_present,
    true,
    "契约侧 request_id 键恒在 —— 与前端可选形成已登记差异",
  );

  // 差异 ②：契约的 already_shell 是值判定（见契约原文），前端是键判定（上一条测试已断言）。
  assert.equal(
    envelopeContract["x-wbtimeai"].not_wrapped.cases.find((item) => item.case === "already_shell")
      .condition,
    'code == 0 且 message == "ok" 且含 data 与 request_id',
  );
});

test("K-11 前端零改动：apps/web/src 逐文件 sha256 与登记快照全等（V0.2.0 审计 #29：去 git 工作树依赖）", () => {
  // 与 gate:fdiff 的重叠说明：`gate:fdiff` 做 243 文件逐字节 + raw digest 双判（权威）；
  // 这里只做一个「本任务期间没动过前端」的轻量旁证 —— 两者都在，互不替代。
  //
  // **#29 订正**：原实现用 `git diff --stat` / `git status --porcelain` 判零改动 ——
  // 那依赖 git 工作树状态（N-8 实测：无 `.git` 的工作树里直接抛错，测试变成环境红）。
  // 现改用**前端文件 sha 快照**：登记 243 个文件（`fixtures/web-src-sha256.json`，
  // 生成方式见该文件与下方），无 `.git` 也能跑；前端任一文件被改 / 增 / 删 ⇒ 红。
  //
  // 快照再生成（刻意的手工摩擦：改前端必须显式刷新快照并登记，不允许悄悄带过）：
  //   node -e "<见 02-施工/施工记录/T3-15.md §#29>"
  const snapshot = JSON.parse(
    readFileSync(join(ROOT, "apps", "api", "tests", "fixtures", "web-src-sha256.json"), "utf8"),
  );
  assert.equal(snapshot.algorithm, "sha256");
  assert.equal(snapshot.root, "apps/web/src");
  assert.ok(
    snapshot.fileCount >= 1 && Object.keys(snapshot.files).length === snapshot.fileCount,
    "快照登记表必须非空且与 fileCount 一致（空快照 = 空集 ⊆ 任意集 的哑真）",
  );

  const actual = new Map();
  const walk = (dir) => {
    for (const name of readdirSync(dir).sort()) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else actual.set(relative(snapshot.root, full).split("\\").join("/"), full);
    }
  };
  walk(WEB_SRC_PATH);

  // ① 不得删文件：快照里有、工作树没有 ⇒ 红。
  for (const rel of Object.keys(snapshot.files)) {
    assert.ok(
      actual.has(rel),
      `apps/web/src/${rel} 在快照里登记了但工作树已删除（K-11 红线：前端零改动）`,
    );
  }
  // ② 不得加文件 / 改文件：工作树的每一份内容 sha 必须与快照逐字节等价。
  for (const [rel, full] of actual) {
    const expected = snapshot.files[rel];
    assert.ok(
      expected !== undefined,
      `apps/web/src/${rel} 是快照外的**新增**文件（K-11 红线：前端零改动；若为登记过的合法变更，须刷新快照并登记差异变更）`,
    );
    const digest = createHash("sha256").update(readFileSync(full)).digest("hex");
    assert.equal(
      digest,
      expected,
      `apps/web/src/${rel} 内容与快照不符（K-11 红线：前端零改动）`,
    );
  }
});
