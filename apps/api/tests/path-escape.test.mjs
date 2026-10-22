/**
 * T3-10 · 路径逃逸防护证明（DoD#2 的路径面）。
 *
 * 判据（卡面验收 ③「路径逃逸全绿」）
 * ------------------------------
 *   - `..` 穿越；
 *   - 绝对路径；
 *   - **符号链接**（最易漏：`path.resolve` 不展开链接，必须先 `realpath`）；
 *   - scope glob 越界（`dir/**` 之外的文件）；
 *   - 正常路径通过（否则防护就变成「全拒」）。
 *
 * 符号链接用例在 Windows 上用 `junction`（目录联接），不需要管理员特权；
 * POSIX 用普通 symlink。若平台仍建不出来（极少见），用例会**跳过并标记**，
 * 而不是静默通过 —— 跳过是显式的。
 *
 * 复跑：`cd apps/api && npx tsc -b && node --experimental-sqlite --test tests/path-escape.test.mjs`
 */

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  PathGuardError,
  isWithin,
  matchScope,
  resolveWithinWorkspace,
  validateScopePaths,
} from "../dist/modules/tool/guards/path-escape.js";

/** 建一个临时 workspace + 一个"外部"目录。 */
function makeLayout() {
  const base = mkdtempSync(join(tmpdir(), "wb-t10-"));
  const root = join(base, "ws");
  const outside = join(base, "outside");
  mkdirSync(root, { recursive: true });
  mkdirSync(join(root, "src"), { recursive: true });
  mkdirSync(join(root, "tests"), { recursive: true });
  mkdirSync(outside, { recursive: true });
  writeFileSync(join(root, "src", "a.txt"), "hello");
  writeFileSync(join(root, "tests", "b.txt"), "test");
  writeFileSync(join(outside, "secret.txt"), "TOP-SECRET");
  return { base, root, outside, cleanup: () => rmSync(base, { recursive: true, force: true }) };
}

/** 断言抛 `PathGuardError` 且 code 匹配。 */
function assertGuard(fn, code, pattern) {
  assert.throws(fn, (error) => {
    assert.ok(error instanceof PathGuardError, `必须是 PathGuardError，实测 ${String(error)}`);
    assert.equal(error.code, code, `code 应为 ${code}`);
    if (pattern !== undefined) assert.match(error.message, pattern);
    return true;
  });
}

// ---------------------------------------------------------------------------
// A 组 · 四种越界形态
// ---------------------------------------------------------------------------

test("A-1 · `..` 穿越 ⇒ PERMISSION_DENIED", () => {
  const layout = makeLayout();
  try {
    assertGuard(
      () => resolveWithinWorkspace("../outside/secret.txt", { root: layout.root }),
      "PERMISSION_DENIED",
      /越出 Workspace/
    );
    assertGuard(
      () => resolveWithinWorkspace("src/../../outside/secret.txt", { root: layout.root }),
      "PERMISSION_DENIED"
    );
  } finally {
    layout.cleanup();
  }
});

test("A-2 · 绝对路径越界 ⇒ PERMISSION_DENIED", () => {
  const layout = makeLayout();
  try {
    assertGuard(
      () => resolveWithinWorkspace(join(layout.outside, "secret.txt"), { root: layout.root }),
      "PERMISSION_DENIED"
    );
    assertGuard(() => resolveWithinWorkspace("/etc/passwd", { root: layout.root }), "PERMISSION_DENIED");
  } finally {
    layout.cleanup();
  }
});

test("A-3 · **符号链接**越界 ⇒ PERMISSION_DENIED（`resolve` 不展开链接，必须先 realpath）", (t) => {
  const layout = makeLayout();
  try {
    const link = join(layout.root, "escape");
    try {
      symlinkSync(layout.outside, link, process.platform === "win32" ? "junction" : "dir");
    } catch (error) {
      // 显式跳过（不是静默通过）
      t.skip(`本平台无法创建符号链接：${error instanceof Error ? error.message : String(error)}`);
      return;
    }

    // `ws/escape/secret.txt` 从字符串看"在 workspace 内"，但链接指向外部。
    assertGuard(
      () => resolveWithinWorkspace("escape/secret.txt", { root: layout.root }),
      "PERMISSION_DENIED",
      /越出 Workspace/
    );
  } finally {
    layout.cleanup();
  }
});

