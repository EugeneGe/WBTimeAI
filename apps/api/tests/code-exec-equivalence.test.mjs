/**
 * T3-10 · `code_exec` 的三档 runtime 一致性证明（DoD#5 / R3-18）。
 *
 * 判据
 * ----
 *   ① **三档都不是空壳**：`python` / `node` / `bash` 各自产出正确的 argv
 *      （`-c` / `-e` / `-c`），且 **node 档真跑一次 happy path**（用真沙箱 + `process.execPath`）
 *      —— 卡面反例「`runtime=node/bash` 完全空壳 ⇒ happy-path 必红」的机器形态；
 *   ② **未知 runtime** ⇒ `VALIDATION_ERROR`（不自造第四档，也不静默按 python 跑）；
 *   ③ **本地规则先于沙箱**：危险代码 ⇒ `DENIED` 且 **exec 计数 0**（验收 ⑥）；
 *   ④ **超时 ⇒ `TOOL_TIMEOUT`**；**输出截断到 200000**（锁死项，见下）。
 *
 * `MAX_OUTPUT_CHARS = 200000` 是**锁死项**
 * ------------------------------------
 *   改它 = 放弃 `code_exec` 跨线等价（DoD#5）。本文件断言这个常量值本身 ——
 *   有人把它从 `sandbox/types.ts` 里改小 "为了省内存"，这里立刻红。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/code-exec-equivalence.test.mjs`
 */

import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { LocalProcessSandbox } from "../dist/modules/sandbox/local-process.js";
import { MAX_OUTPUT_CHARS } from "../dist/modules/sandbox/types.js";
import { createCodeExecTool } from "../dist/modules/tool/builtin/code-exec.js";

/** 记录 argv 的 fake 沙箱。 */
function recordingSandbox(result = {}) {
  const execs = [];
  return {
    execs,
    async createSession(workdir) {
      return { id: "sess-1", workdir };
    },
    async exec(session, argv, options) {
      execs.push({ argv, options });
      return {
        stdout: "ok",
        stderr: "",
        exitCode: 0,
        timedOut: false,
        durationMs: 3,
        truncated: false,
        ...result,
      };
    },
    async destroy() {},
  };
}

/** 测试解释器（可预测的假路径）。 */
const FAKE_INTERPRETERS = { python: "/fake/python3", node: "/fake/node", bash: "/fake/bash" };

/** 造上下文。 */
function contextWith(sandbox, root) {
  return {
    workspaceRoot: root,
    sandbox,
    session: { id: "sess-1", workdir: root },
    egressAllowlist: [],
  };
}

test("A-1 · 三档 argv 正确：python `-c` / node `-e` / bash `-c`", async () => {
  const tool = createCodeExecTool(FAKE_INTERPRETERS);
  const sandbox = recordingSandbox();
  const context = contextWith(sandbox, process.cwd());

  await tool.execute({ code: "print(1)" }, context);
  await tool.execute({ code: "console.log(1)", runtime: "node" }, context);
  await tool.execute({ code: "echo 1", runtime: "bash" }, context);

  assert.deepEqual(sandbox.execs[0].argv, ["/fake/python3", "-c", "print(1)"]);
  assert.deepEqual(sandbox.execs[1].argv, ["/fake/node", "-e", "console.log(1)"]);
  assert.deepEqual(sandbox.execs[2].argv, ["/fake/bash", "-c", "echo 1"]);
});

test("A-2 · 缺省 runtime = python（契约 default 的落地）", async () => {
  const tool = createCodeExecTool(FAKE_INTERPRETERS);
  const sandbox = recordingSandbox();
  await tool.execute({ code: "print(1)" }, contextWith(sandbox, process.cwd()));
  assert.equal(sandbox.execs[0].argv[0], "/fake/python3");
});

