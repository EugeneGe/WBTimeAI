// @wbtime/contracts 的**结构自证**（node:test，零第三方依赖）。
//
// 本包是纯类型包：这里不测行为（没有行为可测），只测「不变量」——
// ① 零运行时依赖；② 9 个扩展点文件齐且无多余；③ 每个文件都声明 interface + 版本常量；
// ④ src/** 里没有值 import（纯类型的可断言形式）；⑤ 快照存在且 9 点 9 版本自洽。
// 深一层的「签名与旧线 Protocol 全等」由 scripts/check_extension_point_signatures.py 断言。

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";
import { describe, it } from "node:test";

const HERE = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = join(HERE, "..");
const POINTS_DIR = join(PACKAGE_ROOT, "src", "extension-points");

/** 9 个扩展点（与门禁脚本 EXPECTED_POINTS 同源，改动须同步两处）。 */
const EXPECTED_POINTS = {
  auth_provider: { interface: "AuthProvider", version: "auth_provider/v1" },
  policy_engine: { interface: "PolicyEngine", version: "policy_engine/v1" },
  audit_sink: { interface: "AuditSink", version: "audit_sink/v1" },
  secret_provider: { interface: "SecretProvider", version: "secret_provider/v1" },
  model_gateway: { interface: "ModelGateway", version: "model_gateway/v1" },
  model_provider: { interface: "ModelProviderFactory", version: "model_provider/v1" },
  connector: { interface: "Connector", version: "connector/v1" },
  ui_extension: { interface: "UIExtension", version: "ui_extension/v1" },
  agent_executor: { interface: "AgentExecutor", version: "agent_executor/v1" },
};

function read(relative) {
  return readFileSync(join(PACKAGE_ROOT, relative), "utf8");
}

/** 去掉注释后再断言（与门禁脚本同口径：注释里的示例不算 import）。 */
function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
}

function tsFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return tsFiles(full);
    return entry.name.endsWith(".ts") ? [full] : [];
  });
}

describe("package manifest", () => {
  it("零运行时依赖（dependencies 为空对象）", () => {
    const manifest = JSON.parse(read("package.json"));
    assert.deepEqual(manifest.dependencies, {});
    assert.equal(manifest.name, "@wbtime/contracts");
    // 版本基线改从「根 package.json」取，而不是写字面量 `0.1.0`：
    // 纪律 §4.2-1 要求「全栈同版」，字面量会让每次版本回写都要改测试（V0.3.0 回写即撞上）。
    // 判据不变仍是严格相等 —— 只是把基线换成单一真相源，版本漂移照样红。
    const rootManifest = JSON.parse(read("../../package.json"));
    assert.equal(manifest.version, rootManifest.version);
    assert.equal(manifest.type, "module");
  });
});

describe("extension points", () => {
  const present = readdirSync(POINTS_DIR)
    .filter((name) => name.endsWith(".ts") && name !== "index.ts")
    .map((name) => name.slice(0, -3))
    .sort();

  it("9 个点齐，且没有未登记的多余文件", () => {
    assert.deepEqual(present, Object.keys(EXPECTED_POINTS).sort());
  });

  for (const [point, expected] of Object.entries(EXPECTED_POINTS)) {
    it(`${point}：声明 interface ${expected.interface} 与版本 ${expected.version}`, () => {
      const source = read(join("src", "extension-points", `${point}.ts`));
      assert.match(source, new RegExp(`export interface ${expected.interface} \\{`));
      assert.match(source, new RegExp(`= "${expected.version}"`));
    });
  }

  it("每个 interface 至少有 1 个成员（空接口 ⇒ 门禁判 EMPTY）", () => {
    for (const point of present) {
      const source = read(join("src", "extension-points", `${point}.ts`));
      const body = source.slice(source.indexOf("export interface"));
      const members = body.match(/^\s{2}\w+\(/gm) ?? [];
      assert.ok(members.length > 0, `${point} 有 0 个成员`);
    }
  });
});

describe("pure types", () => {
  it("src/** 里没有值 import（只有 import type / export type）", () => {
    for (const file of tsFiles(join(PACKAGE_ROOT, "src"))) {
      const source = stripComments(readFileSync(file, "utf8"));
      const valueImports = source.match(/^\s*import\s+(?!type\s)[^\n]+/gm) ?? [];
      assert.deepEqual(valueImports, [], `${file} 含值 import`);
      assert.doesNotMatch(source, /\brequire\s*\(/);
      assert.doesNotMatch(source, /from\s+"@wbtime\//);
    }
  });
});

describe("signature snapshot", () => {
  const snapshot = JSON.parse(read("signature-snapshot.json"));

  it("存在且 9 点 9 版本自洽", () => {
    assert.equal(snapshot.contract, "extension-point-signatures/v1");
    assert.equal(snapshot.point_count, 9);
    assert.deepEqual(Object.keys(snapshot.points).sort(), Object.keys(EXPECTED_POINTS).sort());
    for (const [point, expected] of Object.entries(EXPECTED_POINTS)) {
      assert.equal(snapshot.points[point].version, expected.version, `${point} 版本`);
      assert.equal(snapshot.points[point].interface, expected.interface, `${point} 接口名`);
      assert.ok(
        Object.keys(snapshot.points[point].members).length > 0,
        `${point} 签名快照为空`,
      );
    }
  });
});
