import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useUninstallPlugin } from "@/hooks/usePlugins";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import type { PluginResponse } from "@/types";

/** {@link PluginDeleteDialog} 属性。 */
export interface PluginDeleteDialogProps {
  /** 受控开关。 */
  open: boolean;
  /** 开关回调。 */
  onOpenChange: (open: boolean) => void;
  /** 待卸载插件（`null` 时仅渲染空弹窗，不展示内容）。 */
  plugin: PluginResponse | null;
  /** 卸载成功回调（透传被删插件，供调用方 toast）。 */
  onRemoved?: (plugin: PluginResponse) => void;
}

/**
 * 卸载插件 · 二次确认弹窗（V0.4.6 收口 · M07-01 第 12 条）。
 *
 * 本仓无 AlertDialog 原语 → 复用 `ui/dialog`（对齐 `knowledge/KbDeleteDialog.tsx`）。
 * 确认后调 `DELETE /plugins/{id}`（**204 无响应体 / 幂等**）：成功 → 关弹窗 + `onRemoved`；
 * 失败保留弹窗并展示后端 message，用户可重试或取消。
 *
 * 🔴 **失败原因不得跨目标残留**（P2-2）：`useUninstallPlugin()` 的 mutation
 *    `isError` / `error` 是**跨调用共享**的，若不复位，插件 A 卸载失败后打开插件 B 的
 *    确认框会继续显示 A 的错误。两道防线：
 *    ① 弹窗每次**打开**时 `reset()`（`useEffect([open])`）；
 *    ② 渲染错误时额外校验 `variables === 当前 plugin.id`（避免 effect 前的单帧残影）。
 *
 * `data-testid`：`settings-plugin-delete-dialog` / `-error` / `-cancel` / `-submit`。
 */
export function PluginDeleteDialog({
  open,
  onOpenChange,
  plugin,
  onRemoved,
}: PluginDeleteDialogProps) {
  const { t } = useTranslation();
  const uninstallPlugin = useUninstallPlugin();
  const resetUninstall = uninstallPlugin.reset;

  // 打开即复位 mutation（`isError` / `error` / `variables` 一并清空）：
  // 否则上一个插件的失败原因会被复用到新目标上（P2-2）。
  useEffect(() => {
    if (open) {
      resetUninstall();
    }
  }, [open, resetUninstall]);

  /** 失败态**仅对当前目标**生效（同一帧内也不会串到别的插件）。 */
  const errorForCurrent =
    uninstallPlugin.isError && uninstallPlugin.variables === plugin?.id
      ? toApiError(uninstallPlugin.error).message
      : null;

  /** 确认卸载（幂等 204；成功后关弹窗并上抛）。 */
  const handleRemove = (): void => {
    if (plugin === null) {
      return;
    }
    uninstallPlugin.mutate(plugin.id, {
      onSuccess: () => {
        onOpenChange(false);
        onRemoved?.(plugin);
      },
      onError: () => {
        // 卸载失败（网络 / 未知）：保留弹窗，错误文案由下方 `error` 分支渲染。
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="settings-plugin-delete-dialog">
        <DialogHeader>
          <DialogTitle>{t("settings.plugins.delete.title")}</DialogTitle>
          <DialogDescription>
            {t("settings.plugins.delete.confirm", { name: plugin?.name ?? "" })}
          </DialogDescription>
        </DialogHeader>

        {errorForCurrent !== null ? (
          <p
            data-testid="settings-plugin-delete-error"
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
          >
            {errorForCurrent}
          </p>
        ) : null}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            data-testid="settings-plugin-delete-cancel"
            onClick={() => onOpenChange(false)}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            data-testid="settings-plugin-delete-submit"
            onClick={handleRemove}
            disabled={uninstallPlugin.isPending}
          >
            {t("settings.plugins.delete.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
