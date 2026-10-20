import { Lock, Monitor, Moon, Sun } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/uiStore";
import type { Appearance } from "@/stores/uiStore";

/**
 * 设置 · 外观分区（V0.4.5 B3 · F-11.4，Q4=A 卡片式）。
 *
 * - **真实可切**：`浅色 / 深色 / 跟随系统`（复用 `uiStore.appearance` + `setAppearance`）；
 * - **占位卡**：其余主题位统一展示「敬请期待」（`settings.appearance.comingSoon`），
 *   **不新增主题资源 / 不新增色值**（§8.3，仅用既有语义 token）。
 *
 * `data-testid`：`settings-appearance-card-<theme>`（真实三项）/
 * `settings-appearance-card-coming-soon-<n>`（占位）。
 */

/** 真实可切主题（顺序冻结：浅色 / 深色 / 跟随系统）。 */
interface RealTheme {
  value: Appearance;
  labelKey: string;
  icon: LucideIcon;
  /** 缩略预览用语义 token（**禁止 hex**，§8.3）。 */
  previewClassName: string;
}

const REAL_THEMES: readonly RealTheme[] = [
  {
    value: "light",
    labelKey: "settings.appearance.light",
    icon: Sun,
    previewClassName: "border-border bg-background",
  },
  {
    value: "dark",
    labelKey: "settings.appearance.dark",
    icon: Moon,
    previewClassName: "border-border bg-foreground",
  },
  {
    value: "system",
    labelKey: "settings.appearance.system",
    icon: Monitor,
    previewClassName: "border-border bg-gradient-to-br from-background to-foreground",
  },
];

/** 占位主题卡数量（其余主题「敬请期待」）。 */
const PLACEHOLDER_THEME_COUNT = 3;

export function AppearanceSection() {
  const { t } = useTranslation();
  const appearance = useUiStore((state) => state.appearance);
  const setAppearance = useUiStore((state) => state.setAppearance);

  // F-26（V0.4.5 B5）：「正在使用」大预览卡取当前 appearance 的 previewClassName 放大版。
  const current = REAL_THEMES.find((item) => item.value === appearance) ?? REAL_THEMES[2];

  return (
    <section
      aria-label={t("settings.appearance.title")}
      data-testid="settings-appearance"
      className="space-y-4"
    >
      <h3 className="text-sm font-semibold text-foreground">{t("settings.appearance.title")}</h3>

      {/* F-26：正在使用 · 当前主题大预览卡（右上「正在使用」徽标）。 */}
      <div
        data-testid="settings-appearance-current"
        className={cn(
          "relative flex h-28 w-full items-center justify-center rounded-xl border",
          current.previewClassName,
        )}
      >
        <current.icon
          className={cn(
            "h-8 w-8",
            current.value === "dark" ? "text-background" : "text-foreground",
          )}
        />
        <span className="absolute right-2 top-2 rounded-full bg-primary px-2 py-0.5 text-[11px] font-medium text-primary-foreground dark:bg-accent dark:text-primary">
          {t("settings.appearance.current")}
        </span>
        <span
          className={cn(
            "absolute bottom-2 left-3 text-xs font-medium",
            current.value === "dark" ? "text-background" : "text-foreground",
          )}
        >
          {t(current.labelKey)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {REAL_THEMES.map((item) => {
          const active = appearance === item.value;
          return (
            <button
              key={item.value}
              type="button"
              data-testid={`settings-appearance-card-${item.value}`}
              aria-pressed={active}
              onClick={() => setAppearance(item.value)}
              className={cn(
                "group flex flex-col gap-2 rounded-xl border p-2 text-left transition-colors",
                active
                  ? "border-primary ring-1 ring-primary"
                  : "border-border hover:border-foreground/30",
              )}
            >
              <span
                className={cn(
                  "flex h-16 w-full items-center justify-center rounded-lg border",
                  item.previewClassName,
                )}
              >
                <item.icon
                  className={cn(
                    "h-5 w-5",
                    item.value === "dark" ? "text-background" : "text-foreground",
                  )}
                />
              </span>
              <span
                className={cn("text-xs font-medium", active ? "text-primary" : "text-foreground")}
              >
                {t(item.labelKey)}
              </span>
            </button>
          );
        })}

        {Array.from({ length: PLACEHOLDER_THEME_COUNT }).map((_, index) => (
          <div
            key={`coming-soon-${index}`}
            data-testid={`settings-appearance-card-coming-soon-${index}`}
            aria-disabled="true"
            className="flex flex-col gap-2 rounded-xl border border-dashed border-border p-2 opacity-70"
          >
            <span className="flex h-16 w-full items-center justify-center rounded-lg bg-muted">
              <Lock className="h-4 w-4 text-muted-foreground" />
            </span>
            <span className="text-xs text-muted-foreground">
              {t("settings.appearance.comingSoon")}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
