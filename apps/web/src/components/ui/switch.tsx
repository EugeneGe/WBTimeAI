import * as React from "react";

import { cn } from "@/lib/cn";

/**
 * {@link Switch} 属性（**完全受控**：组件自身不持有状态，`checked` 与 `onCheckedChange` 必须成对使用）。
 */
export interface SwitchProps {
  /** 当前开关状态（`true` = 开）。 */
  checked: boolean;
  /** 状态变更回调（传入**反转后的**目标值）。 */
  onCheckedChange: (checked: boolean) => void;
  /** 禁用态（`opacity-50` + 不可点）。 */
  disabled?: boolean;
  /** 追加类名（与内置尺寸类合并）。 */
  className?: string;
  /** 无障碍名称（纯图标/无文案开关必填，供读屏与 `getByRole("switch")` 定位）。 */
  "aria-label"?: string;
  /** 测试定位标识。 */
  "data-testid"?: string;
}

/**
 * 自绘 Switch（B-20；设计 §一 D7「行内开关 34×19，on=墨蓝」）。
 *
 * - 结构：`<button type="button" role="switch" aria-checked>` + 内部圆点，
 *   因此**原生**支持鼠标点击与 <kbd>Space</kbd> / <kbd>Enter</kbd> 切换；
 * - 尺寸：轨道 `h-[19px] w-[34px]`、圆点 `15px`（描边留白 2px，故 on 位位移 `17px`）；
 * - 配色：on = `bg-primary`（墨蓝）、off = `bg-[#C9D2E0]`（浅灰蓝）；过渡 150ms；
 * - 焦点：`focus-visible:ring-2 ring-ring ring-offset-2`（与全站原语一致）。
 *
 * 🔴 全仓此前无 `ui/switch` 原语（调度「启用」列只能用文本按钮反转文案），
 *    本组件按设计稿补齐，**仅**提供受控形态，不引入 radix 依赖。
 */
export const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  {
    checked,
    onCheckedChange,
    disabled = false,
    className,
    "aria-label": ariaLabel,
    "data-testid": testId,
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      data-testid={testId}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-[19px] w-[34px] flex-none items-center rounded-full transition-colors duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-primary" : "bg-[#C9D2E0]",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "pointer-events-none block h-[15px] w-[15px] rounded-full bg-white shadow-sm transition-transform duration-150",
          checked ? "translate-x-[17px]" : "translate-x-[2px]",
        )}
      />
    </button>
  );
});
