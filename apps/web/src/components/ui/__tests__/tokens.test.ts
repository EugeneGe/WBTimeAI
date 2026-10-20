// ---------------------------------------------------------------------------
// D-UI 体验优化波 · WS-F · token 快照断言（DU-4）
//
// 断言 `src/index.css` 关键 token 存在且 HSL 合规、旧 shadcn 蓝归零、
// 字体栈/圆角/新增槽位到位。index.css 为全站唯一色值落点。
// ---------------------------------------------------------------------------
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// vitest 以包目录（apps/web）为 cwd 运行，故 index.css 落在 `src/index.css`。
const cssPath = resolve(process.cwd(), "src", "index.css");
const css = readFileSync(cssPath, "utf8");

/** HSL 写值格式：`H S% L%`（H/S/L 允许小数）。 */
const HSL = /^\d+(?:\.\d+)? \d+(?:\.\d+)?% \d+(?:\.\d+)?%$/;

/** 必需要有 HSL 色值的 token。 */
const COLOR_TOKENS = [
  "primary",
  "primary-foreground",
  "accent",
  "ring",
  "background",
  "foreground",
  "muted",
  "muted-foreground",
  "border",
  "input",
  "card",
  "popover",
  "page",
  "success",
  "success-foreground",
  "warning",
  "warning-foreground",
  "destructive",
];

/** 取某 token 的全部出现值（`:root` 与 `.dark` 各一）。 */
function occurrences(name: string): string[] {
  const re = new RegExp(`--${name}:\\s*([^;]+);`, "g");
  const found: string[] = [];
  let match: RegExpExecArray | null = re.exec(css);
  while (match !== null) {
    found.push(match[1].trim());
    match = re.exec(css);
  }
  return found;
}

describe("index.css token（DU-4）", () => {
  it.each(COLOR_TOKENS)("--%s 存在且为 HSL 写值", (name) => {
    const values = occurrences(name);
    expect(values.length).toBeGreaterThanOrEqual(1);
    for (const value of values) {
      expect(value).toMatch(HSL);
    }
  });

  it("亮色主色为墨蓝（216 60% 23%）", () => {
    expect(occurrences("primary")).toContain("216 60% 23%");
  });

  it("暗色主色翻转序金（40 90% 61%）", () => {
    expect(occurrences("primary")).toContain("40 90% 61%");
  });

  it("accent / ring 为序金（40 90% 61%）", () => {
    expect(occurrences("accent")).toContain("40 90% 61%");
    expect(occurrences("ring")).toContain("40 90% 61%");
  });

  it("新增 --page 明暗双值", () => {
    const page = occurrences("page");
    expect(page).toContain("220 33% 96%");
    expect(page).toContain("222 51% 9%");
  });

  it("新增 --success / --warning 明暗双值", () => {
    expect(occurrences("success")).toContain("150 25% 39%");
    expect(occurrences("success")).toContain("150 24% 49%");
    expect(occurrences("warning")).toContain("38 75% 51%");
    expect(occurrences("warning")).toContain("40 90% 61%");
  });

  it("补两槽：--success-foreground / --warning-foreground", () => {
    expect(occurrences("success-foreground")).toContain("0 0% 100%");
    // 暗色 warning-foreground 用深字（金底对比度）。
    expect(occurrences("warning-foreground")).toContain("216 60% 23%");
  });

  it("圆角基值为控件 8px", () => {
    expect(css).toMatch(/--radius:\s*8px;/);
  });

  it("字体栈为 Segoe UI Variable → 微软雅黑 → system-ui", () => {
    expect(css).toContain('"Segoe UI Variable Text"');
    expect(css).toContain('"Microsoft YaHei"');
  });

  it("旧 shadcn 蓝残留归零", () => {
    expect(css).not.toContain("221.2 83.2% 53.3%");
    expect(css).not.toContain("217.2 91.2% 59.8%");
  });

  it("最外层底色走 --page", () => {
    expect(css).toMatch(/@apply bg-page text-foreground;/);
  });
});
