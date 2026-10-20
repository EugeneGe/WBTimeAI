import { cn } from "@/lib/cn";

/**
 * KB 状态徽标（V0.4.6 · D-UI 优化波 · B-16）。
 *
 * 内联 `span` 模式（**不改** `ui/badge` 原语，对齐 `AgentStatusBadge`）：
 * `status` 枚举值**原样**展示：READY / ACTIVE 系绿；PARSING / INDEXING 系金；其余灰系。
 */
const KB_STATUS_CLASS: Readonly<Record<string, string>> = {
  READY: "border-[#C9DFD2] bg-[#F0F7F3] text-[#4A7C63]",
  ACTIVE: "border-[#C9DFD2] bg-[#F0F7F3] text-[#4A7C63]",
  PARSING: "border-[#EBD9AC] bg-[#FDF6E6] text-[#8A6322]",
  INDEXING: "border-[#EBD9AC] bg-[#FDF6E6] text-[#8A6322]",
};

/** {@link KbStatusBadge} 属性。 */
export interface KbStatusBadgeProps {
  /** 后端状态枚举值（原样展示；空值回落 `—`）。 */
  status: string | null | undefined;
}

/** 知识库 / 文档状态徽标（绿 = READY、金 = PARSING、灰 = 其他）。 */
export function KbStatusBadge({ status }: KbStatusBadgeProps) {
  const label = status ?? "—";
  return (
    <span
      aria-label={label}
      className={cn(
        "flex-none whitespace-nowrap rounded-full border px-1.5 py-px text-[10px] font-medium leading-4",
        KB_STATUS_CLASS[label] ?? "border-border bg-muted text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}
