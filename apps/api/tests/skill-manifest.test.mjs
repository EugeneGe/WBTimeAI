/**
 * T3-06 · `skill.yaml` 清单解析 + 包装载的行为证明（**纯单元**，零 HTTP / 零 DB）。
 *
 * 判据（任务卡验收 ②③ + 反例 R3-21）：
 *   ② 必填键缺失 / 版本非法 / **资源路径越界** ⇒ 422 `VALIDATION_ERROR`（不新增契约错误码）；
 *   ③ 解析**确定性**：同一清单两次解析（含 YAML 键序不同）sha（指纹）全等；
 *   R3-21 反例：清单放行 `../` 资源路径 ⇒ 必红；同输入两次解析结果不同 ⇒ 必红。
 *
 * 语义逐条对 py oracle（`wbtime_ai_skill/manifest.py` / `loader.py`）：
 * 必填 `name`（`^[a-z0-9][a-z0-9._-]{1,63}$`）/ `version`（`MAJOR.MINOR.PATCH`）；
 * `display_name` 缺省回落 `name`；指令文件缺失宽松落空串；资源扫描 examples →
 * resources → scripts，逐层排序。
 */

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, test } from "node:test";

import {
  DEFAULT_INSTRUCTIONS_FILE,
  manifestFingerprint,
  parseManifestYaml,
  versionKey,
  validateRelPath,
} from "../dist/modules/skill/manifest.js";
import { loadSkillPackage } from "../dist/modules/skill/loader.js";

/** 断言一个函数抛 422 `VALIDATION_ERROR`（HttpException 的契约形状）。 */
function assertValidation422(fn) {
  try {
    fn();
  } catch (error) {
    assert.equal(error.statusCode, 422, `期望 422，实测 ${error.statusCode}：${error.message}`);
    assert.equal(error.code, "VALIDATION_ERROR", "复用既有契约错误码，不新增");
    return error;
  }
  assert.fail("期望抛 422 VALIDATION_ERROR，实际没有抛");
}

/** 临时包目录登记（afterEach 统一清理）。 */
const tempDirs = [];

