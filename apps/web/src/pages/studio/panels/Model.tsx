import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useProviders, useProviderModels } from "@/hooks/useModels";
import { useTranslation } from "@/i18n";
import type { AgentStudioPanelProps } from "@/types";

/**
 * Model 面板（W8 / T2-41；设计 §2.13）。
 *
 * 选择模型**提供方 + 模型**，写入 Studio 草稿的 `modelConfig`
 * （发布时落到 `agent_version.model_config`）。复用既有模型服务（不重复实现）。
 */
export function Model({ draft, onDraftChange }: AgentStudioPanelProps) {
  const { t } = useTranslation();
  const { data: providers } = useProviders();

  const providerId =
    typeof draft.modelConfig.provider_id === "string" ? draft.modelConfig.provider_id : "";
  const modelName = typeof draft.modelConfig.model === "string" ? draft.modelConfig.model : "";

  const { data: models } = useProviderModels(providerId || null);

  const setModelConfig = (patch: Record<string, unknown>): void => {
    onDraftChange({ modelConfig: { ...draft.modelConfig, ...patch } });
  };

  const handleProviderChange = (nextProviderId: string): void => {
    const provider = (providers ?? []).find((item) => item.id === nextProviderId);
    setModelConfig({
      provider_id: nextProviderId,
      provider: provider?.name ?? provider?.type ?? "",
      model: "",
    });
  };

  return (
    <div className="space-y-4" data-testid="panel-model">
      <Card>
        <CardHeader>
          <CardTitle>{t("studio.panel.model.title")}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="model-provider">{t("studio.panel.model.provider")}</Label>
            <Select value={providerId || undefined} onValueChange={handleProviderChange}>
              <SelectTrigger id="model-provider" data-testid="model-provider-select">
                <SelectValue placeholder={t("studio.panel.model.placeholder")} />
              </SelectTrigger>
              <SelectContent>
                {(providers ?? []).map((provider) => (
                  <SelectItem key={provider.id} value={provider.id}>
                    {provider.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="model-name">{t("studio.panel.model.model")}</Label>
            <Select
              value={modelName || undefined}
              onValueChange={(value) => setModelConfig({ model: value })}
              disabled={!providerId}
            >
              <SelectTrigger id="model-name" data-testid="model-name-select">
                <SelectValue placeholder={t("studio.panel.model.placeholder")} />
              </SelectTrigger>
              <SelectContent>
                {(models ?? []).map((model) => (
                  <SelectItem key={model.id} value={model.name}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
