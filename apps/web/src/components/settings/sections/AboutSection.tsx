import { Sparkles } from "lucide-react";

import { useTranslation } from "@/i18n";
import { useSystemSettings } from "@/hooks/useSettings";

/**
 * 设置 · 关于分区（V0.4.5 B3 · F-11.7，ref21 形态）。
 *
 * 应用名 / 版本 / 版权（B-01：品牌名随语言——`en` `WBTimeAI` / `zh-CN` `观序智能平台`，
 * 统一经 `t("app.name")` 取词）。
 * 文案全部走 `useTranslation()`；版本取自 `useSystemSettings().app_version`（只读）。
 *
 * `data-testid`：`settings-about` / `settings-about-version` / `settings-about-copyright`。
 */
export function AboutSection() {
  const { t } = useTranslation();
  const system = useSystemSettings();
  const version = system.data?.app_version ?? "—";

  return (
    <section
      aria-label={t("settings.about.title")}
      data-testid="settings-about"
      className="space-y-5"
    >
      <h3 className="text-sm font-semibold text-foreground">{t("settings.about.title")}</h3>

      <div className="flex flex-col items-center gap-2 rounded-lg border border-border px-4 py-6 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
          <Sparkles className="h-6 w-6" />
        </span>
        <p className="text-base font-semibold text-foreground">{t("app.name")}</p>
        <p className="text-xs text-muted-foreground">{t("app.tagline")}</p>
        <p data-testid="settings-about-version" className="text-xs text-muted-foreground">
          v{version}
        </p>
      </div>

      <div className="flex items-center justify-between gap-4 rounded-lg border border-border px-4 py-3 text-sm">
        <span className="text-muted-foreground">{t("settings.about.copyright")}</span>
        <span data-testid="settings-about-copyright" className="text-foreground">
          {`© 2026 ${t("app.name")}`}
        </span>
      </div>
    </section>
  );
}
