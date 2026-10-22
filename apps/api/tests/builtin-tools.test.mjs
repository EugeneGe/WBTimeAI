/**
 * T3-10 · 5 个内置工具的行为证明（DoD#3 + 验收 ⑥「命中本地规则 ⇒ 沙箱 exec 计数 == 0」）。
 *
 * 判据
 * ----
 *   ① **注册表与契约表逐字对齐**（A 组）：`BUILTIN_REGISTRY` 的 name 集合 ==
 *      `packages/db` 的 `BUILTIN_TOOLS` 名单，且 `requiresSandbox` 一致。
 *      单边加一个工具（或改一个沙箱标记）立刻红。
 *   ② **filesystem 四动作**真跑（真临时目录），越界 ⇒ `DENIED`（B 组）。
 *   ③ **本地规则先于沙箱**（C 组）：危险 shell 命令 ⇒ `DENIED` 且 **fake 沙箱 exec 计数 == 0**
 *      —— 这是验收 ⑥ 的机器形态。
 *   ④ **http / git clone 的出网闸**（D / E 组）：无白名单 / 内网 / 无沙箱 都拒。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/builtin-tools.test.mjs`
 */

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { BUILTIN_TOOLS } from "@wbtime/db";

import { BUILTIN_REGISTRY, registeredToolNames, sandboxedToolNames } from "../dist/modules/tool/registry.js";

/** 计数沙箱（每次 `exec` 都记下来）。 */
function countingSandbox(result = { stdout: "ok", stderr: "", exitCode: 0, timedOut: false, durationMs: 1, truncated: false }) {
  const execs = [];
  return {
    execs,
    async createSession(workdir) {
      return { id: "sess-1", workdir };
    },
    async exec(session, argv, options) {
      execs.push({ argv, options });
      return { ...result };
    },
    async destroy() {},
  };
}

/** 建临时 workspace。 */
function makeWorkspace() {
  const root = mkdtempSync(join(tmpdir(), "wb-tools-"));
  return { root, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

/** 工具上下文（带 fake 沙箱）。 */
function toolContext(root, extra = {}) {
  const sandbox = extra.sandbox ?? countingSandbox();
  return {
    sandbox,
    context: {
      workspaceRoot: root,
      sandbox,
      session: { id: "sess-1", workdir: root },
      egressAllowlist: [],
      ...extra,
    },
  };
}

// ---------------------------------------------------------------------------
// A 组 · 注册表与契约表对齐
// ---------------------------------------------------------------------------

test("A-1 · 注册表 name 集合与 `BUILTIN_TOOLS` 逐字相同（5 个，一个不多一个不少）", () => {
  const contract = BUILTIN_TOOLS.map((tool) => tool.name).sort();
  assert.deepEqual(registeredToolNames(), contract, "两边的工具名单必须逐字相同");
  assert.equal(contract.length, 5);
});

test("A-2 · `requiresSandbox` 与契约表一致（git / shell / code_exec 需要）", () => {
  const contractSandboxed = BUILTIN_TOOLS.filter((tool) => tool.requiresSandbox)
    .map((tool) => tool.name)
    .sort();
  assert.deepEqual(sandboxedToolNames(), contractSandboxed);
  assert.deepEqual(contractSandboxed, ["code_exec", "git", "shell"]);
});

test("A-3 · 每个工具的 spec 与实现同名（防「注册表键写错」）", () => {
  for (const [key, tool] of BUILTIN_REGISTRY) {
    assert.equal(key, tool.name, `Map 键 ${key} 与工具自报的名字 ${tool.name} 不符`);
  }
});

// ---------------------------------------------------------------------------
// B 组 · filesystem
// ---------------------------------------------------------------------------

test("B-1 · filesystem 四动作真跑：write → read → list → delete", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("filesystem");
    const { context } = toolContext(ws.root);

    const written = await tool.execute({ action: "write", path: "a.txt", content: "你好" }, context);
    assert.equal(written.ok, true, JSON.stringify(written));
    assert.equal(readFileSync(join(ws.root, "a.txt"), "utf8"), "你好");

    const read = await tool.execute({ action: "read", path: "a.txt" }, context);
    assert.equal(read.ok, true);
    assert.equal(read.output.content, "你好");

    const listed = await tool.execute({ action: "list", path: "." }, context);
    assert.equal(listed.ok, true);
    assert.deepEqual(listed.output.entries.map((entry) => entry.name), ["a.txt"]);

    const deleted = await tool.execute({ action: "delete", path: "a.txt" }, context);
    assert.equal(deleted.ok, true);
  } finally {
    ws.cleanup();
  }
});

test("B-2 · filesystem 越界 / 未知 action / 非法 encoding 都折成失败结果（不抛）", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("filesystem");
    const { context } = toolContext(ws.root);

    const escape = await tool.execute({ action: "read", path: "../etc/passwd" }, context);
    assert.equal(escape.ok, false);
    assert.equal(escape.errorCode, "PERMISSION_DENIED");

    const unknown = await tool.execute({ action: "chmod", path: "a" }, context);
    assert.equal(unknown.errorCode, "VALIDATION_ERROR");

    const badEncoding = await tool.execute({ action: "read", path: "a.txt", encoding: "latin1" }, context);
    assert.equal(badEncoding.errorCode, "VALIDATION_ERROR");
  } finally {
    ws.cleanup();
  }
});

// ---------------------------------------------------------------------------
// C 组 · shell（本地规则先于沙箱 —— 验收 ⑥）
// ---------------------------------------------------------------------------

