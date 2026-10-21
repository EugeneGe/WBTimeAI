/**
 * T2-04 · **J-2 口令双向互验**（计划 §8；R-8：py 侧可得，不得记「依赖不可得」）。
 *
 * 判据三条，逐条落地：
 *  1. **py 生成的 PHC 串 → TS `verify` == true**：来自
 *     `tests/fixtures/py-argon2id-hashes.json`（由 py 线同参 argon2-cffi 真跑生成，
 *     **非手写**），含一条中文口令 —— 跨语言最容易分叉的就是 UTF-8 编码路径。
 *  2. **TS 生成的 PHC 串 → py `verify` == true**：调 py 侧 argon2-cffi 真跑 verify。
 *     解释器**跨平台解析**（见下），全部候选都不可得时 **显式 skip 且原因可见**
 *     （TAP `# SKIP`）—— 既不是静默通过，也不是把"环境缺件"报成代码失败。
 *  3. **参数断言**：`$argon2id$v=19$m=65536,t=3,p=4$` —— 任一项不同即红。
 *
 * 另外把「`verify` 永不抛」与 `needsRehash` 一起钉住：它们不是 J-2 的字面判据，
 * 但同属 §3.1 的冻结语义，且都是"错了不会报错、只会静默变差"的那类。
 *
 * py oracle 解释器的解析口径（审计 #28 的修复）
 * ------------------------------------------
 * 曾经这里硬编码了 `D:/WBT/WBTimeAI_old/.venv/Scripts/python.exe`（Windows 绝对路径）
 * 和 `D:/Temp/.../py-argon2.py`（上一次会话的临时文件路径）—— 在任何 Linux runner /
 * dev 服务器上必然红，且红的是**测试自身的环境耦合**，不是被测行为。现在改为：
 *
 *   ① `WBTIME_PY_ORACLE_PYTHON`（显式覆盖，优先级最高）；
 *   ② 按平台给默认候选：Windows ⇒ `<repo>/../WBTimeAI_old/.venv/Scripts/python.exe`；
 *      POSIX ⇒ 同一 venv 的 `bin/python`，再退到 `PATH` 里的 `python3`；
 *   ③ 按**存在性/可用性**取第一个；一个都没有 ⇒ `t.skip(...)`，并在 skip 文案里
 *      打印**所有试过的候选及其来源**（`env` / `platform-default`），避免"配错了变量
 *      却只看到一句跳过"。
 *
 * py 侧校验程序**内联**在本文件（`PY_ORACLE_PROGRAM`），不再依赖上一次会话留在
 * `D:/Temp` 的脚本 —— 那份临时文件同样不可能出现在服务器上。内联的是 T2-04 那个
 * helper 的 **verify 分支逐字拷贝**（参数与 py 线 `wbtime_ai_security/password.py` 一致：
 * time_cost=3 / memory_cost=65536 / parallelism=4 / hash_len=32 / salt_len=16 / Type.ID）。
 * 若要把 oracle 换成外部脚本（例如直接驱动 py 线的 `PasswordHasher`），设
 * `WBTIME_PY_ORACLE_SCRIPT` 指向它即可；I/O 契约不变：stdin `{cases:[{password,hash}]}`
 * → stdout `{results:[{password,hash_prefix,py_verify}]}`。
 */

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import {
  ARGON2_PHC_PREFIX,
  ARGON2_SALT_LENGTH,
  PasswordHasher,
} from "../dist/modules/auth/password.js";
import { ROOT } from "./auth-harness.mjs";

const FIXTURES = JSON.parse(
  readFileSync(join(ROOT, "apps", "api", "tests", "fixtures", "py-argon2id-hashes.json"), "utf8")
);

/** py 解释器 / 脚本的显式覆盖变量（名字进头注，运维可直接照抄）。 */
export const PY_ORACLE_PYTHON_ENV = "WBTIME_PY_ORACLE_PYTHON";
export const PY_ORACLE_SCRIPT_ENV = "WBTIME_PY_ORACLE_SCRIPT";

/** py 线旧仓根（venv 在这一层）。与 `ROOT` 同级：`<repo>/../WBTimeAI_old`。 */
const OLD_REPO = join(ROOT, "..", "WBTimeAI_old");

/**
 * py oracle 内联程序（T2-04 helper 的 **verify 分支逐字拷贝**）。
 *
 * 为什么内联：原实现指向 `D:/Temp/WBTimeAI/2026-10-21-T2-04/py-argon2.py` —— 那是
 * **上一次开发会话留在 Temp 的临时文件**，在任何服务器 / CI 上都不存在，于是这条用例
 * 红在"脚本不存在"，与被测行为无关（审计 #28 的同类问题）。
 *
 * I/O 契约（与外部脚本版本完全一致）：stdin `{cases:[{password,hash}]}` →
 * stdout `{results:[{password,hash_prefix,py_verify}]}`。
 */