test("A-4 · scope glob 越界 ⇒ PERMISSION_DENIED", () => {
  const layout = makeLayout();
  try {
    // scope 只允许 src/** ⇒ tests/b.txt 必须被拒
    assertGuard(
      () =>
        resolveWithinWorkspace("tests/b.txt", {
          root: layout.root,
          allowedPaths: ["src/**"],
        }),
      "PERMISSION_DENIED",
      /permission_scope/
    );
    // src 下允许
    const resolved = resolveWithinWorkspace("src/a.txt", {
      root: layout.root,
      allowedPaths: ["src/**"],
    });
    assert.equal(resolved.endsWith("a.txt"), true);
  } finally {
    layout.cleanup();
  }
});

// ---------------------------------------------------------------------------
// B 组 · 正常路径（否则防护 = 全拒）
// ---------------------------------------------------------------------------

test("B-1 · 相对 / 绝对（在根内）都能解析；`mustExist` 生效", () => {
  const layout = makeLayout();
  try {
    const fromRelative = resolveWithinWorkspace("src/a.txt", { root: layout.root, mustExist: true });
    const fromAbsolute = resolveWithinWorkspace(join(layout.root, "src", "a.txt"), {
      root: layout.root,
      mustExist: true,
    });
    assert.equal(fromRelative, fromAbsolute, "两种写法必须解析到同一路径");

    assertGuard(
      () => resolveWithinWorkspace("src/missing.txt", { root: layout.root, mustExist: true }),
      "VALIDATION_ERROR",
      /目标不存在/
    );
    // 写场景：不要求存在 ⇒ 不抛
    const newFile = resolveWithinWorkspace("src/new.txt", { root: layout.root });
    assert.equal(newFile.endsWith("new.txt"), true);
  } finally {
    layout.cleanup();
  }
});

test("B-2 · 根目录本身 ⇒ 通过（`relative === \"\"` 的边界）", () => {
  const layout = makeLayout();
  try {
    const resolved = resolveWithinWorkspace(".", { root: layout.root, mustExist: true });
    assert.equal(isWithin(layout.root, resolved), true);
  } finally {
    layout.cleanup();
  }
});

test("B-3 · `isWithin` 不用字符串前缀（`/ws-evil` 不算 `/ws` 的子路径）", () => {
  assert.equal(isWithin("/ws", "/ws-evil/x"), false, "前缀相同但不是子路径");
  assert.equal(isWithin("/ws", "/ws/a/b"), true);
  assert.equal(isWithin("/ws", "/ws"), true);
  assert.equal(isWithin("/ws", "/ws/../etc"), false);
});

// ---------------------------------------------------------------------------
// C 组 · scope 匹配与声明校验
// ---------------------------------------------------------------------------

test("C-1 · matchScope 三种写法", () => {
  assert.equal(matchScope("src/a.txt", ["src"]), true, "目录写法覆盖其下全部");
  assert.equal(matchScope("src/a.txt", ["src/**"]), true);
  assert.equal(matchScope("src/deep/a.txt", ["src/**"]), true);
  assert.equal(matchScope("srcx/a.txt", ["src"]), false, "不得前缀误伤");
  assert.equal(matchScope("src/a.txt", ["*.txt"]), false, "glob 的 `*` 不跨 `/`");
  assert.equal(matchScope("a.txt", ["*.txt"]), true);
  assert.equal(matchScope("tests/b.txt", ["src/**"]), false);
});

test("C-2 · validateScopePaths：`..` 与绝对越界 ⇒ VALIDATION_ERROR", () => {
  const layout = makeLayout();
  try {
    assertGuard(() => validateScopePaths(["../etc"]), "VALIDATION_ERROR", /穿越/);
    assertGuard(() => validateScopePaths(["src/../../x"]), "VALIDATION_ERROR", /穿越/);
    assertGuard(() => validateScopePaths(["/etc/passwd"]), "VALIDATION_ERROR", /绝对路径/);
    assertGuard(
      () => validateScopePaths([join(layout.outside, "x")], layout.root),
      "VALIDATION_ERROR",
      /越出 Workspace/
    );
    // 合法声明不抛
    validateScopePaths(["src", "tests/**"], layout.root);
    validateScopePaths([join(layout.root, "src")], layout.root);
  } finally {
    layout.cleanup();
  }
});
