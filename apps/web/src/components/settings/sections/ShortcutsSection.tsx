import { RotateCcw, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useTranslation } from "@/i18n";

/** 只读快捷键条目（UI 先行；Q12 拍板：本波仅展示，不接绑定编辑）。 */
interface ShortcutRow {
  /** 行 testid 后缀。 */
  id: string;
  /** 命令名 i18n key。 */
  labelKey: string;
  /** 按键绑定（展示串）。 */
  binding: string;
}

/** 快捷键表（顺序冻结）。 */
const SHORTCUT_ROWS: readonly ShortcutRow[] = [
  { id: "new-chat", labelKey: "settings.shortcuts.row.newChat", binding: "Ctrl+N" },
  { id: "find", labelKey: "settings.shortcuts.row.find", binding: "Ctrl+K" },
  { id: "settings", labelKey: "settings.shortcuts.row.settings", binding: "Ctrl+," },
  { id: "close-window", labelKey: "settings.shortcuts.row.closeWindow", binding: "Ctrl+W" },
  { id: "quit", labelKey: "settings.shortcuts.row.quit", binding: "Ctrl+Q" },
];

/**
 * 设置 · 快捷键分区（V0.4.5 B5 · F-26 新增第 8 区）。
 *
 * - 顶部搜索框（本地过滤命令名）+「全部恢复默认」（**占位禁用**，待绑定编辑接入）；
 * - **只读表格**（命令 / 按键绑定 / 操作）：操作列为删除按钮禁用占位；
 * - 本波纯展示（UI 先行），不做真实按键绑定读写。
 *
 * `data-testid`：`settings-shortcuts` / `settings-shortcuts-search` /
 * `settings-shortcuts-reset` / `settings-shortcuts-row-<id>` /
 * `settings-shortcuts-delete-<id>`。
 */
export function ShortcutsSection() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) {
      return SHORTCUT_ROWS;
    }
    return SHORTCUT_ROWS.filter((row) =>
      `${t(row.labelKey)} ${row.binding}`.toLowerCase().includes(keyword),
    );
  }, [query, t]);

  return (
    <section
      aria-label={t("settings.shortcuts.title")}
      data-testid="settings-shortcuts"
      className="space-y-4"
    >
      <h3 className="text-sm font-semibold text-foreground">{t("settings.shortcuts.title")}</h3>

      {/* 顶部：搜索 + 全部恢复默认（占位禁用）。 */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            data-testid="settings-shortcuts-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("settings.shortcuts.search")}
            className="pl-8"
          />
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          data-testid="settings-shortcuts-reset"
          disabled
          title={t("settings.shortcuts.pending")}
        >
          <RotateCcw className="h-3.5 w-3.5" />
          {t("settings.shortcuts.reset")}
        </Button>
      </div>

      {/* 只读表格（命令 / 按键绑定 / 操作）。 */}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("settings.shortcuts.col.command")}</TableHead>
            <TableHead>{t("settings.shortcuts.col.binding")}</TableHead>
            <TableHead className="w-16">{t("settings.shortcuts.col.action")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={3} className="text-center text-muted-foreground">
                {t("settings.shortcuts.empty")}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow key={row.id} data-testid={`settings-shortcuts-row-${row.id}`}>
                <TableCell className="text-foreground">{t(row.labelKey)}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{row.binding}</TableCell>
                <TableCell>
                  <button
                    type="button"
                    aria-label={t("settings.shortcuts.delete")}
                    title={t("settings.shortcuts.pending")}
                    data-testid={`settings-shortcuts-delete-${row.id}`}
                    disabled
                    className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      <p className="text-xs text-muted-foreground">{t("settings.shortcuts.pending")}</p>
    </section>
  );
}
