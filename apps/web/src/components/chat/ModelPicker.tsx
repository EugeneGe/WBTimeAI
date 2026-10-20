import { Check, Pencil } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";

/** 模型选项（F-14.1：仅展示**图标 + 名称**）。 */
export interface ModelOption {
  id: string;
  name: string;
  /** 模型图标（lucide）；缺省回落到名称首字徽标。 */
  icon?: LucideIcon;
  /** 计费倍率标签（如 `0.6x`）。**保留字段但不再渲染**（§4.5）。 */
  rate?: string;
  /** 徽标（如「默认」「夜间折扣」）。**保留字段但不再渲染**（§4.5）。 */
  badge?: string;
}

/** 模型选择属性。 */
export interface ModelPickerProps {
  models: ModelOption[];
  /** 当前模型 id（`null` = 未选，显示首个已设置模型）。 */
  value: string | null;
  onChange: (id: string) => void;
  /** 「配置自定义模型」入口（F-14.2：跳设置·模型页并自动弹新增表单）。 */
  onConfigure?: () => void;
  loading?: boolean;
}

/**
 * 模型选择（D-UI 体验优化波 · WS-C / DU-6；V0.4.5 B3 · F-14.1 改版）。
 *
 * - 触发器为底部「模型 ⌄」胶囊，展示当前模型名；
 * - 弹出面板：已设置模型列表（**图标 + 名称**，选中打勾）+ 底部「配置自定义模型」入口；
 * - 🔴 **不展示**折率 / 费率（F-14.1，ref24）：`rate` / `badge` 字段保留但**不再渲染**；
 * - 数据经 `useModels` 只读消费（由父 Composer 注入，无数据时以缺省档兜底）；
 * - 开合/外部点击/Esc 由 `ui/popover`（radix，§4.3 补遗冻结原语）内建。
 */
export function ModelPicker({
  models,
  value,
  onChange,
  onConfigure,
  loading = false,
}: ModelPickerProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const selected = models.find((model) => model.id === value) ?? models[0] ?? null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="composer-model-trigger"
          aria-haspopup="listbox"
          aria-expanded={open}
          className="flex flex-none items-center gap-1 rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground"
        >
          <span className="max-w-[140px] truncate">
            {selected ? selected.name : t("composer.model.select")}
          </span>
          <span aria-hidden>⌄</span>
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="end"
        side="top"
        sideOffset={8}
        data-testid="composer-model-panel"
        role="listbox"
        aria-label={t("composer.model.select")}
        className="w-[268px] rounded-2xl border border-border p-1.5 text-sm shadow-md"
      >
        {models.length === 0 ? (
          // V0.4.5 B4 · F-20.2：列表为空 → 空态引导「未配置模型，去设置添加」；
          // V0.4.5 B5 · F-25.9：**去重**——空态内不再渲染「配置自定义模型」按钮，
          // 配置入口统一收敛到底部唯一按钮（`composer-model-configure`）。
          <div data-testid="composer-model-empty" className="px-2 py-3">
            <p className="text-xs text-muted-foreground">
              {loading ? "加载中…" : t("composer.model.emptyGuide")}
            </p>
          </div>
        ) : (
          <ul className="max-h-[240px] overflow-auto">
            {models.map((model) => {
              const active = selected?.id === model.id;
              const ModelIcon = model.icon;
              return (
                <li key={model.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    data-testid={`composer-model-option-${model.id}`}
                    onClick={() => {
                      onChange(model.id);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left",
                      active ? "bg-accent/30 font-medium text-primary" : "hover:bg-accent/15",
                    )}
                  >
                    {/* F-14.1：图标 + 名称（不展示折率 / 费率）。 */}
                    {ModelIcon ? (
                      <ModelIcon className="h-4 w-4 flex-none text-muted-foreground" />
                    ) : (
                      <span className="flex h-4 w-4 flex-none items-center justify-center rounded-md bg-primary text-xs text-primary-foreground">
                        {model.name.slice(0, 1)}
                      </span>
                    )}
                    <span className="truncate">{model.name}</span>
                    {active ? <Check className="ml-auto h-3.5 w-3.5 flex-none" /> : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <div className="my-1 h-px bg-border" />
        <button
          type="button"
          data-testid="composer-model-configure"
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-muted-foreground hover:bg-accent/15"
          onClick={() => {
            onConfigure?.();
            setOpen(false);
          }}
        >
          <Pencil className="h-3.5 w-3.5" />
          {t("composer.model.configure")}
        </button>
      </PopoverContent>
    </Popover>
  );
}