function makeTempDir(prefix) {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop(), { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// A · 必填键 / 词表（验收 ②）
// ---------------------------------------------------------------------------

test("A · 合法最小清单：name + version 即可，其余键全部落缺省（py 冻结字段同口径）", () => {
  const manifest = parseManifestYaml("name: my-skill\nversion: 1.2.3\n");
  assert.equal(manifest.name, "my-skill");
  assert.equal(manifest.version, "1.2.3");
  assert.equal(manifest.display_name, "my-skill", "display_name 缺省回落 name（py `or name`）");
  assert.equal(manifest.description, "");
  assert.equal(manifest.category, "");
  assert.equal(manifest.entry, null, "entry 缺省 null = 纯指令包（py 同口径）");
  assert.equal(manifest.instructions, DEFAULT_INSTRUCTIONS_FILE);
  assert.deepEqual(manifest.dependencies, []);
  assert.deepEqual(manifest.requires, []);
  assert.equal(manifest.license, "");
  assert.equal(manifest.resources, "resources");
  assert.equal(manifest.examples, "examples");
  assert.equal(manifest.scripts, "scripts");
  assert.equal(manifest.min_wbtime_ai_version, "");
});

test("A · name 缺失 / 非法 ⇒ 422（py SKILL_NAME_PATTERN 同词表）", () => {
  for (const yaml of ["version: 1.0.0\n", "name: '', version: 1.0.0\n"]) {
    assertValidation422(() => parseManifestYaml(yaml));
  }
  for (const bad of ["Upper", "has space", "", "a".repeat(65), "-lead", "中文"]) {
    assertValidation422(() => parseManifestYaml(`name: ${JSON.stringify(bad)}\nversion: 1.0.0\n`));
  }
  // 边界合法值不抛：2 字符起、允许 . _ - 数字字母
  parseManifestYaml("name: a1\nversion: 1.0.0\n");
  parseManifestYaml("name: a.b_c-d9\nversion: 1.0.0\n");
});

test("A · version 缺失 / 非语义化 ⇒ 422（严格 MAJOR.MINOR.PATCH，无前缀无后缀）", () => {
  for (const bad of ["1.2", "v1.2.3", "1.2.3.4", "1.2.x", ""]) {
    assertValidation422(() => parseManifestYaml(`name: a1\nversion: ${JSON.stringify(bad)}\n`));
  }
  assertValidation422(() => parseManifestYaml("name: a1\n"));
  // 边界合法值不抛
  parseManifestYaml("name: a1\nversion: 0.0.0\n");
  parseManifestYaml("name: a1\nversion: 10.20.30\n");
});

test("A · 顶层非映射（列表 / 标量）⇒ 422；非法 YAML ⇒ 422（py「解析失败」同文案）", () => {
  assertValidation422(() => parseManifestYaml("- a\n- b\n"));
  assertValidation422(() => parseManifestYaml("42\n"));
  assertValidation422(() => parseManifestYaml("name: [unclosed\n"));
  // 空文档（py `raw or {}`）落到 name 缺失的同一条 422
  assertValidation422(() => parseManifestYaml(""));
});

test("A · dependencies/requires 列表归一化（py _as_str_tuple：falsy 空 / 单串单元素 / 逐项 String）", () => {
  const m = parseManifestYaml(
    "name: a1\nversion: 1.0.0\ndependencies: [tool:filesystem, tool:web]\nrequires: cap:one\n",
  );
  assert.deepEqual(m.dependencies, ["tool:filesystem", "tool:web"]);
  assert.deepEqual(m.requires, ["cap:one"]);
  const none = parseManifestYaml("name: a1\nversion: 1.0.0\ndependencies: []\n");
  assert.deepEqual(none.dependencies, []);
});

test("A · versionKey：可比较三元组；非法回退 (0,0,0)（py version_key 同语义）", () => {
  assert.deepEqual(versionKey("1.2.3"), [1, 2, 3]);
  assert.deepEqual(versionKey("10.0.7"), [10, 0, 7]);
  assert.deepEqual(versionKey("nope"), [0, 0, 0]);
});

// ---------------------------------------------------------------------------
// B · 资源路径越界（验收 ② / R3-21 反例一：放行 `../` 必红）
// ---------------------------------------------------------------------------

test("B · 反例 R3-21：instructions/resources/examples/scripts/entry 带 `..` ⇒ 422 必红", () => {
  for (const [field, value] of [
    ["instructions", "../etc/passwd"],
    ["resources", "../outside"],
    ["examples", "a/../../b"],
    ["scripts", ".."],
    ["entry", "x/../y"],
  ]) {
    const error = assertValidation422(() =>
      parseManifestYaml(`name: a1\nversion: 1.0.0\n${field}: ${JSON.stringify(value)}\n`),
    );
    assert.equal(error.data.field, field, `越界字段要写进 data.field（实测 ${JSON.stringify(error.data)}）`);
  }
});

test("B · 绝对路径 / 盘符 / 反斜杠 / NUL ⇒ 422；`.` 段与尾随 `/` 无害放行", () => {
  for (const [field, value] of [
    ["resources", "/etc"],
    ["resources", "C:/win"],
    ["scripts", "a\\b"],
    ["entry", "a\0b"],
  ]) {
    assertValidation422(() =>
      parseManifestYaml(`name: a1\nversion: 1.0.0\n${field}: ${JSON.stringify(value)}\n`),
    );
  }
  // 无害形态放行（不过度校验）
  parseManifestYaml("name: a1\nversion: 1.0.0\nresources: ./resources\n");
  parseManifestYaml("name: a1\nversion: 1.0.0\nresources: resources/\n");
  // validateRelPath 单独暴露（loader 扫描复用同一出口）
  assertValidation422(() => validateRelPath("p", "../x"));
  assert.equal(validateRelPath("p", "resources/x.txt"), "resources/x.txt");
});

// ---------------------------------------------------------------------------
// C · 确定性（验收 ③ / R3-21 反例二：同输入两次解析结果不同必红）
// ---------------------------------------------------------------------------

test("C · 同一清单两次解析指纹全等；YAML 键序不同指纹仍全等（规范 JSON 键排序）", () => {
  const once = parseManifestYaml(
    "name: a1\nversion: 1.0.0\ndisplay_name: 技能一\ndependencies: [tool:web]\n",
  );
  const twice = parseManifestYaml(
    "name: a1\nversion: 1.0.0\ndisplay_name: 技能一\ndependencies: [tool:web]\n",
  );
  assert.equal(manifestFingerprint(once), manifestFingerprint(twice), "同输入两次 sha 必全等");

  // 键序不同（同内容）⇒ 仍全等 —— 这是 canonicalize 键排序存在的理由
  const reordered = parseManifestYaml(
    "dependencies: [tool:web]\ndisplay_name: 技能一\nversion: 1.0.0\nname: a1\n",
  );
  assert.equal(manifestFingerprint(once), manifestFingerprint(reordered), "键序不影响指纹");

  // 内容不同 ⇒ 指纹必不同（指纹不是常量）
  const changed = parseManifestYaml("name: a1\nversion: 1.0.1\n");
  assert.notEqual(manifestFingerprint(once), manifestFingerprint(changed));
  // 指纹形状：64 位 hex
  assert.match(manifestFingerprint(once), /^[0-9a-f]{64}$/);
});

test("C · manifestFromDict 直接构造（对象入参）与 YAML 入参同出口；非映射 ⇒ 422", async () => {
  const { manifestFromDict } = await import("../dist/modules/skill/manifest.js");
  const direct = manifestFromDict({ name: "a1", version: "2.0.0" });
  assert.equal(direct.version, "2.0.0");
  assertValidation422(() => manifestFromDict(["not", "a", "map"]));
});

// ---------------------------------------------------------------------------
// D · 包装载（py load_skill_package 同语义：缺清单 422、缺指令宽松、资源扫描有序）
// ---------------------------------------------------------------------------

test("D · 完整包装载：manifest + instructions + 资源清单（examples→resources→scripts，逐层排序）", () => {
  const root = makeTempDir("wbtime-skill-full-");
  writeFileSync(
    join(root, "skill.yaml"),
    "name: deploy-skill\nversion: 1.0.0\ndisplay_name: 部署技能\n",
  );
  writeFileSync(join(root, DEFAULT_INSTRUCTIONS_FILE), "# 指令正文\n按序执行。\n");
  mkdirSync(join(root, "examples", "sub"), { recursive: true });
  writeFileSync(join(root, "examples", "b.md"), "b");
  writeFileSync(join(root, "examples", "sub", "a.md"), "a");
  mkdirSync(join(root, "resources"), { recursive: true });
  writeFileSync(join(root, "resources", "tpl.txt"), "T");
  mkdirSync(join(root, "scripts"), { recursive: true });
  writeFileSync(join(root, "scripts", "run.py"), "print(1)");

  const loaded = loadSkillPackage(root, { source: "workspace" });
  assert.equal(loaded.manifest.name, "deploy-skill");
  assert.equal(loaded.instructions, "# 指令正文\n按序执行。\n");
  assert.equal(loaded.source, "workspace");
  assert.deepEqual(
    loaded.resources.map((spec) => `${spec.kind}:${spec.path}`),
    [
      "example:examples/b.md",
      "example:examples/sub/a.md",
      "file:resources/tpl.txt",
      "script:scripts/run.py",
    ],
    "相对路径从包根起算（py relative_to(root.parent) 同口径）；目录内逐层排序",
  );
  assert.ok(loaded.resources.every((spec) => spec.storage_key === null), "装载期 storage_key 恒 null（py 同口径）");

  // 确定性（装载面）：同一包同参数两次装载指纹全等（source 是指纹的一部分，也须同参）
  const again = loadSkillPackage(root, { source: "workspace" });
  assert.equal(loaded.fingerprint, again.fingerprint, "同包两次装载 sha 必全等");
  assert.equal(again.source, "workspace");
  assert.equal(loadSkillPackage(root).source, "builtin", "source 缺省 builtin（另参装载）");
});

test("D · 缺指令文件宽松落空串；目录不存在 / 缺 skill.yaml / 清单非法 ⇒ 422", () => {
  // 缺 instructions.md ⇒ 不挡装载（py 同口径）
  const bare = makeTempDir("wbtime-skill-bare-");
  writeFileSync(join(bare, "skill.yaml"), "name: bare\nversion: 0.1.0\n");
  const loaded = loadSkillPackage(bare);
  assert.equal(loaded.instructions, "");
  assert.deepEqual(loaded.resources, [], "三个资源目录都不存在 ⇒ 空清单");

  // 目录不存在 ⇒ 422
  assertValidation422(() => loadSkillPackage(join(bare, "no-such-dir")));
  // 缺 skill.yaml ⇒ 422
  const noManifest = makeTempDir("wbtime-skill-nomanifest-");
  assertValidation422(() => loadSkillPackage(noManifest));
  // 清单非法（版本非法）⇒ 422（解析期死，不进装载）
  const badManifest = makeTempDir("wbtime-skill-bad-");
  writeFileSync(join(badManifest, "skill.yaml"), "name: bad\nversion: not-semver\n");
  assertValidation422(() => loadSkillPackage(badManifest));
});

test("D · 清单声明越界目录名（skill.yaml 里 resources: ../escape）⇒ 422（解析期挡下，读盘前）", () => {
  const root = makeTempDir("wbtime-skill-escape-");
  writeFileSync(join(root, "skill.yaml"), "name: evil\nversion: 1.0.0\nresources: ../escape\n");
  assertValidation422(() => loadSkillPackage(root));
});
