// ---------------------------------------------------------------------------
// WBTimeAI · 「添加模型配置」弹窗（V0.4.6 BugFix · B-07）
//
// 需求（用户实测）：设置·模型分区不再跳转 `/models`；在本页直接添加模型，
// 表单需支持两类：
//   - **常用模型**：选择预设提供方（OpenAI / Anthropic / Gemini / DeepSeek / 通义千问 / Ollama）
//     + 预设模型名，填 API Key 即可；
//   - **自定义模型**：自填提供方名称 / Base URL / 模型名 / 上下文窗口（OpenAI 兼容协议）。
//
// 写入链路（后端既有端点，无新增）：
//   1) `POST /models/providers`（不存在同名提供方时）——`config.model_kind` 记录 common/custom；
//   2) `POST /models/credentials`（有 API Key 时，仅存掩码）；
//   3) `POST /models/providers/{id}/credential`（绑定凭证引用）；
//   4) `POST /models/providers/{id}/models`（注册模型）。
//
// 🔴 凭据纪律（C-07）：明文 Key 仅提交一次，不落 state 之外、不回显、不写日志。
// ---------------------------------------------------------------------------
import { useEffect, useMemo, useState } from "react";

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
import {
  useBindCredential,
  useProviders,
  useRegisterModel,
  useRegisterProvider,
  useSaveCredential,
} from "@/hooks/useModels";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/uiStore";

/** 模型类型（决定表单分支与列表分组）。 */
export type ModelConfigKind = "common" | "custom";

/** 常用提供方预设。 */
interface ModelPreset {
  key: string;
  /** 展示名（同时作为 Provider `name`）。 */
  label: string;
  /** 后端 `provider_type`（见 `MODEL_PROVIDER_TYPES`）。 */
  providerType: string;
  endpoint: string;
  /** 预设模型（可手输覆盖）。 */
  models: readonly string[];
  /** 本地服务（无 API Key 亦可）。 */
  keyOptional?: boolean;
}

/** 常用模型预设（覆盖后端允许的 provider_type，零新增依赖）。 */
const PRESETS: readonly ModelPreset[] = [
  {
    key: "openai",
    label: "OpenAI",
    providerType: "openai",
    endpoint: "https://api.openai.com/v1",
    models: ["gpt-4o", "gpt-4o-mini", "o3-mini"],
  },
  {
    key: "anthropic",
    label: "Anthropic",
    providerType: "anthropic",
    endpoint: "https://api.anthropic.com",
    models: ["claude-3-7-sonnet", "claude-3-5-haiku"],
  },
  {
    key: "gemini",
    label: "Google Gemini",
    providerType: "gemini",
    endpoint: "https://generativelanguage.googleapis.com",
    models: ["gemini-2.0-flash", "gemini-1.5-pro"],
  },
  {
    key: "deepseek",
    label: "DeepSeek",
    providerType: "deepseek",
    endpoint: "https://api.deepseek.com/v1",
    models: ["deepseek-chat", "deepseek-reasoner"],
  },
  {
    key: "qwen",
    label: "通义千问",
    providerType: "qwen",
    endpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: ["qwen-plus", "qwen-max"],
  },
  {
    key: "ollama",
    label: "Ollama（本地）",
    providerType: "ollama",
    endpoint: "http://localhost:11434/v1",
    models: ["llama3.1", "qwen2.5"],
    keyOptional: true,
  },
];

/** {@link AddModelConfigDialog} 属性。 */
export interface AddModelConfigDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 添加成功后回调（父级可刷新/提示）。 */
  onAdded?: (modelName: string) => void;
}

/**
 * 「添加模型配置」弹窗。
 *
 * 两类模型共用同一提交链路，仅字段来源不同；成功后关闭并 toast 提示。
 */