export const PY_ORACLE_PROGRAM = `# -*- coding: utf-8 -*-
"""J-2 py 侧 oracle：校验给定 (password, hash) 对。

参数与 py 线 \`wbtime_ai_security/password.py\` 一致：
time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16, type=ID。
"""
from __future__ import annotations

import json
import sys

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def verify(password: str, hash_value: str) -> bool:
    try:
        return hasher.verify(hash_value, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


payload = json.load(sys.stdin)
results = []
for case in payload.get("cases", []):
    results.append(
        {
            "password": case["password"],
            "hash_prefix": case["hash"][:35],
            "py_verify": verify(case["password"], case["hash"]),
        }
    )
print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
`;

/**
 * 某个候选解释器是否**可用**。
 *
 * 绝对/相对路径 ⇒ 文件存在即可；裸名字（如 `python3`）⇒ 走 PATH 探测
 * （`existsSync("python3")` 恒 false，直接用会把最常见的 POSIX 情形误判成"不可得"）。
 *
 * @param {string} candidate 候选解释器（路径或 PATH 中的名字）。
 * @returns {boolean} 是否可执行。
 */
function isUsablePython(candidate) {
  const looksLikePath = candidate.includes("/") || candidate.includes("\\");
  if (looksLikePath) {
    // `existsSync` 对目录也返回 true —— 传一个目录当解释器会走到 spawn 的 EACCES，
    // 变成"莫名其妙的失败"。这里要求是**文件**，把误配挡在解析阶段。
    try {
      return statSync(candidate).isFile();
    } catch {
      return false;
    }
  }
  const probe = spawnSync(candidate, ["-c", "import sys"], { encoding: "utf8" });
  return probe.status === 0;
}

/**
 * 列出候选解释器（只算名字，不探测可用性 —— skip 文案要用它）。
 *
 * @param {{env?: Record<string, string | undefined>, platform?: string}} [options]
 * @returns {Array<{python: string, source: "env" | "platform-default"}>}
 */
export function pyOracleCandidates(options = {}) {
  const env = options.env ?? process.env;
  const platform = options.platform ?? process.platform;
  const isWindows = platform === "win32";

  /** @type {Array<{python: string, source: "env" | "platform-default"}>} */
  const candidates = [];
  const override = env[PY_ORACLE_PYTHON_ENV];
  if (typeof override === "string" && override.trim() !== "") {
    candidates.push({ python: override.trim(), source: "env" });
  }
  candidates.push({
    python: join(
      OLD_REPO,
      ".venv",
      isWindows ? "Scripts" : "bin",
      isWindows ? "python.exe" : "python"
    ),
    source: "platform-default",
  });
  if (!isWindows) {
    // POSIX 常见形态是在 PATH 里（系统 python3 + 已装 argon2-cffi）。
    candidates.push({ python: "python3", source: "platform-default" });
  }
  return candidates;
}

/**
 * 按「环境变量 → 平台默认」解析 py oracle 解释器（审计 #28）。
 *
 * 依赖全部可注入（`env` / `platform` / `usable`）：本机 Windows 上 venv 一定存在，
 * 走不到"全不可得"那条分支 —— 若不注入就没法证明 skip 判据本身是对的，只能靠
 * "在服务器上试一下"。测试必须能在任何机器上自证，这是本仓的既有要求。
 *
 * @param {{env?: Record<string, string | undefined>, platform?: string,
 *   usable?: (candidate: string) => boolean}} [options]
 * @returns {{python: string, source: "env" | "platform-default"} | null}
 *   `null` 表示所有候选都不可得（调用方必须 **skip 而不是 fail**）。
 */
export function resolvePyOraclePython(options = {}) {
  const usable = options.usable ?? isUsablePython;
  for (const candidate of pyOracleCandidates(options)) {
    if (usable(candidate.python)) return candidate;
  }
  return null;
}

/** 解析一次（模块加载期）。 */
const PY_ORACLE = resolvePyOraclePython();

/** 外部 oracle 脚本（可选；给了就必须存在，配错要 fail loud 而不是悄悄跳过）。 */
const PY_ORACLE_SCRIPT = (() => {
  const raw = process.env[PY_ORACLE_SCRIPT_ENV];
  if (typeof raw !== "string" || raw.trim() === "") return null;
  assert.ok(
    existsSync(raw.trim()),
    `${PY_ORACLE_SCRIPT_ENV} 指向的脚本不存在：${raw.trim()}（显式配置错了必须当场报错，不能跳过）`
  );
  return raw.trim();
})();

/**
 * 拼出运行 oracle 的 argv（内联程序 or 外部脚本）。
 *
 * @returns {string[]} 传给 `spawnSync` 的 python 参数。
 */
