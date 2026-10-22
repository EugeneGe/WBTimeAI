/**
 * T3-10 · 路径逃逸防护（py `wbtime_ai_tool/security.py` 的逐项复刻）。
 *
 * 四种越界形态与各自的拦截点
 * -----------------------
 * | 形态 | 例子 | 拦截点 |
 * |---|---|---|
 * | `..` 穿越 | `../../etc/passwd` | `resolve` 后 `isWithin` |
 * | 绝对路径 | `/etc/passwd` | `resolve` 后 `isWithin` |
 * | **符号链接** | `ws/link → /etc` 再读 `ws/link/passwd` | `realpath` 展开后 `isWithin` |
 * | scope glob 越界 | scope=`src/**` 却读 `tests/x` | `matchScope` |
 *
 * 第四条（符号链接）是**最容易漏**的一条：`path.resolve` **不展开**符号链接，
 * 所以只做 `resolve` 的实现在 `ws/link/passwd` 上会判"在 workspace 内"。
 * 必须先 `realpath`（对存在的路径）再判。本文件用 {@link realpathOrResolve}。
 *
 * 为什么"解析后比较"而不是"字符串前缀比较"
 * -------------------------------------
 *   `/workspace-evil/x` 以 `/workspace` 开头但不是它的子路径。前缀比较会放行。
 *   正确做法是 `path.relative(root, target)` 不以 `..` 开头且不是绝对路径。
 */

import { existsSync, realpathSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

/** 路径校验失败（`PERMISSION_DENIED` / `VALIDATION_ERROR`）。 */
export class PathGuardError extends Error {
  readonly name = "PathGuardError";
  readonly code: "PERMISSION_DENIED" | "VALIDATION_ERROR";
  readonly data: Readonly<Record<string, unknown>>;

  constructor(
    message: string,
    code: "PERMISSION_DENIED" | "VALIDATION_ERROR",
    data: Record<string, unknown> = {}
  ) {
    super(message);
    this.code = code;
    this.data = data;
  }
}

/**
 * 解析路径：存在的走 `realpath`（展开符号链接），不存在的退回 `resolve`。
 *
 * 为什么对不存在的路径退回 `resolve`：工具可能要"写一个新文件"，此时目标还不存在，
 * `realpath` 会抛。退回 `resolve` 后仍然做 `isWithin` 判定 —— 父目录若是个指向外部的
 * 符号链接，`resolve` 展开父目录后同样会被判越界（`resolve` 会解析已存在的祖先链接）。
 */
export function realpathOrResolve(path: string): string {
  try {
    return realpathSync(path);
  } catch {
    return resolve(path);
  }
}

/** `target` 是否在 `root` 之内（两者都已解析）。 */
export function isWithin(root: string, target: string): boolean {
  const rel = relative(root, target);
  if (rel === "") return true; // 就是根本身
  if (rel.startsWith("..")) return false;
  if (isAbsolute(rel)) return false;
  return true;
}

/** scope 白名单匹配入参。 */
export interface ResolveWithinOptions {
  /** Workspace 根（会先 `realpath`）。 */
  readonly root: string;
  /** 可选 scope 白名单（相对路径 / `dir` / `dir/**` / glob）。 */
  readonly allowedPaths?: readonly string[];
  /** 要求目标已存在（读 / 删 时用；写时为 false）。 */
  readonly mustExist?: boolean;
  /** 存在性探针（测试注入；缺省 `fs.existsSync`）。 */
  readonly exists?: (path: string) => boolean;
}

/**
 * 把 `path` 解析为 Workspace 内的绝对路径；任何越界都抛错。
 *
 * @throws {PathGuardError} `PERMISSION_DENIED`（越界 / 不在 scope）/ `VALIDATION_ERROR`
 *   （目标不存在）。
 */
export function resolveWithinWorkspace(path: string, options: ResolveWithinOptions): string {
  const root = realpathOrResolve(options.root);
  const candidate = isAbsolute(path) ? path : resolve(root, path);
  const resolved = realpathOrResolve(candidate);

  if (!isWithin(root, resolved)) {
    throw new PathGuardError("路径越出 Workspace 边界", "PERMISSION_DENIED", {
      path,
      workspace: root,
    });
  }

  if (options.allowedPaths !== undefined && options.allowedPaths.length > 0) {
    const rel = relative(root, resolved).split(sep).join("/");
    const normalized = rel === "." ? "" : rel;
    if (!matchScope(normalized, options.allowedPaths)) {
      throw new PathGuardError("路径不在 permission_scope 允许范围内", "PERMISSION_DENIED", {
        path,
        scope: [...options.allowedPaths],
      });
    }
  }

  if (options.mustExist === true) {
    const exists = options.exists ?? defaultExists;
    if (!exists(resolved)) {
      throw new PathGuardError("目标不存在", "VALIDATION_ERROR", { path });
    }
  }

  return resolved;
}

/** 缺省存在性探针（`existsSync` 不抛错，符合"探测"语义）。 */
function defaultExists(path: string): boolean {
  return existsSync(path);
}

/**
 * 相对路径是否命中 scope 白名单。
 *
 * 三种写法（py `_match_scope` 同口径）：
 *   - `dir` / `dir/**` ⇒ 目录及其下全部；
 *   - 含 `*` / `?` ⇒ shell glob；
 *   - 精确串 ⇒ 该文件或该目录下。
 */
export function matchScope(relativePath: string, patterns: readonly string[]): boolean {
  const target = relativePath.split(sep).join("/");
  for (const raw of patterns) {
    const pattern = String(raw).replace(/\\/g, "/").trim();
    if (pattern === "") continue;

    if (pattern.endsWith("/**")) {
      const prefix = pattern.slice(0, -3).replace(/\/+$/, "");
      if (target === prefix || target.startsWith(`${prefix}/`)) return true;
      continue;
    }
    if (pattern.includes("*") || pattern.includes("?")) {
      if (globToRegExp(pattern).test(target)) return true;
      continue;
    }
    if (target === pattern || target.startsWith(`${pattern}/`)) return true;
  }
  return false;
}

/** 极简 glob（`*` 不跨 `/`，与 fnmatch 同义）。 */
function globToRegExp(pattern: string): RegExp {
  const escaped = pattern
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, "[^/]*")
    .replace(/\?/g, "[^/]");
  return new RegExp(`^${escaped}$`);
}

