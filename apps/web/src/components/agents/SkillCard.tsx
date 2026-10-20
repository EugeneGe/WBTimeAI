import { Wrench } from "lucide-react";

import type { SkillListItem } from "@/hooks/useSkills";
import { useTranslation } from "@/i18n";
import { formatRelativeTime } from "@/lib/agentDisplay";
import { cn } from "@/lib/cn";

/** {@link SkillCard} 属性。 */
export interface SkillCardProps {
  /** 技能列表项（`toSkillListItems` 投影）。 */
  item: SkillListItem;
  /** 启用态（**本地态**，由 SkillsTab 的 `enabledMap` 下发；后端无启用字段）。 */
  enabled: boolean;
  /** 切换启用态回调。 */
  onToggle: (item: SkillListItem) => void;
  /** 参照时刻（测试注入固定值，保证相对时间可断言）。 */
  now?: Date;
}

/**
 * 技能卡（V0.4.6 B-15 · 三 Tab 统一改版）。
 *
 * 与 {@link ExpertCard} 同规范：圆角 12 / 1px 描边 / hover 抬升 / 最小高 132。
 * 结构：34px 雾蓝图标块 + 展示名 → 「分类 · 相对时间（created_at）」meta →
 * footer：分类 tag + 启用开关（`role="switch"`，本地态不落库）。
 *
 * 🔴 技能无详情页：**整卡不可点**（不设 `role="link"`，避免死点击）。
 *
 * `data-testid`：`skill-card-<id>` / `agents-skill-toggle-<id>`（沿用）/ `skill-demo-hint-<id>`（沿用，
 * 以 sr-only 附着于开关内，读屏可感知且视觉不与设计冲突）。
 */
export function SkillCard({ item, enabled, onToggle, now }: SkillCardProps) {
  const { t } = useTranslation();
  const categoryLabel = item.category.trim() ? item.category : t("agents.skills.uncategorized");
  const time = formatRelativeTime(item.createdAt, t, now);
  const meta = time === null ? categoryLabel : `${categoryLabel} · ${time}`;

  return (
    <article
      data-testid={`skill-card-${item.id}`}
      className="group flex min-h-[132px] cursor-default flex-col rounded-xl border border-border bg-card p-3 transition-[border-color,box-shadow] duration-150 hover:border-input hover:shadow-[0_5px_16px_rgba(23,50,92,0.09)]"
    >
      {/* 头部：图标块 + 展示名 + 分类/时间 meta */}
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-[10px] bg-[#EAF0F8] text-primary"
        >
          <Wrench className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">{item.displayName}</p>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{meta}</p>
        </div>
      </div>

      {/* footer：分类 tag + 启用开关（本地演示态） */}
      <div className="mt-auto flex items-center gap-2 border-t border-border pt-2">
        <span className="flex-none whitespace-nowrap rounded-full bg-muted px-1.5 py-0.5 text-[10px] leading-4 text-muted-foreground">
          {categoryLabel}
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={item.displayName}
          data-testid={`agents-skill-toggle-${item.id}`}
          onClick={() => onToggle(item)}
          className={cn(
            "relative ml-auto h-5 w-9 flex-none rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            enabled ? "bg-primary" : "bg-muted",
          )}
        >
          <span data-testid={`skill-demo-hint-${item.id}`} className="sr-only">
            {t("agents.skills.localDemo")}
          </span>
          <span
            aria-hidden
            className={cn(
              "absolute top-0.5 h-4 w-4 rounded-full bg-background transition-all",
              enabled ? "left-[18px]" : "left-0.5",
            )}
          />
        </button>
      </div>
    </article>
  );
}
