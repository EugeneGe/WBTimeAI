/**
 * T2-04 · **J-2 口令双向互验**（计划 §8；R-8：py 侧可得，不得记「依赖不可得」）。
 *
 * 判据三条，逐条落地：
 *  1. **py 生成的 PHC 串 → TS `verify` == true**：来自
 *     `tests/fixtures/py-argon2id-hashes.json`（由 py 线同参 argon2-cffi 真跑生成，
 *     **非手写**），含一条中文口令 —— 跨语言最容易分叉的就是 UTF-8 编码路径。
 *  2. **TS 生成的 PHC 串 → py `verify` == true**：调 py 侧 argon2-cffi 真跑 verify。
 *     解释器**只能**由 `WBTIME_PY_ORACLE_PYTHON` 显式给出（见下）；没给 ⇒ **红**并点名
 *     该变量。唯一的 skip 出口是 `WBTIME_ALLOW_MISSING_PY_ORACLE=1`，且必须
 *     `console.warn` 写明「本次 skip 不构成等效性证明」—— 静默 skip 会让"等效性证明"
 *     在换目录跑时无声退化。
 *  3. **参数断言**：`$argon2id$v=19$m=65536,t=3,p=4$` —— 任一项不同即红。
 *
 * 另外把「`verify` 永不抛」与 `needsRehash` 一起钉住：它们不是 J-2 的字面判据，
 * 但同属 §3.1 的冻结语义，且都是"错了不会报错、只会静默变差"的那类。
 *
 * py oracle 解释器的解析口径（审计 #28 + J-2② 的 fail loud 化）
 * ------------------------------------------------------------
 * 曾经这里硬编码了 `D:/WBT/WBTimeAI_old/.venv/Scripts/python.exe`（Windows 绝对路径）
 * 和 `D:/Temp/.../py-argon2.py`（上一次会话的临时文件路径）—— 在任何 Linux runner /
 * dev 服务器上必然红，且红的是**测试自身的环境耦合**，不是被测行为。
 *
 * 硬编码修掉之后又冒出第二个问题：**静默 skip**。同一份代码、同一台机器 ——
 * 在主仓跑时 `<repo>/../WBTimeAI_old/.venv/...` 存在 ⇒ pass；换个目录（worktree）跑
 * 时同一路径不存在 ⇒ # SKIP。而 skip 在 TAP 里看起来"没事"，于是「J-2② 等效性证明」
 * 在换目录时**无声退化**。这违反本仓既定纪律「不可达须显式挂账，禁以缺省冒充实证」。
 *
 * 所以接受来源收窄为**显式环境变量**一条：
 *
 *   ① `WBTIME_PY_ORACLE_PYTHON`（文档化的唯一入口）。给了却不可用 ⇒ **当场抛**
 *      （配错必须 fail loud，绝不回落到别处）；
 *   ② 没给 ⇒ **抛**，错误信息点名该变量，并把「兜底探测」结果一并打印：
 *      `<repo>/../WBTimeAI_old/.venv/{Scripts,bin}/python[.exe]`、POSIX 的 `python3`。
 *      这些候选只用来**写提示**（"这个路径存在，请显式指定它"），
 *      **不是接受来源** —— 否则「不设变量 ⇒ 红」这条判据在"本机 venv 恰好在"时
 *      永远成立不了，静默退化的口子又开了。
 *   ③ 唯一逃生口：`WBTIME_ALLOW_MISSING_PY_ORACLE=1`（只认字面 `"1"`）⇒ 不抛，
 *      返回 null；调用方 `t.skip` 且 `console.warn` 明确写「本次 skip 不构成等效性证明」。
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

/**
 * **唯一**允许"本次不验证 J-2②"的逃生口。
 *
 * 只认字面 `"1"`：`"true"` / `"yes"` / `"0"` 一律不认 —— 与 `WBTIME_AI_ALLOW_FAKE_PROVIDER`
 * 同一口径（配置项"看起来像开了、其实没开"是哑失败的经典来源）。
 */
export const ALLOW_MISSING_PY_ORACLE_ENV = "WBTIME_ALLOW_MISSING_PY_ORACLE";
const ALLOW_MISSING_VALUE = "1";