/**
 * 校验 `permission_scope.paths` 的**声明**（不是用的时候再判）。
 *
 * 两条硬规则（py `validate_scope_paths`）：
 *   - 绝对路径：给了 root 就必须在 root 内；没给 root ⇒ **直接拒绝**（无参照系）；
 *   - 任何形态的 `..` 段 ⇒ 拒绝（声明里写穿越，说明配置本身有问题）。
 *
 * @throws {PathGuardError} `VALIDATION_ERROR`。
 */
export function validateScopePaths(paths: readonly string[] | undefined, root?: string): void {
  const realRoot = root === undefined ? undefined : realpathOrResolve(root);
  for (const raw of paths ?? []) {
    const text = String(raw).trim();
    if (text === "") continue;
    const normalized = text.replace(/\\/g, "/");
    const looksAbsolute = isAbsolute(normalized) || normalized.startsWith("/");

    if (looksAbsolute) {
      if (realRoot === undefined) {
        throw new PathGuardError("permission_scope 不允许绝对路径", "VALIDATION_ERROR", {
          path: text,
        });
      }
      const resolved = realpathOrResolve(normalized);
      if (!isWithin(realRoot, resolved)) {
        throw new PathGuardError("permission_scope 路径越出 Workspace", "VALIDATION_ERROR", {
          path: text,
          workspace: realRoot,
        });
      }
    }

    if (normalized.split("/").includes("..")) {
      throw new PathGuardError("permission_scope 不允许路径穿越 '..'", "VALIDATION_ERROR", {
        path: text,
      });
    }
  }
}
