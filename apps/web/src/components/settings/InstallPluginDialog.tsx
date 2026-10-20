import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useInstallPlugin } from "@/hooks/usePlugins";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { InstallPluginRequest, PluginResponse } from "@/types";

/** {@link InstallPluginDialog} 属性。 */
export interface InstallPluginDialogProps {
  /** 受控开关。 */
  open: boolean;
  /** 开关回调。 */
  onOpenChange: (open: boolean) => void;
  /** 安装成功回调（透传新建插件，供调用方 toast / 定位）。 */
  onInstalled?: (plugin: PluginResponse) => void;
}

/** `kind` 下拉中「其他（手填）」的哨兵值（真实 kind 由文本输入提供）。 */
const KIND_OTHER = "other";

/** 把逗号 / 空白分隔的权限文本解析为 `string[]`（去空、去重、保序）。 */
function parsePermissions(raw: string): string[] {
  const parts = raw
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter((item) => item !== "");
  return Array.from(new Set(parts));
}

/**
 * 安装插件 · 行式弹窗（V0.4.6 收口 · M07-01 第 12 条）。
 *
 * 字段（**完整方案**，对齐后端 `InstallPluginRequest`）：
 * `name`（必填 1–150）/ `version`（必填 1–50）/ `kind`（必填，下拉 connector / tool +
 * 「其他」手填）/ `entry_point`（可选 ≤255）/ `permissions`（可选，逗号分隔 → `string[]`）/
 * `manifest`（可选 JSON 文本，提交前 `JSON.parse` 校验；非法 → **行内错误且不发请求**）。
 *
 * 🔴 **重名 409**：展示后端 `message`（`toApiError(e).message`）并**保留弹窗**，让用户改名重试。
 *
 * `data-testid`：`settings-plugin-form` / `-name` / `-version` / `-kind` / `-kind-custom` /
 * `-entry-point` / `-permissions` / `-manifest` / `-manifest-error` / `-error` / `-submit` / `-cancel`。
 */
