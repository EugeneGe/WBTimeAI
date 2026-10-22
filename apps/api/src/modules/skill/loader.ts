/**
 * T3-06 · Skill 包装载（py oracle：`wbtime_ai_skill/loader.py` + `manifest.load_skill_package` 逐条对齐）。
 *
 * 职责（与 py 同口径）
 * ------------------
 * 从**包目录**装载一个 Skill：`skill.yaml` + 指令正文 + 资源清单（`LoadedSkill`）。
 * 目录缺失 / `skill.yaml` 缺失或非法 ⇒ 422 `VALIDATION_ERROR`；`instructions` 文件
 * 缺失 ⇒ **宽松落空串**（py 同口径：`if instructions_path.is_file() else ""`）——
 * 缺指令文件不挡装载，缺清单才挡。
 *
 * 边界（R3-21，py 没有显式做、TS 双层防护）：
 *   1. 清单内的路径形字段在 {@link ./manifest} 解析期已过 `validateRelPath`（`..` /
 *      绝对路径 / 反斜杠 ⇒ 422）；
 *   2. 装载期**再次**做 `path.resolve` 前缀包含检查（纵深防御：就算校验被绕过，
 *      读文件也出不了包根）；扫描出的每个资源相对路径同样过 {@link validateRelPath}。
 *
 * 确定性：目录扫描**逐层排序**（py `sorted(root.rglob("*"))` 同款），`fingerprint`
 * 对 manifest + instructions + 资源清单做规范 JSON sha256 —— 同一包两次装载全等
 * （验收 ③ 的装载面判据）。
 *
 * 零 Web / 零 ORM：只依赖 `node:fs` / `node:path` + 本目录 {@link ./manifest}。
 * **不做 Skill 执行**（范围红线：Skill 是提示词/资源包，非工具；`scripts/` 只是被
 * 列举为资源，本版无任何执行入口）。
 *
 * 错误载体：与 manifest.ts 同一出口（`authError` → 422 `VALIDATION_ERROR`，状态由
 * 契约错误表派生，不新增契约错误码）。
 */

import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { ERROR_CODES } from "@wbtime/core";

import { authError } from "../auth/errors.js";
import {
  manifestFingerprint,
  parseManifestYaml,
  validateRelPath,
  type SkillManifestData,
} from "./manifest.js";

/** 清单文件名（py `SkillLoader._manifest_filename` 缺省同款）。 */
export const MANIFEST_FILENAME = "skill.yaml";

/** 包内资源规格（py `SkillResourceSpec` 同形：相对路径 + 种类 + 存储键）。 */
export interface SkillResourceSpec {
  /** 包内相对路径（posix 分隔，如 `scripts/run.py`）。 */
  readonly path: string;
  /** 资源种类（`file` / `example` / `script` / `template`）。 */
  readonly kind: string;
  /**
   * Storage 对象键（py：`skills/{skill_id}/{version}/{path}`；装载期尚不知
   * `skill_id` ⇒ 恒 `null`，发布时补齐 —— 本版发布流不写资源存储，登记遗留）。
   */
  readonly storage_key: null;
}

/** 装载结果（py `LoadedSkill` 同形 + TS 侧确定性指纹）。 */
export interface LoadedSkill {
  readonly manifest: SkillManifestData;
  /** 指令正文（`instructions` 路径缺文件 ⇒ `""`，py 同口径）。 */
  readonly instructions: string;
  /** 来源（`builtin` / `plugin` / `workspace`；py 同款字符串而非枚举）。 */
  readonly source: string;
  /** 包根目录（绝对路径字符串）。 */
  readonly root: string;
  /** 资源清单（examples → resources → scripts 顺序，目录内逐层排序）。 */
  readonly resources: readonly SkillResourceSpec[];
  /** 确定性指纹：manifest + instructions + 资源清单的规范 JSON sha256。 */
  readonly fingerprint: string;
}

/** 装载选项。 */
export interface LoadSkillOptions {
  /** 来源标记；缺省 `builtin`（py 同款）。 */
  readonly source?: string;
}

/** 装载期 422（与 manifest 解析同一错误出口：`VALIDATION_ERROR`，不新增契约错误码）。 */
function packageError(message: string, data: Record<string, unknown> = {}): Error {
  return authError(ERROR_CODES.VALIDATION_ERROR, message, data);
}

/**
 * 读文件（不存在 / 是目录 ⇒ `null`）。
 *
 * 为什么不用 `readFileSync` 直接抛：调用方要的是 py 的"缺文件宽松落空串"语义，
 * 这里把存在性判断收在一处，调用方不再各写一遍 `is_file()`。
 */
function readFileOrNull(path: string): string | null {
  if (!existsSync(path) || !statSync(path).isFile()) return null;
  return readFileSync(path, "utf8");
}