/** 是否显式允许在 py oracle 不可得时 skip（见 {@link ALLOW_MISSING_PY_ORACLE_ENV}）。 */
export function allowsMissingPyOracle(env = process.env) {
  return env[ALLOW_MISSING_PY_ORACLE_ENV] === ALLOW_MISSING_VALUE;
}

/**
 * py 线旧仓根（venv 在这一层）。与 `ROOT` 同级：`<repo>/../WBTimeAI_old`。
 *
 * ⚠️ 只用于**兜底探测**（把"这个路径存在，请显式指定它"写进错误提示），
 * **不是**解释器的接受来源 —— 理由见文件头注：相对定位一换目录就失效，
 * 把它当来源就等于把 "pass/skip 取决于从哪个目录跑" 重新引入。
 */
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
 * 返回的 `source` 决定**能否被采纳**：只有 `"env"` 是接受来源；
 * `"platform-default"` 只用来写提示。
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
 * 解析 py oracle 解释器 —— **fail loud**，不静默退化成 skip。
 *
 * 三态（逐态都有单测，见「J-2② 解释器解析」那条）：
 *  1. `WBTIME_PY_ORACLE_PYTHON` 给了且可用 ⇒ 返回它（`source: "env"`）；
 *  2. 给了但不可用 ⇒ **抛**（配错必须当场报，绝不回落到兜底）；
 *  3. 没给 ⇒ **抛**并点名该变量；唯一例外是 `WBTIME_ALLOW_MISSING_PY_ORACLE=1`
 *     ⇒ `console.warn` + 返回 `null`（调用方 skip，且 skip **不构成等效性证明**）。
 *
 * 依赖全部可注入（`env` / `platform` / `usable`）：本机 venv 一定存在，走不到
 * "不可得"那条分支 —— 不注入就没法证明这三态判据本身是对的，只能靠"在服务器上试一下"。
 * 测试必须能在任何机器上自证，这是本仓的既有要求。
 *
 * @param {{env?: Record<string, string | undefined>, platform?: string,
 *   usable?: (candidate: string) => boolean}} [options]
 * @returns {{python: string, source: "env"} | null}
 *   `null` **只在** `WBTIME_ALLOW_MISSING_PY_ORACLE=1` 时返回（其余情形一律抛）。
 * @throws {Error} 不可解析时必须抛 —— 这是本函数存在的意义（旧版返回 null ⇒ 静默 skip）。
 */
export function resolvePyOraclePython(options = {}) {
  const env = options.env ?? process.env;
  const usable = options.usable ?? isUsablePython;
  const explicit = env[PY_ORACLE_PYTHON_ENV];

  // ① 显式指定：有就用它；**配错必须当场报错**（不回落到兜底候选）
  if (typeof explicit === "string" && explicit.trim() !== "") {
    const candidate = { python: explicit.trim(), source: /** @type {const} */ ("env") };
    if (usable(candidate.python)) return candidate;
    throw new Error(
      `${PY_ORACLE_PYTHON_ENV} 指向的解释器不可用：${candidate.python} —— ` +
        "显式配置错了必须当场报错，不能悄悄地回落到别的候选（那会让 J-2② 看起来跑过了）"
    );
  }

  // ② 没显式指定 ⇒ 只把「兜底探测」结果写进提示，**不采纳**
  const probes = pyOracleCandidates({ env, platform: options.platform }).filter(
    (candidate) => candidate.source !== "env"
  );
  const tried = probes.length === 0 ? "(无)" : probes.map((item) => item.python).join(" , ");
  const usableProbes = probes.filter((candidate) => usable(candidate.python));

  if (allowsMissingPyOracle(env)) {
    console.warn(
      `[J-2②] 未设置 ${PY_ORACLE_PYTHON_ENV}，兜底探测：${tried}；` +
        `因 ${ALLOW_MISSING_PY_ORACLE_ENV}=${ALLOW_MISSING_VALUE} 已置位 ⇒ 本轮 skip，` +
        "**本次 skip 不构成等效性证明**（TS→py 方向的口令互验没有跑）。"
    );
    return null;
  }

  const hint =
    usableProbes.length === 0
      ? `兜底探测均不可用：${tried}`
      : `兜底探测中 ${usableProbes.map((item) => item.python).join(" , ")} 存在/可用，` +
        "但按纪律不采用（相对路径换目录即失效）";
  throw new Error(
    `J-2② 需要 py oracle 解释器，但没有设置 ${PY_ORACLE_PYTHON_ENV} —— ` +
      `请把它设为装了 argon2-cffi 的 py 解释器绝对路径（例：` +
      `${PY_ORACLE_PYTHON_ENV}=D:/WBT/WBTimeAI_old/.venv/Scripts/python.exe）。` +
      `${hint}。仅当明确接受「本轮不做等效性证明」时，才设 ` +
      `${ALLOW_MISSING_PY_ORACLE_ENV}=${ALLOW_MISSING_VALUE} 跳过。`
  );
}