export function AddModelConfigDialog({ open, onOpenChange, onAdded }: AddModelConfigDialogProps) {
  const { t } = useTranslation();
  const { data: providers } = useProviders();
  const registerProvider = useRegisterProvider();
  const registerModel = useRegisterModel();
  const saveCredential = useSaveCredential();
  const bindCredential = useBindCredential();
  const showToast = useUiStore((state) => state.showToast);

  const [kind, setKind] = useState<ModelConfigKind>("common");
  const [presetKey, setPresetKey] = useState<string>(PRESETS[0].key);
  const [presetModel, setPresetModel] = useState<string>(PRESETS[0].models[0]);
  const [modelName, setModelName] = useState<string>(PRESETS[0].models[0]);
  const [apiKey, setApiKey] = useState<string>("");
  // 自定义分支字段。
  const [providerName, setProviderName] = useState<string>("自定义模型");
  const [endpoint, setEndpoint] = useState<string>("");
  const [contextWindow, setContextWindow] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const preset = useMemo(
    () => PRESETS.find((item) => item.key === presetKey) ?? PRESETS[0],
    [presetKey],
  );

  // 切预设：模型名跟随预设首项（用户仍可改）。
  useEffect(() => {
    setPresetModel(preset.models[0]);
    setModelName(preset.models[0]);
  }, [preset]);

  // 关闭后清空明文 Key 与错误（下次打开回到干净态；保留类型/预设便于连续添加）。
  useEffect(() => {
    if (!open) {
      setApiKey("");
      setError(null);
    }
  }, [open]);

  /** 提交：按分支创建 Provider（如缺）/ 凭证 / 模型。 */
  const handleSubmit = async (): Promise<void> => {
    const keyRequired = kind === "common" && !preset.keyOptional;
    const trimmedKey = apiKey.trim();

    if (keyRequired && !trimmedKey) {
      setError(t("settings.models.dialog.apiKeyRequired"));
      return;
    }

    let targetProviderName = preset.label;
    let targetType = preset.providerType;
    let targetEndpoint: string | null = preset.endpoint;
    let targetModelName = (kind === "common" ? presetModel : modelName).trim();

    if (kind === "custom") {
      targetProviderName = providerName.trim() || "自定义模型";
      targetType = "openai_compatible";
      targetEndpoint = endpoint.trim() || null;
      targetModelName = modelName.trim();
      if (!targetEndpoint) {
        setError(t("settings.models.dialog.endpointRequired"));
        return;
      }
      if (!targetModelName) {
        setError(t("settings.models.dialog.modelRequired"));
        return;
      }
    }

    setError(null);
    setSubmitting(true);
    try {
      // 1) Provider：同名同类型复用，避免重复建目录项。
      let provider = (providers ?? []).find(
        (item) => item.name === targetProviderName && item.type === targetType,
      );
      if (!provider) {
        provider = await registerProvider.mutateAsync({
          name: targetProviderName,
          provider_type: targetType,
          endpoint: targetEndpoint,
          config: { model_kind: kind, ...(kind === "common" ? { preset: preset.key } : {}) },
        });
      }

      // 2) + 3) 凭证（可选）与绑定。
      if (trimmedKey) {
        const credential = await saveCredential.mutateAsync({
          provider: targetProviderName,
          key_type: "api_key",
          value: trimmedKey,
        });
        await bindCredential.mutateAsync({
          providerId: provider.id,
          payload: { credential_id: credential.id },
        });
      }

      // 4) 模型注册。
      const parsedContext = Number.parseInt(contextWindow, 10);
      await registerModel.mutateAsync({
        providerId: provider.id,
        payload: {
          name: targetModelName,
          model_type: "CHAT",
          context_window: Number.isFinite(parsedContext) ? parsedContext : null,
        },
      });

      showToast({
        title: t("settings.models.dialog.success", { name: targetModelName }),
      });
      onAdded?.(targetModelName);
      onOpenChange(false);
    } catch (submitError) {
      setError(t("settings.models.dialog.failed", { message: toApiError(submitError).message }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="add-model-config-dialog"
        className="max-h-[85vh] max-w-lg overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle>{t("settings.models.dialog.title")}</DialogTitle>
          <DialogDescription>{t("settings.models.dialog.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 模型类型：常用 / 自定义 */}
          <div className="space-y-1.5">
            <Label>{t("settings.models.dialog.kind")}</Label>
            <div
              role="radiogroup"
              aria-label={t("settings.models.dialog.kind")}
              className="grid grid-cols-2 gap-2"
            >
              {(
                [
                  ["common", "settings.models.dialog.kind.common"],
                  ["custom", "settings.models.dialog.kind.custom"],
                ] as const
              ).map(([value, labelKey]) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={kind === value}
                  data-testid={`add-model-kind-${value}`}
                  onClick={() => {
                    setKind(value);
                    setError(null);
                  }}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-sm transition-colors",
                    kind === value
                      ? "border-primary bg-accent/15 font-medium text-primary dark:text-accent"
                      : "border-border text-muted-foreground hover:bg-accent/10",
                  )}
                >
                  {t(labelKey)}
                </button>
              ))}
            </div>
          </div>

          {kind === "common" ? (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="add-model-preset">{t("settings.models.dialog.provider")}</Label>
                <Select value={presetKey} onValueChange={setPresetKey}>
                  <SelectTrigger id="add-model-preset" data-testid="add-model-preset">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PRESETS.map((item) => (
                      <SelectItem key={item.key} value={item.key}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[11px] text-muted-foreground">{preset.endpoint}</p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="add-model-common-name">{t("settings.models.dialog.model")}</Label>
                <Select value={presetModel} onValueChange={setPresetModel}>
                  <SelectTrigger id="add-model-common-name" data-testid="add-model-common-name">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {preset.models.map((name) => (
                      <SelectItem key={name} value={name}>
                        {name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="add-model-provider-name">
                  {t("settings.models.dialog.providerName")}
                </Label>
                <Input
                  id="add-model-provider-name"
                  data-testid="add-model-provider-name"
                  value={providerName}
                  onChange={(event) => setProviderName(event.target.value)}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="add-model-endpoint">{t("settings.models.dialog.endpoint")}</Label>
                <Input
                  id="add-model-endpoint"
                  data-testid="add-model-endpoint"
                  placeholder="https://api.example.com/v1"
                  value={endpoint}
                  onChange={(event) => setEndpoint(event.target.value)}
                />
                <p className="text-[11px] text-muted-foreground">
                  {t("settings.models.dialog.customHint")}
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="add-model-name">{t("settings.models.dialog.model")}</Label>
                <Input
                  id="add-model-name"
                  data-testid="add-model-name"
                  placeholder="my-model"
                  value={modelName}
                  onChange={(event) => setModelName(event.target.value)}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="add-model-context">{t("settings.models.dialog.context")}</Label>
                <Input
                  id="add-model-context"
                  data-testid="add-model-context"
                  inputMode="numeric"
                  placeholder="128000"
                  value={contextWindow}
                  onChange={(event) => setContextWindow(event.target.value)}
                />
              </div>
            </>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="add-model-api-key">{t("settings.models.dialog.apiKey")}</Label>
            <Input
              id="add-model-api-key"
              data-testid="add-model-api-key"
              type="password"
              autoComplete="off"
              placeholder={
                kind === "common" && preset.keyOptional
                  ? t("settings.models.dialog.apiKeyOptional")
                  : "sk-…"
              }
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </div>

          {error ? (
            <p data-testid="add-model-error" role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            data-testid="add-model-cancel"
            onClick={() => onOpenChange(false)}
          >
            {t("settings.models.dialog.cancel")}
          </Button>
          <Button
            type="button"
            data-testid="add-model-submit"
            disabled={submitting}
            onClick={() => void handleSubmit()}
          >
            {submitting
              ? t("settings.models.dialog.submitting")
              : t("settings.models.dialog.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
