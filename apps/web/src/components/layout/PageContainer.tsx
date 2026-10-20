import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * 页面容器档位（D-UI 体验优化波 · WS-L / DU-1）。
 *
 * 逐页按 `01-UI基线清单.md §三` 的「档」列声明宽度：
 * - `default` = 1152px（常规单列页）
 * - `content` = 1280px（信息密度更高的列表 / 卡片页，如「专家与智能体」/「工作区」）
 * - `wide`    = 1600px（宽表 / 三栏 Studio / 编辑器）
 * - `full`    = 全宽（Workflow 画布）
 *
 * `content` 为 V0.4.6 新增档（D5）：**专家页（`/agents`）与工作区页（`/workspace`）**使用，
 * 其余页档位不变。
 */
export type PageContainerWidth = "default" | "content" | "wide" | "full";

const WIDTH_CLASS: Record<PageContainerWidth, string> = {
  default: "max-w-[1152px]",
  content: "max-w-[1280px]",
  wide: "max-w-[1600px]",
  full: "w-full max-w-none",
};

/** {@link PageContainer} 属性。 */
export interface PageContainerProps {
  /** 宽度档位（默认 `default`）。 */
  width?: PageContainerWidth;
  /** 追加类名（与档位类合并，后者可覆盖前者）。 */
  className?: string;
  /** 页面内容。 */
  children: ReactNode;
}

/**
 * 档位容器：统一为页面提供水平居中 + 内边距 + 三档最大宽度。
 *
 * 冻结签名（施工记录 `00-开工前架构裁定.md §4.4`）：
 * `{ width?: "default" | "wide" | "full"; className?: string; children: ReactNode }`。
 */
export function PageContainer({ width = "default", className, children }: PageContainerProps) {
  return (
    <div className={cn("mx-auto w-full px-4 py-6", WIDTH_CLASS[width], className)}>{children}</div>
  );
}
