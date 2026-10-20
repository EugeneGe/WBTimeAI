import { Check, CornerUpRight, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";

/** 专家选项（复用既有 Agent 只读数据）。 */
export interface ExpertOption {
  id: string;
  name: string;
}

/** 专家位属性（受控开合，便于 ＋菜单「专家」项触发）。 */
export interface ExpertChipProps {
  experts: ExpertOption[];
  /** 当前选中专家 id（`null` = 专家位留空）。 */
  value: string | null;
  onChange: (id: string | null) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  loading?: boolean;
}

/** 由名称取首字（头像字）。 */
function initial(name: string): string {
  return name.trim().slice(0, 1) || "专";
}

/**
 * 专家位（D-UI 体验优化波 · WS-C / DU-6）。
 *
 * - 默认留空（仅渲染锚点）；经 ＋菜单「专家」项或点击已选 chip 打开搜索面板；
 * - 选中后显示专家 chip（头像字 + 名称 + 清除）；
 * - 面板含搜索框 + 专家列表（选中打勾）+「召唤更多专家」入口（UI 态）；
 * - 开合/外部点击/Esc 由 `ui/popover`（radix，§4.3 补遗冻结原语）内建。
 */
export function ExpertChip({
  experts,
  value,
  onChange,
  open,
  onOpenChange,
  loading = false,
}: ExpertChipProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");

  // 面板关闭时清空搜索词（下次打开回到全量列表）。
  useEffect(() => {
    if (!open) {
      setQuery("");
    }
  }, [open]);

  const selected = experts.find((expert) => expert.id === value) ?? null;
  const keyword = query.trim();
  const filtered = keyword ? experts.filter((expert) => expert.name.includes(keyword)) : experts;

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverAnchor asChild>
        {selected ? (
          <span
            data-testid="composer-expert-chip"
            className="flex flex-none items-center gap-1.5 rounded-full border border-border bg-background py-0.5 pl-1 pr-2.5 text-sm text-foreground"
          >
            <span className="flex h-4 w-4 flex-none items-center justify-center rounded-md bg-primary text-xs text-primary-foreground">
              {initial(selected.name)}
            </span>
            <button
              type="button"
              className="max-w-[120px] truncate"
              aria-label={`专家 ${selected.name}`}
              onClick={() => onOpenChange(!open)}
            >
              {selected.name}
            </button>
            <button
              type="button"
              data-testid="composer-expert-clear"
              aria-label="清除专家"
              className="text-muted-foreground hover:text-foreground"
              onClick={() => onChange(null)}
            >
              ×
            </button>
          </span>
        ) : (
          <span data-testid="composer-expert-slot" aria-hidden className="block h-6 w-6" />
        )}
      </PopoverAnchor>

      <PopoverContent
        align="start"
        side="top"
        sideOffset={8}
        data-testid="composer-expert-panel"
        role="dialog"
        aria-label="选择专家"
        className="w-[236px] rounded-2xl border border-border p-1.5 text-sm shadow-md"
        // ＋菜单关闭时会把焦点还给其触发器（面板外），避免误判为「失焦」而立即关闭；
        // 外部点击（pointer）与 Esc 关闭仍由 radix 内建。
        onFocusOutside={(event) => event.preventDefault()}
      >
        <div className="mb-1.5 flex items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-muted-foreground">
          <Search className="h-3.5 w-3.5 flex-none" />
          <input
            data-testid="composer-expert-search"
            className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            placeholder={t("composer.expert.search")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <ul className="max-h-[220px] overflow-auto">
          {filtered.map((expert) => {
            const active = expert.id === value;
            return (
              <li key={expert.id}>
                <button
                  type="button"
                  data-testid={`composer-expert-option-${expert.id}`}
                  aria-pressed={active}
                  onClick={() => {
                    onChange(expert.id);
                    onOpenChange(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left",
                    active ? "bg-accent/30 font-medium text-primary" : "hover:bg-accent/15",
                  )}
                >
                  <span className="flex h-4 w-4 flex-none items-center justify-center rounded-md bg-primary text-xs text-primary-foreground">
                    {initial(expert.name)}
                  </span>
                  <span className="truncate">{expert.name}</span>
                  {active ? <Check className="ml-auto h-3.5 w-3.5 flex-none" /> : null}
                </button>
              </li>
            );
          })}
          {filtered.length === 0 ? (
            <li className="px-2 py-1.5 text-xs text-muted-foreground">
              {loading ? t("composer.expert.loading") : t("composer.expert.empty")}
            </li>
          ) : null}
        </ul>
        <div className="my-1 h-px bg-border" />
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-muted-foreground hover:bg-accent/15"
        >
          <CornerUpRight className="h-3.5 w-3.5" />
          {t("composer.expert.more")}
        </button>
      </PopoverContent>
    </Popover>
  );
}
