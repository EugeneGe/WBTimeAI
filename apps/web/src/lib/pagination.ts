// ---------------------------------------------------------------------------
// WBTimeAI · 前端分页工具（V0.4.6 · B-17 复核修正：设备会话分页条页码窗口化）
//
// 目标：任意总页数下分页条数字位恒 ≤ 7（加省略号），页面不出现横向滚动。
// 纯函数、无 React 依赖，可单测。
// ---------------------------------------------------------------------------

/** 页码窗口元素：数字页码或省略号占位。 */
export type PageWindowEntry = number | "ellipsis";

/**
 * 计算页码窗口。
 *
 * 总页数 ≤ 7 → 全量页码；否则只保留「第 1 页 + 当前页 ±1 + 最后一页」，
 * 断口处以 `"ellipsis"` 占位。
 *
 * @param current 当前页（1 起；越界值按集合过滤自然收敛）。
 * @param total 总页数（≥ 1）。
 * @returns 页码窗口（数字位恒 ≤ 7）。
 */
export function pageWindow(current: number, total: number): PageWindowEntry[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }
  const set = new Set<number>(
    [1, total, current - 1, current, current + 1].filter((p) => p >= 1 && p <= total),
  );
  const sorted = [...set].sort((a, b) => a - b);
  const out: PageWindowEntry[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (p - prev > 1) {
      out.push("ellipsis");
    }
    out.push(p);
    prev = p;
  }
  return out;
}