test("C-1 · 危险命令 ⇒ DENIED 且 **沙箱 exec 计数 == 0**", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("shell");
    const { context, sandbox } = toolContext(ws.root);

    for (const command of ["rm -rf /", "sudo ls", "mkfs.ext4 /dev/sda", "echo `whoami`"]) {
      const result = await tool.execute({ command }, context);
      assert.equal(result.ok, false, `${command} 必须被拦`);
      assert.equal(result.errorCode, "PERMISSION_DENIED");
    }
    assert.equal(sandbox.execs.length, 0, "命中本地规则时沙箱一次都不该被调用（验收 ⑥）");
  } finally {
    ws.cleanup();
  }
});

test("C-2 · 正常命令 ⇒ 走沙箱（`sh -c` 包装），返回 stdout", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("shell");
    const sandbox = countingSandbox({ stdout: "hello\n", stderr: "", exitCode: 0, timedOut: false, durationMs: 5, truncated: false });
    const { context } = toolContext(ws.root, { sandbox });

    const result = await tool.execute({ command: "echo hello" }, context);
    assert.equal(result.ok, true);
    assert.equal(result.output.stdout, "hello\n");
    assert.equal(sandbox.execs.length, 1);
    const argv = sandbox.execs[0].argv;
    assert.equal(argv[2], "echo hello", "整条命令作为 `-c` 的参数（唯一经 shell 的路径）");
  } finally {
    ws.cleanup();
  }
});

test("C-3 · 无沙箱 ⇒ 失败且**不回落宿主**", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("shell");
    const result = await tool.execute({ command: "echo hi" }, { workspaceRoot: ws.root });
    assert.equal(result.ok, false);
    assert.equal(result.errorCode, "INTERNAL_ERROR");
    assert.match(result.error, /需要沙箱/);
  } finally {
    ws.cleanup();
  }
});

// ---------------------------------------------------------------------------
// D 组 · http 出网闸
// ---------------------------------------------------------------------------

test("D-1 · 无白名单 ⇒ DENIED（默认拒绝全部），且**不发请求**", async () => {
  const tool = BUILTIN_REGISTRY.get("http");
  const result = await tool.execute(
    { url: "https://example.com/" },
    { workspaceRoot: process.cwd(), egressAllowlist: [] }
  );
  assert.equal(result.ok, false);
  assert.equal(result.errorCode, "PERMISSION_DENIED");
});

test("D-2 · 白名单命中但解析到内网 ⇒ DENIED", async () => {
  const tool = BUILTIN_REGISTRY.get("http");
  const result = await tool.execute(
    { url: "https://evil.example/" },
    {
      workspaceRoot: process.cwd(),
      egressAllowlist: ["*.example"],
      resolver: async () => ["10.0.0.1"],
    }
  );
  assert.equal(result.ok, false);
  assert.equal(result.errorCode, "PERMISSION_DENIED");
  assert.match(result.error, /内网/);
});

// ---------------------------------------------------------------------------
// E 组 · git
// ---------------------------------------------------------------------------

test("E-1 · action 白名单先于一切：`push` 等危险子命令**根本不可达**（VALIDATION_ERROR）", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("git");
    const { context, sandbox } = toolContext(ws.root);

    // 5 个 action（clone/status/diff/commit/branch）之外的子命令一律 VALIDATION_ERROR。
    // 这比"黑名单拦住 push --force"更强：连表达都表达不出来。
    for (const action of ["push", "reset", "filter-branch", "clean"]) {
      const result = await tool.execute({ action, args: ["--force"] }, context);
      assert.equal(result.ok, false, `${action} 必须被 action 白名单挡住`);
      assert.equal(result.errorCode, "VALIDATION_ERROR");
    }
    assert.equal(sandbox.execs.length, 0, "白名单拒绝时不得下沙箱");

    // 对照：合法 action 确实下沙箱（否则上面的 0 次可能只是"什么都没做"）
    const ok = await tool.execute({ action: "status", args: [] }, context);
    assert.equal(ok.ok, true);
    assert.equal(sandbox.execs.length, 1);
  } finally {
    ws.cleanup();
  }
});

test("E-1b · 遗留登记：`args` 不受路径校验（`diff --no-index` 可读任意文件）", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("git");
    const { context, sandbox } = toolContext(ws.root);

    // 这是**已知遗留**（与 py 同形）：`check_git_command` 只挡 5 条危险子命令，
    // 不校验 args 里的路径；`git diff --no-index /etc/passwd /dev/null` 会在沙箱
    // （cwd 限定，但**不隔离文件系统**）里读到宿主文件。
    // 本条用例把它**记录下来**，避免将来有人以为"git 已完全隔离"。
    const result = await tool.execute(
      { action: "diff", args: ["--no-index", "/etc/passwd", "/dev/null"] },
      context
    );
    assert.equal(result.ok, true, "当前实现会放行 —— 这是登记的事实，不是期望的行为");
    assert.equal(sandbox.execs.length, 1, "它确实下到了沙箱（沙箱只限定 cwd）");
  } finally {
    ws.cleanup();
  }
});

test("E-2 · clone 无 white list ⇒ DENIED（出网闸先于沙箱）", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("git");
    const { context, sandbox } = toolContext(ws.root);

    const result = await tool.execute({ action: "clone", args: ["https://example.com/r.git"] }, context);
    assert.equal(result.ok, false);
    assert.equal(result.errorCode, "PERMISSION_DENIED");
    assert.equal(sandbox.execs.length, 0, "出网被拒时不得下沙箱");
  } finally {
    ws.cleanup();
  }
});

test("E-3 · 未知 action ⇒ VALIDATION_ERROR", async () => {
  const ws = makeWorkspace();
  try {
    const tool = BUILTIN_REGISTRY.get("git");
    const { context } = toolContext(ws.root);
    const result = await tool.execute({ action: "clean", args: ["-fdx"] }, context);
    assert.equal(result.errorCode, "VALIDATION_ERROR");
  } finally {
    ws.cleanup();
  }
});
