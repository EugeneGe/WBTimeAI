import { PackageOpen, Plug } from "lucide-react";
import { useState } from "react";

import { InlineEmpty } from "@/components/common/InlineEmpty";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePlugins } from "@/hooks/usePlugins";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import { useUiStore } from "@/stores/uiStore";
import { PLUGIN_STATUS_INSTALLED } from "@/types";
import type { PluginResponse } from "@/types";

import { InstallPluginDialog } from "./InstallPluginDialog";
import { PluginDeleteDialog } from "./PluginDeleteDialog";

/** 非 `installed`（降级 / 停用 / 异常）的琥珀 warn tag 样式。 */
const WARN_TAG_CLASS =
  "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400 hover:bg-amber-500/10";
/** `installed` 的正常色 tag 样式。 */
const OK_TAG_CLASS =
  "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/10";

/** 从 `manifest` 读取非空字符串（缺省 / 非字符串 → `null`）。 */
function readManifestString(manifest: Record<string, unknown>, key: string): string | null {
  const value = manifest[key];
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * 设置 · 系统分区内的「插件」区块（V0.4.6 收口 · M07-01 第 12 条）。
 *
 * 只读表格（名称 / 版本 / core_compat / 扩展点 / 状态）+「安装插件」行式弹窗 + 卸载二次确认。
 *
 * 🔴 **`core_compat` 不在 `PluginResponse` 顶层**：取 `manifest.core_compat`；缺失显示
 *    「未知」（灰色占位，**不是错误**）。
 * 🔴 **`GET /plugins` 是全局的**（非租户隔离）：顶部固定说明，避免误读为「本租户已装」。
 * 🔴 **不阻塞核心启动**：本区块自带加载 / 空 / 错误三态，失败仅在本区块内降级。
 *
 * `data-testid`：`settings-plugins` / `-scope-note` / `-install` / `-loading` / `-empty` /
 * `-error` / `-table` / `-row-<id>` / `-status-<id>` / `-core-compat-<id>` / `-uninstall-<id>`。
 */
export function PluginSection() {
  const { t } = useTranslation();
  const plugins = usePlugins();
  const showToast = useUiStore((state) => state.showToast);

  const [installOpen, setInstallOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<PluginResponse | null>(null);

  /** 状态文案：已知状态走 i18n，未知状态**原样**展示（不当成错误）。 */
  const statusLabel = (status: string): string => {
    const key = `settings.plugins.status.${status}`;
    const translated = t(key);
    return translated === key ? status : translated;
  };

  /** 降级原因：优先 `manifest.status_reason`，缺失则回落原始 status 值。 */
  const statusReason = (plugin: PluginResponse): string => {
    return readManifestString(plugin.manifest, "status_reason") ?? plugin.status;
  };

  const items = plugins.data ?? [];

  return (
    <section
      aria-label={t("settings.plugins.title")}
      data-testid="settings-plugins"
      className="space-y-3 border-t border-border pt-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h4 className="text-sm font-semibold text-foreground">{t("settings.plugins.title")}</h4>
          {/* 全局性明示：`GET /plugins` 非租户隔离。 */}
          <p
            data-testid="settings-plugins-scope-note"
            className="max-w-[420px] text-[11px] leading-[1.5] text-muted-foreground"
          >
            {t("settings.plugins.scopeNote")}
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          data-testid="settings-plugins-install"
          onClick={() => setInstallOpen(true)}
        >
          <Plug className="h-3.5 w-3.5" />
          {t("settings.plugins.install")}
        </Button>
      </div>

      {plugins.isPending ? (
        <div data-testid="settings-plugins-loading" className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : plugins.isError ? (
        <div
          data-testid="settings-plugins-error"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2.5"
        >
          <span className="text-xs text-destructive">
            {t("settings.plugins.loadFailed")}: {toApiError(plugins.error).message}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="settings-plugins-retry"
            onClick={() => {
              void plugins.refetch();
            }}
          >
            {t("common.retry")}
          </Button>
        </div>
      ) : items.length === 0 ? (
        <InlineEmpty
          icon={PackageOpen}
          title={t("settings.plugins.empty.title")}
          description={t("settings.plugins.empty.description")}
          testId="settings-plugins-empty"
        />
      ) : (
        <Table data-testid="settings-plugins-table">
          <TableHeader>
            <TableRow>
              <TableHead>{t("settings.plugins.col.name")}</TableHead>
              <TableHead className="w-[92px]">{t("settings.plugins.col.version")}</TableHead>
              <TableHead className="w-[110px]">{t("settings.plugins.col.coreCompat")}</TableHead>
              <TableHead>{t("settings.plugins.col.extensionPoint")}</TableHead>
              <TableHead className="w-[92px]">{t("settings.plugins.col.status")}</TableHead>
              <TableHead className="w-[72px]">{t("settings.plugins.col.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((plugin) => {
              const coreCompat = readManifestString(plugin.manifest, "core_compat");
              const isInstalled = plugin.status === PLUGIN_STATUS_INSTALLED;
              return (
                <TableRow key={plugin.id} data-testid={`settings-plugin-row-${plugin.id}`}>
                  <TableCell>
                    <div className="flex flex-col">
                      <span className="text-sm font-medium text-foreground">{plugin.name}</span>
                      <span className="text-[11px] text-muted-foreground">{plugin.kind}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{plugin.version}</TableCell>
                  <TableCell
                    data-testid={`settings-plugin-core-compat-${plugin.id}`}
                    className={
                      coreCompat === null
                        ? "text-xs text-muted-foreground"
                        : "text-xs text-foreground"
                    }
                  >
                    {coreCompat ?? t("settings.plugins.unknown")}
                  </TableCell>
                  <TableCell className="text-xs">
                    {plugin.entry_point !== null && plugin.entry_point !== "" ? (
                      <span className="break-all font-mono text-foreground">
                        {plugin.entry_point}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">{t("settings.plugins.none")}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge
                      data-testid={`settings-plugin-status-${plugin.id}`}
                      variant="outline"
                      className={isInstalled ? OK_TAG_CLASS : WARN_TAG_CLASS}
                      title={isInstalled ? undefined : statusReason(plugin)}
                    >
                      {statusLabel(plugin.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      data-testid={`settings-plugin-uninstall-${plugin.id}`}
                      onClick={() => setPendingDelete(plugin)}
                    >
                      {t("settings.plugins.uninstall")}
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      <InstallPluginDialog
        open={installOpen}
        onOpenChange={setInstallOpen}
        onInstalled={(plugin) => {
          showToast({
            title: t("settings.plugins.form.installed"),
            description: plugin.name,
          });
        }}
      />
      <PluginDeleteDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingDelete(null);
          }
        }}
        plugin={pendingDelete}
        onRemoved={(plugin) => {
          showToast({
            title: t("settings.plugins.uninstalled"),
            description: plugin.name,
          });
        }}
      />
    </section>
  );
}
