import { cn } from "@/lib/cn";

/** 上下文用量环属性。 */
export interface ContextRingProps {
  /** 已用上下文（token 估算值）。 */
  used: number;
  /** 上下文上限（token）。 */
  total: number;
  /** 直径（px，缺省 18）。 */
  size?: number;
  /** 附加类名。 */
  className?: string;
}

/** 圆环几何参数（viewBox 14×14，与设计屏 02 对齐）。 */
const RADIUS = 4.6;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * 上下文用量环（D-UI 体验优化波 · WS-C / DU-6）。
 *
 * 自绘 SVG（**零依赖**，§5 裁定不装 progress 库）：底色环 + 序金进度环。
 * 用量 = 已用 / 上限，钳制到 `[0, 1]`；`aria-label` 暴露百分比（可及性）。
 */
export function ContextRing({ used, total, size = 18, className }: ContextRingProps) {
  const safeTotal = total > 0 ? total : 1;
  const ratio = Math.min(1, Math.max(0, used / safeTotal));
  const dash = CIRCUMFERENCE * ratio;
  const percent = Math.round(ratio * 100);

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      role="img"
      aria-label={`上下文用量 ${percent}%`}
      data-testid="context-ring"
      className={cn("flex-none", className)}
    >
      <circle cx="7" cy="7" r={RADIUS} fill="none" strokeWidth="2.6" className="stroke-border" />
      <circle
        cx="7"
        cy="7"
        r={RADIUS}
        fill="none"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeDasharray={`${dash} ${CIRCUMFERENCE - dash}`}
        transform="rotate(-90 7 7)"
        className="stroke-primary"
      />
    </svg>
  );
}
