import { PackageSearch, Search, Upload, X } from "lucide-react";
import { useMemo, useState } from "react";

import { SkillCard } from "@/components/agents/SkillCard";
import {
  TabErrorPanel,
  TabHintBar,
  TabNoMatchPanel,
  TabSkeleton,
  TabEmptyPanel,
} from "@/components/agents/TabPanels";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { toSkillListItems, useSkills, type SkillListItem } from "@/hooks/useSkills";
import { useTranslation } from "@/i18n";

/** {@link SkillsTab} 属性。 */
export interface SkillsTabProps {
  /** 「添加技能」弹窗开合（**受控**：状态提升到 `Agents` 宿主，页头主按钮共用）。 */
  addOpen: boolean;
  /** 开合回调。 */
  onAddOpenChange: (open: boolean) => void;
}

/**
 * 技能 Tab（V0.4.6 B-15 · 三 Tab 统一改版；骨架对齐专家 Tab）。
 *
 * 结构：工具栏（全宽搜索 + 分类下拉 + 上传技能 + 已安装计数）→
 * 「用户自定义」组（承载筛选后的全部技能）/「来自市场」组（恒空 → 虚线展示卡）→ 底部说明条。
 * 四态与专家 Tab 同口径：6 卡骨架 / 错误面板 / 真空态（CTA=添加技能）/ 筛选空。
 *
 * - 数据经 `useSkills`（**只读**）投影为 {@link SkillListItem}；
 * - 「启用开关」为**本地 UI 演示态**（不落库，登记遗留；后端 `SkillResponse` 无启用字段）；
 * - 搜索 / 分类筛选**纯前端**（分类选项随数据去重，自由字段不硬编码）。
 *
 * `data-testid`：`agents-search-skills` / `agents-skills-search-clear` /
 * `agents-skills-category-filter` / `agents-skills-upload` / `agents-skills-installed-count` /
 * `agents-skills-group-<custom|market>` / `agents-skills-market-card` / `skill-card-<id>` /
 * `agents-skill-toggle-<id>` / `skill-demo-hint-<id>`（沿用）/ `agents-skills-empty` /
 * `agents-skills-empty-create` / `agents-skills-no-match` / `agents-skills-clear-filters` /
 * `agents-skills-error` / `agents-skills-retry` / `agents-skills-add-dialog` /
 * `agents-skills-upload-dialog`（沿用）。
 */