export function InstallPluginDialog({ open, onOpenChange, onInstalled }: InstallPluginDialogProps) {
  const { t } = useTranslation();
  const installPlugin = useInstallPlugin();

  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [kind, setKind] = useState<string>("connector");
  const [customKind, setCustomKind] = useState("");
  const [entryPoint, setEntryPoint] = useState("");
  const [permissions, setPermissions] = useState("");
  const [manifestText, setManifestText] = useState("");
  /** 表单级错误（必填校验 / 后端错误统一在此展示）。 */
  const [formError, setFormError] = useState<string | null>(null);
  /** `manifest` JSON 解析的**行内**错误。 */
  const [manifestError, setManifestError] = useState<string | null>(null);

  /** 重置全部字段（每次打开 / 安装成功后）。 */
  const resetForm = (): void => {
    setName("");
    setVersion("");
    setKind("connector");
    setCustomKind("");
    setEntryPoint("");
    setPermissions("");
    setManifestText("");
    setFormError(null);
    setManifestError(null);
  };

  /** 开关变更：关闭时清空错误与字段，避免下次打开残留。 */
  const handleOpenChange = (nextOpen: boolean): void => {
    if (!nextOpen) {
      resetForm();
    }
    onOpenChange(nextOpen);
  };

  /** 提交安装：先本地校验（必填 + manifest JSON），通过后发 `POST /plugins`。 */
  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();

    const resolvedKind = kind === KIND_OTHER ? customKind.trim() : kind;
    const trimmedName = name.trim();
    const trimmedVersion = version.trim();
    if (trimmedName === "" || trimmedVersion === "" || resolvedKind === "") {
      setFormError(t("settings.plugins.form.required"));
      return;
    }

    let manifest: Record<string, unknown> = {};
    if (manifestText.trim() !== "") {
      let parsed: unknown;
      try {
        parsed = JSON.parse(manifestText);
      } catch {
        setManifestError(t("settings.plugins.form.manifestInvalid"));
        return;
      }
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setManifestError(t("settings.plugins.form.manifestNotObject"));
        return;
      }
      manifest = parsed as Record<string, unknown>;
    }

    setManifestError(null);
    setFormError(null);

    const payload: InstallPluginRequest = {
      name: trimmedName,
      version: trimmedVersion,
      kind: resolvedKind,
      entry_point: entryPoint.trim() === "" ? null : entryPoint.trim(),
      permissions: parsePermissions(permissions),
      manifest,
    };

    installPlugin.mutate(payload, {
      onSuccess: (plugin) => {
        resetForm();
        onOpenChange(false);
        onInstalled?.(plugin);
      },
      onError: (error) => {
        // 409 重名 / 422 校验失败 / 网络：展示后端 message，**保留弹窗**让用户修改后重试。
        setFormError(toApiError(error).message);
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        data-testid="settings-plugin-form-dialog"
        className="max-h-[85vh] max-w-lg overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("settings.plugins.form.title")}</DialogTitle>
          <DialogDescription>{t("settings.plugins.form.description")}</DialogDescription>
        </DialogHeader>

        <form data-testid="settings-plugin-form" onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="settings-plugin-form-name">{t("settings.plugins.form.name")}</Label>
            <Input
              id="settings-plugin-form-name"
              data-testid="settings-plugin-form-name"
              value={name}
              maxLength={150}
              required
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-plugin-form-version">
              {t("settings.plugins.form.version")}
            </Label>
            <Input
              id="settings-plugin-form-version"
              data-testid="settings-plugin-form-version"
              value={version}
              maxLength={50}
              required
              autoComplete="off"
              onChange={(event) => setVersion(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-plugin-form-kind">{t("settings.plugins.form.kind")}</Label>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger id="settings-plugin-form-kind" data-testid="settings-plugin-form-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="connector">
                  {t("settings.plugins.form.kind.connector")}
                </SelectItem>
                <SelectItem value="tool">{t("settings.plugins.form.kind.tool")}</SelectItem>
                <SelectItem value={KIND_OTHER}>{t("settings.plugins.form.kind.other")}</SelectItem>
              </SelectContent>
            </Select>
            {kind === KIND_OTHER ? (
              <Input
                data-testid="settings-plugin-form-kind-custom"
                value={customKind}
                maxLength={50}
                placeholder={t("settings.plugins.form.kindPlaceholder")}
                onChange={(event) => setCustomKind(event.target.value)}
              />
            ) : null}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-plugin-form-entry-point">
              {t("settings.plugins.form.entryPoint")}
            </Label>
            <Input
              id="settings-plugin-form-entry-point"
              data-testid="settings-plugin-form-entry-point"
              value={entryPoint}
              maxLength={255}
              autoComplete="off"
              onChange={(event) => setEntryPoint(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-plugin-form-permissions">
              {t("settings.plugins.form.permissions")}
            </Label>
            <Input
              id="settings-plugin-form-permissions"
              data-testid="settings-plugin-form-permissions"
              value={permissions}
              autoComplete="off"
              onChange={(event) => setPermissions(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="settings-plugin-form-manifest">
              {t("settings.plugins.form.manifest")}
            </Label>
            <textarea
              id="settings-plugin-form-manifest"
              data-testid="settings-plugin-form-manifest"
              value={manifestText}
              rows={4}
              spellCheck={false}
              onChange={(event) => {
                setManifestText(event.target.value);
                if (manifestError !== null) {
                  setManifestError(null);
                }
              }}
              className={cn(
                "flex w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs ring-offset-background",
                "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              )}
            />
            {manifestError !== null ? (
              <p
                data-testid="settings-plugin-form-manifest-error"
                role="alert"
                className="text-xs text-destructive"
              >
                {manifestError}
              </p>
            ) : null}
          </div>

          {formError !== null ? (
            <p
              data-testid="settings-plugin-form-error"
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
            >
              {formError}
            </p>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              data-testid="settings-plugin-form-cancel"
              onClick={() => handleOpenChange(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              data-testid="settings-plugin-form-submit"
              disabled={installPlugin.isPending}
            >
              {t("settings.plugins.form.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
