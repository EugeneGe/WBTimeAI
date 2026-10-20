import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * 业务内联空态（V0.4.6 · B-22 / B-23，**冻结签名**）。
 *
 * 与聊天招呼语组件 {@link import("./EmptyState").EmptyState} 严格区分：
 * - `EmptyState` = 品牌标（40px 方块 + 序金点）+ 招呼语 + 场景 chips，**仅对话入口**使用；
 * - `InlineEmpty` = 卡内业务空态：34×34 图标底 + 13px 标题 + 11px 说明（**最多 2 行**）+ 可选动作。
 *
 * 🔴 **不引入聊天 chips**；动作只放**一个**（次级按钮或文字链），避免卡内出现多个主 CTA。
 */
export interface InlineEmptyProps {
  /** 图标组件（`lucide-react` 组件本身，非节点）。 */
  icon: LucideIcon;
  /** 标题（13px，中等字重）。 */
  title: string;
  /** 说明（11px，最多 2 行；缺省不渲染）。 */
  description?: string;
  /** 动作区（一个次级按钮或文字链；缺省不渲染）。 */
  action?: ReactNode;
  /** 附加类名（与默认内边距合并）。 */
  className?: string;
  /** 容器 testid（供用例断言具体空态）。 */
  testId?: string;
}

/**
 * 渲染业务内联空态。
 *
 * @param props 见 {@link InlineEmptyProps}。
 * @returns 垂直居中、居中文本的紧凑空态块。
 */
export function InlineEmpty({
  icon: Icon,
  title,
  description,
  action,
  className,
  testId,
}: InlineEmptyProps) {
  return (
    <div
      data-testid={testId}
      className={cn("flex flex-col items-center gap-1 py-6 text-center", className)}
    >
      <div
        aria-hidden
        className="mb-1 flex h-[34px] w-[34px] items-center justify-center rounded-[10px] bg-secondary text-primary"
      >
        <Icon className="h-[17px] w-[17px]" />
      </div>
      <p className="text-[13px] font-medium text-foreground">{title}</p>
      {description ? (
        <p className="line-clamp-2 max-w-[280px] text-[11px] leading-[1.5] text-muted-foreground">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-1.5">{action}</div> : null}
    </div>
  );
}