function oracleArgs() {
  // `-c` 之后第一个非选项参数会成为 `sys.argv[1]`，因此内联程序不需要 argv 分派。
  return PY_ORACLE_SCRIPT === null ? ["-c", PY_ORACLE_PROGRAM] : [PY_ORACLE_SCRIPT, "verify"];
}

const hasher = new PasswordHasher();

/** 从 PHC 串里抽参数（测试**自己**解析，不复用被测代码的解析器）。 */
function parsePhc(encoded) {
  const match = /^\$argon2id\$v=(\d+)\$m=(\d+),t=(\d+),p=(\d+)\$([A-Za-z0-9+/]+)\$([A-Za-z0-9+/]+)$/.exec(
    encoded
  );
  if (!match) throw new Error(`不是合法的 argon2id PHC 串：${encoded.slice(0, 24)}…`);
  const [, version, memoryCost, timeCost, parallelism, salt, digest] = match;
  return {
    version: Number(version),
    memoryCost: Number(memoryCost),
    timeCost: Number(timeCost),
    parallelism: Number(parallelism),
    saltBytes: Buffer.from(salt, "base64").length,
    digestBytes: Buffer.from(digest, "base64").length,
  };
}

test("J-2① py 生成的 PHC 串 → TS verify == true（3 条，含中文口令）", async () => {
  assert.equal(FIXTURES.fixtures.length, 3, "py 侧基准必须 3 条");
  for (const fixture of FIXTURES.fixtures) {
    assert.equal(
      fixture.salt_len,
      16,
      `[${fixture.password}] py 侧 salt_len 必须是 16（基准自身要正确）`
    );
    assert.equal(
      await hasher.verify(fixture.password, fixture.hash),
      true,
      `[${fixture.password}] py 生成的 PHC 在 TS 侧必须 verify 通过`
    );
    // 反例：换一个字符就该 false（否则 verify 可能恒真）
    assert.equal(
      await hasher.verify(`${fixture.password}x`, fixture.hash),
      false,
      `[${fixture.password}] 错口令必须 false`
    );
  }
});

test("J-2③ 参数断言：$argon2id$v=19$m=65536,t=3,p=4$ + salt 16B + digest 32B", async () => {
  const cases = [
    ...FIXTURES.fixtures.map((item) => ({ source: "py", hash: item.hash })),
    { source: "ts", hash: await hasher.hash("参数断言用口令") },
  ];
  for (const item of cases) {
    assert.ok(
      item.hash.startsWith(ARGON2_PHC_PREFIX),
      `[${item.source}] PHC 前缀必须 ${ARGON2_PHC_PREFIX}，实测 ${item.hash.slice(0, 34)}…`
    );
    const parsed = parsePhc(item.hash);
    assert.deepEqual(
      {
        version: parsed.version,
        memoryCost: parsed.memoryCost,
        timeCost: parsed.timeCost,
        parallelism: parsed.parallelism,
        saltBytes: parsed.saltBytes,
        digestBytes: parsed.digestBytes,
      },
      {
        version: 19,
        memoryCost: 65536,
        timeCost: 3,
        parallelism: 4,
        saltBytes: ARGON2_SALT_LENGTH,
        digestBytes: 32,
      },
      `[${item.source}] 参数必须与计划 §3.1 完全一致`
    );
  }
});