/**
 * **不在模块加载期解析**：解析失败要表现为「J-2② 这一条红」，而不是整个文件
 * 加载失败（后者会让 J-2①/③ 这些与 py 无关的判据一起消失，红点定位变模糊）。
 * 每次调用 `resolvePyOraclePython()` 一次，它在不可解析时会抛 —— fail loud 落在用例里。
 */

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

  // ① 解释器解析：**不可解析 ⇒ 本用例必须红**，且报错信息点名 WBTIME_PY_ORACLE_PYTHON。
  //    旧版在这里 t.skip —— 那是"静默退化"：换个目录跑就从 pass 变 skip，而 skip 看起来没事。
  //    唯一允许 skip 的路径是 WBTIME_ALLOW_MISSING_PY_ORACLE=1（此时 resolve 返回 null
  //    且已经 console.warn 过"本次 skip 不构成等效性证明"）。
  let oracle;
  try {
    oracle = resolvePyOraclePython();
  } catch (error) {
    assert.fail(error.message);
    return;
  }
  if (oracle === null) {
    t.skip(
      `J-2② **未验证**（${ALLOW_MISSING_PY_ORACLE_ENV}=${process.env[ALLOW_MISSING_PY_ORACLE_ENV]}）` +
        "—— 本次 skip **不构成等效性证明**"
    );
    return;
  }
  t.diagnostic(`py oracle: ${oracle.python}（source=${oracle.source}）`);

  const run = spawnSync(oracle.python, oracleArgs(), {
    input: JSON.stringify({ cases }),
    encoding: "utf8",
  });

  // ② 解释器在、但 argon2-cffi 没装 ⇒ 同样是"等效性证明没做"，默认 **fail loud**；
  //    只有显式 WBTIME_ALLOW_MISSING_PY_ORACLE=1 才允许 skip（并 warn）。
  if (run.status !== 0 && /No module named ['"]?argon2/i.test(String(run.stderr))) {
    const detail = String(run.stderr).trim().split("\n").pop();
    if (allowsMissingPyOracle()) {
      console.warn(
        `[J-2②] py oracle（${oracle.python}）缺 argon2-cffi ⇒ 本轮 skip，` +
          `**本次 skip 不构成等效性证明**：${detail}`
      );
      t.skip(`py 侧 argon2-cffi 不可用，J-2② **未验证**：${detail}`);
      return;
    }
    assert.fail(
      `py oracle（${oracle.python}）缺少 argon2-cffi —— 装上依赖，或设 ` +
        `${ALLOW_MISSING_PY_ORACLE_ENV}=${ALLOW_MISSING_VALUE} 明确接受"不验证"：${detail}`
    );
  }
  // ③ 其它非零退出是**真失败**（脚本/契约错了），必须红。
  if (run.status !== 0) {
    t.diagnostic(`py stderr: ${run.stderr}`);
    assert.fail(`py 侧校验脚本执行失败（exit=${String(run.status)}，python=${oracle.python}）`);
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

test("J-2② 解释器解析（fail loud）：env 优先 / 未设 ⇒ 抛并点名变量 / ALLOW=1 ⇒ 才 null", () => {
  // ① 显式给了且可用 ⇒ 用它（`source: "env"` 是**唯一**能被采纳的来源）
  const viaEnv = resolvePyOraclePython({
    env: { [PY_ORACLE_PYTHON_ENV]: "/opt/py/bin/python3" },
    platform: "linux",
    usable: (candidate) => candidate === "/opt/py/bin/python3",
  });
  assert.deepEqual(viaEnv, { python: "/opt/py/bin/python3", source: "env" });

  // ② 显式给了却不可用 ⇒ **抛**，点名变量（配错绝不静默回落到兜底候选）
  assert.throws(
    () =>
      resolvePyOraclePython({
        env: { [PY_ORACLE_PYTHON_ENV]: "/nope/python" },
        platform: "linux",
        usable: () => false,
      }),
    (error) => {
      assert.match(error.message, new RegExp(PY_ORACLE_PYTHON_ENV));
      assert.match(error.message, /不可用/);
      return true;
    },
    "显式配置错了必须当场报错"
  );

  // ③ 未设 + 兜底探测**存在可用**（POSIX 的 python3）⇒ 仍然**抛**，且提示里点出那个路径。
  //    这一格是「兜底不是接受来源」的证明：本机 venv 恰好在时，静默退化的口子就在这里。
  assert.throws(
    () =>
      resolvePyOraclePython({
        env: {},
        platform: "linux",
        usable: (candidate) => candidate === "python3",
      }),
    (error) => {
      assert.match(error.message, new RegExp(PY_ORACLE_PYTHON_ENV));
      assert.match(error.message, /python3/, "提示里要写出探测到可用但按纪律不采用的路径");
      assert.match(error.message, /不采用/);
      return true;
    },
    "兜底候选可用也不能悄悄采用 —— 否则「不设变量 ⇒ 红」这条判据在本机永远成立不了"
  );

  // ④ 未设 + 兜底全不可得 + 无 ALLOW ⇒ **抛**（不许静默 skip），两个变量名都要出现
  assert.throws(
    () => resolvePyOraclePython({ env: {}, platform: "win32", usable: () => false }),
    (error) => {
      assert.match(error.message, new RegExp(PY_ORACLE_PYTHON_ENV));
      assert.match(error.message, new RegExp(ALLOW_MISSING_PY_ORACLE_ENV));
      return true;
    },
    "不可解析时必须抛，而不是返回 null 让调用方 skip"
  );

  // ⑤ 唯一逃生口：ALLOW=1 ⇒ 返回 null（调用方 skip，且已 warn「不构成等效性证明」）
  const warned = [];
  const originalWarn = console.warn;
  console.warn = (...args) => warned.push(args.join(" "));
  try {
    assert.equal(
      resolvePyOraclePython({
        env: { [ALLOW_MISSING_PY_ORACLE_ENV]: "1" },
        platform: "win32",
        usable: () => false,
      }),
      null,
      "ALLOW=1 是唯一允许 skip 的路径"
    );
  } finally {
    console.warn = originalWarn;
  }
  assert.equal(warned.length, 1, "skip 路径必须 warn 一次（不许安静地跳过）");
  assert.match(warned[0], /不构成等效性证明/);

  // ⑥ ALLOW 只认字面 "1"：`"true"` 不算 ⇒ 仍旧抛（"看起来像开了其实没开"是哑失败）
  assert.throws(
    () =>
      resolvePyOraclePython({
        env: { [ALLOW_MISSING_PY_ORACLE_ENV]: "true" },
        platform: "win32",
        usable: () => false,
      }),
    (error) => {
      assert.match(error.message, new RegExp(ALLOW_MISSING_PY_ORACLE_ENV));
      return true;
    },
    `${ALLOW_MISSING_PY_ORACLE_ENV} 只认字面 "1"`
  );

  // ⑦ Windows 只给 venv 一个兜底候选，路径形态必须是 Scripts/python.exe
  const windowsCandidates = pyOracleCandidates({ env: {}, platform: "win32" });
  assert.equal(windowsCandidates.length, 1);
  assert.match(windowsCandidates[0].python.replace(/\\/g, "/"), /\.venv\/Scripts\/python\.exe$/);
  assert.equal(windowsCandidates[0].source, "platform-default");

  // ⑧ 可选：显式配置却指向不存在的 oracle 脚本 ⇒ 加载期就 fail loud（不是跳过）
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
