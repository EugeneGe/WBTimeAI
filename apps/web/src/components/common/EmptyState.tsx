import type { ReactNode } from "react";

import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";

/** EmptyState 属性（§4.4 冻结签名）。 */
export interface EmptyStateProps {
  /** 招呼语 / 标题（缺省为品牌招呼语，走 i18n `chat.greeting.title`）。 */
  title?: string;
  /** 副文案（缺省为引导语，走 i18n `chat.greeting.description`）。 */
  description?: string;
  /** 场景 chips 文案（点击回调经 `onChip`；缺省走 i18n `chat.greeting.chip.*`）。 */
  chips?: string[];
  /** chip 点击回调。 */
  onChip?: (chip: string) => void;
  /** 主 CTA（可传入按钮节点）。 */
  cta?: ReactNode;
  /** 附加类名。 */
  className?: string;
}

/**
 * 空态（D-UI 体验优化波 · WS-C / DU-6，§4.4 冻结签名）。
 *
 * 品牌标（墨蓝方块 + 序金点）+ 招呼语 + 场景 chips + 主 CTA；
 * 供 Chat 及 Wave II 页面复用（标题/描述/chips/CTA 均可定制）。
 *
 * **B-01（V0.4.6 BugFix）**：缺省文案不再硬编码中文，改由 i18n 取词——
 * - 标题 `chat.greeting.title`（插值 `{app}` = `t("app.name")`，即品牌名随语言：
 *   en `WBTimeAI` / zh-CN `观序智能平台`）；
 * - 描述 `chat.greeting.description`、chips `chat.greeting.chip.1..3`。
 *
 * 显式传入 `title` / `description` / `chips` 时**以 props 优先**（既有签名与调用方不变）。
 */
export function EmptyState({ title, description, chips, onChip, cta, className }: EmptyStateProps) {
  const { t } = useTranslation();

  // props 优先（`??` 而非 `||`：显式传空串 / 空数组视为调用方意图，保持原语义）。
  const resolvedTitle = title ?? t("chat.greeting.title", { app: t("app.name") });
  const resolvedDescription = description ?? t("chat.greeting.description");
  const scenes = chips ?? [
    t("chat.greeting.chip.1"),
    t("chat.greeting.chip.2"),
    t("chat.greeting.chip.3"),
  ];

  return (
    <div
      data-testid="empty-state"
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-4 py-10 text-center",
        className,
      )}
    >
      {/* 品牌标：墨蓝方块 + 三序金点（设计 §06 / §04）。 */}
      <div
        aria-hidden
        className="mb-1 flex h-10 w-10 items-center justify-center gap-[3px] rounded-xl bg-primary"
      >
        <i className="h-1 w-1 rounded-full bg-accent" />
        <i className="h-1 w-1 rounded-full bg-accent" />
        <i className="h-1 w-1 rounded-full bg-accent" />
      </div>

      <h2 className="text-greeting font-medium text-primary">{resolvedTitle}</h2>
      {resolvedDescription ? (
        <p data-testid="empty-state-description" className="text-sm text-muted-foreground">
          {resolvedDescription}
        </p>
      ) : null}

      {scenes.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2.5">
          {scenes.map((scene) => (
            <button
              key={scene}
              type="button"
              data-testid={`empty-state-chip-${scene}`}
              className="rounded-full border border-border bg-background px-3.5 py-1 text-sm text-primary hover:bg-accent/15"
              onClick={() => onChip?.(scene)}
            >
              {scene}
            </button>
          ))}
        </div>
      ) : null}

      {cta ? <div className="mt-4">{cta}</div> : null}
    </div>
  );
}