test("J-2② TS 生成的 PHC 串 → py verify == true（真调 py 侧 argon2-cffi）", async (t) => {
  const cases = [];
  for (const password of ["correct horse battery staple", "ts-side-口令-2026"]) {
    cases.push({ password, hash: await hasher.hash(password) });
  }

  // ① 解释器不可得 ⇒ **显式 skip**（TAP `# SKIP`），并把试过的候选全部打印出来。
  //    绝不 assert.fail：那是"环境缺件"，不是"实现错了"（审计 #28 的红就是这么来的）。
  if (PY_ORACLE === null) {
    t.skip(
      `py oracle 解释器不可得，J-2② **未验证**；试过的候选：${pyOracleCandidates()
        .map((item) => `${item.python} (${item.source})`)
        .join(" , ")}；可用 ${PY_ORACLE_PYTHON_ENV}=<绝对路径> 显式指定`
    );
    return;
  }
  t.diagnostic(`py oracle: ${PY_ORACLE.python}（source=${PY_ORACLE.source}）`);

  const run = spawnSync(PY_ORACLE.python, oracleArgs(), {
    input: JSON.stringify({ cases }),
    encoding: "utf8",
  });

  // ② 解释器在、但 argon2-cffi 没装 ⇒ 同样是环境缺件，skip 且原因可见。
  if (run.status !== 0 && /No module named ['"]?argon2/i.test(String(run.stderr))) {
    t.skip(`py 侧 argon2-cffi 不可用，J-2② **未验证**：${String(run.stderr).trim().split("\n").pop()}`);
    return;
  }
  // ③ 其它非零退出是**真失败**（脚本/契约错了），必须红。
  if (run.status !== 0) {
    t.diagnostic(`py stderr: ${run.stderr}`);
    assert.fail(`py 侧校验脚本执行失败（exit=${String(run.status)}，python=${PY_ORACLE.python}）`);
  }

  const out = JSON.parse(run.stdout);
  assert.equal(out.results.length, cases.length);
  for (const result of out.results) {
    assert.equal(
      result.py_verify,
      true,
      `TS 生成的 PHC 必须被 py 验证通过：${result.hash_prefix}…`
    );
  }
  t.diagnostic(`py 侧逐条 verify：${JSON.stringify(out.results.map((r) => r.py_verify))}`);
});

test("J-2② 解释器解析（审计 #28）：env 优先 / POSIX 回落 python3 / 全不可得 ⇒ skip 判据", () => {
  // ① 环境变量优先：显式给了就用它（哪怕平台默认也存在）
  const viaEnv = resolvePyOraclePython({
    env: { [PY_ORACLE_PYTHON_ENV]: "/opt/py/bin/python3" },
    platform: "linux",
    usable: (candidate) => candidate === "/opt/py/bin/python3",
  });
  assert.deepEqual(viaEnv, { python: "/opt/py/bin/python3", source: "env" });

  // ② POSIX：venv 不在 ⇒ 回落到 PATH 里的 python3（而不是直接判不可得）
  const viaPath = resolvePyOraclePython({
    env: {},
    platform: "linux",
    usable: (candidate) => candidate === "python3",
  });
  assert.deepEqual(viaPath, { python: "python3", source: "platform-default" });

  // ③ Windows 只给 venv 一个候选，且路径形态必须是 Scripts/python.exe
  const windowsCandidates = pyOracleCandidates({ env: {}, platform: "win32" });
  assert.equal(windowsCandidates.length, 1);
  assert.match(windowsCandidates[0].python.replace(/\\/g, "/"), /\.venv\/Scripts\/python\.exe$/);
  assert.equal(windowsCandidates[0].source, "platform-default");

  // ④ 全不可得 ⇒ 返回 null（这是 J-2② 走 t.skip 的唯一条件；绝不能变成 assert 失败）
  assert.equal(
    resolvePyOraclePython({ env: {}, platform: "linux", usable: () => false }),
    null,
    "所有候选都不可用时必须返回 null ⇒ 调用方 skip"
  );

  // ⑤ 可选：显式配置却指向不存在的脚本 ⇒ 加载期就要 fail loud（不是跳过）
  assert.ok(
    process.env[PY_ORACLE_SCRIPT_ENV] === undefined ||
      existsSync(String(process.env[PY_ORACLE_SCRIPT_ENV])),
    `${PY_ORACLE_SCRIPT_ENV} 若设置则必须指向存在的脚本`
  );
});

test("verify 永不抛：非法 / 空 / 错算法 / 截断的哈希一律 false", async () => {
  const bad = [
    "",
    "not-a-hash",
    "$argon2i$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaA", // 错算法
    "$argon2id$v=19$m=65536,t=3,p=4$", // 截断
    "$argon2id$v=19$m=65536,t=3,p=1$AAAA$BBBB", // 参数不符但语法像
  ];
  for (const stored of bad) {
    assert.equal(
      await hasher.verify("whatever", stored),
      false,
      `非法哈希必须返回 false 而不是抛错：${JSON.stringify(stored.slice(0, 24))}`
    );
  }
  assert.equal(await hasher.verify("", FIXTURES.fixtures[0].hash), false, "空口令必须 false");
});

test("needsRehash：当前参数 false；参数不同 / 不可解析 true", async () => {
  const current = await hasher.hash("needs-rehash");
  assert.equal(hasher.needsRehash(current), false, "当前参数的哈希不该被判需要重算");

  // m=19456（@node-rs/argon2 的默认值）⇒ 需要重算（说明判定真的在看 m）
  const weaker =
    "$argon2id$v=19$m=19456,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$" + "A".repeat(43);
  assert.equal(hasher.needsRehash(weaker), true, "memoryCost 不同必须判需要重算");
  assert.equal(hasher.needsRehash("garbage"), true, "不可解析必须判需要重算（否则用户永远登不进）");
  assert.equal(hasher.needsRehash(""), true);
});

test("hash 每次取新盐（同一口令两次哈希必须不同，且都能验证通过）", async () => {
  const a = await hasher.hash("same-password");
  const b = await hasher.hash("same-password");
  assert.notEqual(a, b, "两次哈希必须不同（盐必须随机）");
  assert.equal(await hasher.verify("same-password", a), true);
  assert.equal(await hasher.verify("same-password", b), true);
});