test("A-3 · **node 档真跑**（真沙箱 + process.execPath）⇒ 不是空壳", async () => {
  const root = mkdtempSync(join(tmpdir(), "wb-exec-"));
  const sandbox = new LocalProcessSandbox({ defaultTimeoutMs: 10_000 });
  try {
    const tool = createCodeExecTool({ python: "python3", node: process.execPath, bash: "bash" });
    const session = await sandbox.createSession(root);
    const result = await tool.execute(
      { code: "console.log('code-exec-ok'); console.log(1+1)", runtime: "node" },
      { workspaceRoot: root, sandbox, session }
    );

    assert.equal(result.ok, true, JSON.stringify(result));
    assert.match(result.output.stdout, /code-exec-ok/);
    assert.match(result.output.stdout, /2/, "真实执行（不是返回假字符串）");
    assert.equal(result.output.runtime, "node");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("B-1 · 未知 runtime ⇒ VALIDATION_ERROR（不静默按 python 跑）", async () => {
  const tool = createCodeExecTool(FAKE_INTERPRETERS);
  const sandbox = recordingSandbox();
  const result = await tool.execute(
    { code: "x", runtime: "ruby" },
    contextWith(sandbox, process.cwd())
  );
  assert.equal(result.ok, false);
  assert.equal(result.errorCode, "VALIDATION_ERROR");
  assert.equal(sandbox.execs.length, 0);
});

test("B-2 · 空 code ⇒ VALIDATION_ERROR", async () => {
  const tool = createCodeExecTool(FAKE_INTERPRETERS);
  const result = await tool.execute({ code: "" }, contextWith(recordingSandbox(), process.cwd()));
  assert.equal(result.errorCode, "VALIDATION_ERROR");
});

test("C-1 · 危险代码 ⇒ DENIED 且 **沙箱 exec 计数 == 0**（验收 ⑥）", async () => {
  const tool = createCodeExecTool(FAKE_INTERPRETERS);
  const sandbox = recordingSandbox();
  const context = contextWith(sandbox, process.cwd());

  const dangerous = [
    'import shutil; shutil.rmtree("/")',
    'import os; os.remove("/etc/passwd")',
    'subprocess.run(["rm", "-rf", "/"])',
    "print(WBTIME_AI_SECRET_KEY)",
    'cursor.execute("DROP DATABASE prod")',
  ];
  for (const code of dangerous) {
    const result = await tool.execute({ code }, context);
    assert.equal(result.ok, false, `${code} 必须被拦`);
    assert.equal(result.errorCode, "PERMISSION_DENIED");
  }
  assert.equal(sandbox.execs.length, 0, "本地规则命中时沙箱一次都不该被调用");
});

test("D-1 · 超时 ⇒ TOOL_TIMEOUT（且不是 INTERNAL_ERROR）", async () => {
  const tool = createCodeExecTool(FAKE_INTERPRETERS);
  const sandbox = recordingSandbox({ exitCode: null, timedOut: true, durationMs: 30_000 });
  const result = await tool.execute({ code: "print(1)" }, contextWith(sandbox, process.cwd()));
  assert.equal(result.ok, false);
  assert.equal(result.errorCode, "TOOL_TIMEOUT");
  assert.equal(result.timedOut, true);
});

test("E-1 · 输出上限是**锁死项 200000**（改它 = 放弃跨线等价）", () => {
  assert.equal(MAX_OUTPUT_CHARS, 200_000, "DoD#5 的硬钉死值，不得调小/调大");
});

test("E-2 · 超长输出 ⇒ 截断并带 truncated 标记（保留尾部，报错在最后）", async () => {
  const tool = createCodeExecTool(FAKE_INTERPRETERS);
  const long = "x".repeat(MAX_OUTPUT_CHARS + 100);
  const sandbox = recordingSandbox({ stdout: long.slice(-MAX_OUTPUT_CHARS), truncated: true });
  const result = await tool.execute({ code: "print('x')" }, contextWith(sandbox, process.cwd()));
  assert.equal(result.ok, true);
  assert.equal(result.output.truncated, true, "必须显式标记截断（否则调用方以为看到了全部）");
  assert.equal(result.output.stdout.length, MAX_OUTPUT_CHARS);
});

test("E-3 · `truncateOutput`：短输出不截断，长输出保留**尾部**", async () => {
  const { truncateOutput } = await import("../dist/modules/sandbox/types.js");
  const short = truncateOutput("hello");
  assert.deepEqual(short, { text: "hello", truncated: false });

  const payload = "A".repeat(MAX_OUTPUT_CHARS) + "TAIL-MARKER";
  const cut = truncateOutput(payload);
  assert.equal(cut.truncated, true);
  assert.equal(cut.text.endsWith("TAIL-MARKER"), true, "保留尾部：traceback 在末尾");
  assert.equal(cut.text.length, MAX_OUTPUT_CHARS);
});
