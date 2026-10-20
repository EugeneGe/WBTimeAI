import { LifeBuoy } from "lucide-react";

import { useTranslation } from "@/i18n";

/**
 * 设置 · 帮助分区（V0.4.5 B3 · F-11.1；7 分区之一）。
 *
 * 本波「帮助」为**最小落地**：仅分区标题 + 占位说明（冻结字典未含帮助正文 key，
 * 见裁定 §8.1 / R1「分批覆盖」）；后续波次接入真实帮助内容 / 文档链接。
 *
 * `data-testid`：`settings-help`。
 */
export function HelpSection() {
  const { t } = useTranslation();

  return (
    <section
      aria-label={t("settings.help.title")}
      data-testid="settings-help"
      className="space-y-5"
    >
      <h3 className="text-sm font-semibold text-foreground">{t("settings.help.title")}</h3>

      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border px-4 py-8 text-center text-muted-foreground">
        <LifeBuoy className="h-6 w-6" />
        <p className="text-sm">{t("common.comingSoon")}</p>
      </div>
    </section>
  );
}