export function SkillsTab({ addOpen, onAddOpenChange }: SkillsTabProps) {
  const { t } = useTranslation();
  const { data, isLoading, isError, error, refetch } = useSkills();
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  // F-27.3：上传技能弹窗（本地 state；主按钮「添加技能」已提升到宿主）。
  const [uploadOpen, setUploadOpen] = useState(false);
  // 本地启用态（id → enabled；缺省 = 该项默认值；不落库）。
  const [enabledMap, setEnabledMap] = useState<Record<string, boolean>>({});

  /** 全量列表（未筛选；用于「已安装(N)」计数与真空态判定）。 */
  const items = useMemo(() => toSkillListItems(data), [data]);

  /** 分类选项（数据 `category` 去重 + 排序；空字符串分类显示「未分类」且排在末位）。 */
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      set.add(item.category);
    }
    return [...set].sort((left, right) => {
      if (left === "") {
        return 1;
      }
      if (right === "") {
        return -1;
      }
      return left.localeCompare(right, "zh-CN");
    });
  }, [items]);

  /** 搜索 + 分类筛选（纯前端）。 */
  const filtered = useMemo<SkillListItem[]>(() => {
    const keyword = query.trim().toLowerCase();
    let list = items;

    if (keyword) {
      list = list.filter(
        (item) =>
          item.displayName.toLowerCase().includes(keyword) ||
          item.name.toLowerCase().includes(keyword) ||
          item.description.toLowerCase().includes(keyword),
      );
    }
    if (categoryFilter !== "all") {
      list = list.filter((item) => item.category === categoryFilter);
    }
    return list;
  }, [items, query, categoryFilter]);

  const isEnabled = (item: SkillListItem): boolean => enabledMap[item.id] ?? item.enabled;
  const toggle = (item: SkillListItem): void => {
    setEnabledMap((previous) => ({ ...previous, [item.id]: !(previous[item.id] ?? item.enabled) }));
  };

  /** 重置全部筛选（不动上传弹窗）。 */
  const clearFilters = (): void => {
    setQuery("");
    setCategoryFilter("all");
  };

  const isEmpty = !isLoading && !isError && items.length === 0;
  const isNoMatch = !isLoading && !isError && items.length > 0 && filtered.length === 0;
  /** 工具栏仅在「有数据可筛」时渲染（同专家口径，避免假 0 与无效筛选）。 */
  const showToolbar = !isLoading && !isError && items.length > 0;

  return (
    <div className="space-y-3">
      {/* ===== 工具栏 ===== */}
      {showToolbar ? (
        <div className="flex flex-wrap items-center gap-2" data-testid="agents-skills-toolbar">
          {/* 全宽搜索：匹配 display_name + name + description */}
          <div className="relative min-w-[300px] flex-1">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              data-testid="agents-search-skills"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("agents.search.skills")}
              aria-label={t("agents.search.skills")}
              className="h-8 pl-8 pr-8 text-xs"
            />
            {query ? (
              <button
                type="button"
                data-testid="agents-skills-search-clear"
                aria-label={t("agents.search.clear")}
                onClick={() => setQuery("")}
                className="absolute right-2 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X aria-hidden className="h-3 w-3" />
              </button>
            ) : null}
          </div>

          {/* 分类下拉（真实字段 category，选项随数据去重） */}
          <select
            data-testid="agents-skills-category-filter"
            aria-label={t("agents.skills.categoryFilter")}
            value={categoryFilter}
            onChange={(event) => setCategoryFilter(event.target.value)}
            className="h-8 rounded-lg border border-input bg-background px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="all">{t("agents.skills.categoryAll")}</option>
            {categories.map((category) => (
              <option key={category || "uncategorized"} value={category}>
                {category.trim() ? category : t("agents.skills.uncategorized")}
              </option>
            ))}
          </select>

          {/* 右侧：上传技能 + 已安装(N)（N = 全量数，非筛选后） */}
          <div className="ml-auto flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              data-testid="agents-skills-upload"
              onClick={() => setUploadOpen(true)}
              className="h-8 px-2.5 text-xs"
            >
              <Upload aria-hidden className="h-3.5 w-3.5" />
              {t("agents.skills.add.upload")}
            </Button>
            <span
              className="flex-none whitespace-nowrap text-xs text-muted-foreground"
              data-testid="agents-skills-installed-count"
            >
              {t("agents.skills.installedCount", { count: items.length })}
            </span>
          </div>
        </div>
      ) : null}

      {/* ===== 载入 / 错误 / 真空态 ===== */}
      {isLoading ? (
        <TabSkeleton testId="agents-skills-loading" height={132} />
      ) : isError ? (
        <TabErrorPanel
          testId="agents-skills-error"
          retryTestId="agents-skills-retry"
          error={error}
          onRetry={() => {
            void refetch();
          }}
        />
      ) : isEmpty ? (
        <TabEmptyPanel
          testId="agents-skills-empty"
          icon={<PackageSearch aria-hidden className="h-5 w-5" />}
          title={t("agents.skills.emptyTitle")}
          description={t("agents.subtitleSkills")}
          ctaLabel={t("agents.skills.add")}
          ctaTestId="agents-skills-empty-create"
          onCta={() => onAddOpenChange(true)}
        />
      ) : isNoMatch ? (
        <TabNoMatchPanel
          testId="agents-skills-no-match"
          message={t("agents.skills.noMatch")}
          clearTestId="agents-skills-clear-filters"
          onClear={clearFilters}
        />
      ) : (
        <>
          {/* ===== 分组：用户自定义（筛选后全部技能） ===== */}
          <section data-testid="agents-skills-group-custom" className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="text-xs font-semibold text-foreground">
                {t("agents.skills.group.custom")}
              </h2>
              <span className="text-[11px] text-muted-foreground">
                {t("agents.skills.groupCount", { count: filtered.length })}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {filtered.map((item) => (
                <SkillCard key={item.id} item={item} enabled={isEnabled(item)} onToggle={toggle} />
              ))}
            </div>
          </section>

          {/* ===== 分组：来自市场（恒空 → 虚线展示卡，非按钮） ===== */}
          <section data-testid="agents-skills-group-market" className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="text-xs font-semibold text-foreground">
                {t("agents.skills.group.market")}
              </h2>
              <span className="text-[11px] text-muted-foreground">
                {t("agents.skills.marketSubtitle")}
              </span>
            </div>
            <div
              data-testid="agents-skills-market-card"
              className="flex min-h-[132px] cursor-default flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-input bg-muted/20 px-4 py-5 text-center text-muted-foreground"
            >
              <span className="mb-0.5 flex h-7 w-7 items-center justify-center rounded-[9px] border border-dashed border-current">
                <PackageSearch aria-hidden className="h-3.5 w-3.5" />
              </span>
              <b className="text-xs font-medium text-foreground">
                {t("agents.skills.marketCardTitle")}
              </b>
              <span className="text-[11px]">{t("agents.skills.marketCardDesc")}</span>
            </div>
          </section>

          {/* ===== 底部说明条 ===== */}
          <TabHintBar text={t("agents.skills.hint")} />
        </>
      )}

      {/* ===== 添加技能弹窗（受控：宿主页头主按钮 / 空态 CTA 均可打开） ===== */}
      <Dialog open={addOpen} onOpenChange={onAddOpenChange}>
        <DialogContent data-testid="agents-skills-add-dialog" className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("agents.skills.add")}</DialogTitle>
            <DialogDescription>{t("agents.skills.addDialog.description")}</DialogDescription>
          </DialogHeader>
          <div
            data-testid="agents-skills-add-dialog-empty"
            className="flex min-h-32 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground"
          >
            {t("agents.skills.addDialog.marketPending")}
          </div>
        </DialogContent>
      </Dialog>

      {/* ===== 上传技能弹窗（F-27.3）：文件选择 + 提交占位禁用 ===== */}
      <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
        <DialogContent data-testid="agents-skills-upload-dialog" className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("agents.skills.add.upload")}</DialogTitle>
            <DialogDescription>{t("agents.skills.uploadDialog.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <input
              type="file"
              data-testid="agents-skills-upload-input"
              accept=".zip"
              className="block w-full cursor-pointer rounded-md border border-input bg-background px-3 py-2 text-sm text-muted-foreground file:mr-3 file:cursor-pointer file:border-0 file:bg-muted file:px-3 file:py-1 file:text-xs file:text-foreground"
            />
            <Button type="button" size="sm" data-testid="agents-skills-upload-submit" disabled>
              {t("agents.skills.uploadDialog.submit")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