/**
 * 解析后的路径必须仍在包根内（纵深防御第 2 层）。
 *
 * `validateRelPath` 已挡住 `..` / 绝对路径，这里是"就算未来有人在 manifest.ts 之外
 * 造出绕过校验的路径，读盘也出不了包根"的最后闸。`resolve` 消解全部 `..`/`.` 段后
 * 做前缀包含判断（`sep` 后缀防 `pkg-evil` 前缀误判）。
 *
 * @returns 包根内的绝对路径。
 * @throws {Error} 越界（编程错误级 —— 正常流到不了这里）。
 */
function assertWithinRoot(root: string, ...segments: readonly string[]): string {
  const target = resolve(root, ...segments);
  const rootWithSep = root.endsWith(sep) ? root : root + sep;
  if (target !== root && !target.startsWith(rootWithSep)) {
    throw new Error(`路径越界（包根包含检查失败）：${target} ∉ ${root}`);
  }
  return target;
}

/**
 * 递归扫一个资源目录（py `_scan_directory` 同语义：只收**文件**，逐层排序）。
 *
 * @param pkgRoot 包根（绝对路径）。
 * @param dirName 目录名（已经过 `validateRelPath`，单段或 `a/b` 形）。
 * @param kind 资源种类。
 * @returns 资源规格（相对路径**含目录前缀** —— py `relative_to(root.parent)` 同口径：
 *          扫描根是 `pkgRoot/dirName`，但相对路径从包根起算，如 `examples/foo.md`）。
 */
function scanDirectory(pkgRoot: string, dirName: string, kind: string): SkillResourceSpec[] {
  const scanRoot = assertWithinRoot(pkgRoot, ...dirName.split("/"));
  if (!existsSync(scanRoot) || !statSync(scanRoot).isDirectory()) return [];

  const specs: SkillResourceSpec[] = [];
  const walk = (current: string): void => {
    // readdirSync 排序 = py `sorted(rglob("*"))` 的确定性前提（同包两次扫描同序）。
    for (const name of readdirSync(current).sort()) {
      const full = join(current, name);
      const stat = statSync(full);
      if (stat.isDirectory()) {
        walk(full);
        continue;
      }
      if (!stat.isFile()) continue; // 符号链接等非常规项：跳过，不当资源
      // 相对路径从包根起算，posix 分隔（Windows 下 `relative` 给 `\\`，统一翻转）。
      const rel = relative(pkgRoot, full).split(sep).join("/");
      // 资源路径同样过边界校验（纵深第 3 层：扫描结果再验一次）。
      validateRelPath("resources[].path", rel);
      specs.push({ path: rel, kind, storage_key: null });
    }
  };
  walk(scanRoot);
  return specs;
}

/**
 * 从包目录装载一个 Skill（py `load_skill_package` 同名同语义）。
 *
 * @param directory Skill 包根目录。
 * @param options 装载选项（来源标记）。
 * @returns 装载结果（manifest + 指令正文 + 资源清单 + 指纹）。
 * @throws {HttpException} 目录不存在 / `skill.yaml` 缺失或非法 ⇒ 422 `VALIDATION_ERROR`。
 */
export function loadSkillPackage(directory: string, options: LoadSkillOptions = {}): LoadedSkill {
  const source = options.source ?? "builtin";
  if (typeof directory !== "string" || directory.trim() === "") {
    throw packageError("Skill 包目录不存在", { path: String(directory) });
  }
  const root = resolve(directory);
  if (!existsSync(root) || !statSync(root).isDirectory()) {
    throw packageError("Skill 包目录不存在", { path: root });
  }

  const manifestPath = assertWithinRoot(root, MANIFEST_FILENAME);
  const yamlText = readFileOrNull(manifestPath);
  if (yamlText === null) {
    throw packageError("skill.yaml 不存在", { path: manifestPath });
  }
  // 非法 YAML / 必填键缺失 / 版本非法 / 路径越界都在解析期死（422）。
  const manifest = parseManifestYaml(yamlText);

  // 指令正文：缺文件宽松落空串（py 同口径；路径已在解析期过边界校验）。
  const instructionsPath = assertWithinRoot(root, ...manifest.instructions.split("/"));
  const instructions = readFileOrNull(instructionsPath) ?? "";

  // 资源清单：examples → resources → scripts（py 的 extend 顺序同款）。
  const resources: SkillResourceSpec[] = [
    ...scanDirectory(root, manifest.examples, "example"),
    ...scanDirectory(root, manifest.resources, "file"),
    ...scanDirectory(root, manifest.scripts, "script"),
  ];

  // 指纹输入取一份普通对象（readonly 数组在 JSON.stringify 下无差别；
  // manifestFingerprint 内部做键排序规范化 —— 键序不同的同内容输入同 sha）。
  const fingerprintInput = {
    manifest: {
      ...manifest,
      dependencies: [...manifest.dependencies],
      requires: [...manifest.requires],
    },
    instructions,
    source,
    resources,
  };
  return {
    manifest,
    instructions,
    source,
    root,
    resources,
    fingerprint: manifestFingerprint(fingerprintInput),
  };
}
