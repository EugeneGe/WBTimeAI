import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useProviders, useProviderModels } from "@/hooks/useModels";
import type { AgentStudioPanelProps } from "@/types";

/**
 * Model 面板（W8 / T2-41；设计 §2.13）。
 *
 * 选择模型**提供方 + 模型**，写入 Studio 草稿的 `modelConfig`
 * （发布时落到 `agent_version.model_config`）。复用既有模型服务（不重复实现）。
 */
export function Model({ draft, onDraftChange }: AgentStudioPanelProps) {
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
          <CardTitle>模型</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="model-provider">模型提供方</Label>
            <select
              id="model-provider"
              data-testid="model-provider-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={providerId}
              onChange={(event) => handleProviderChange(event.target.value)}
            >
              <option value="">请选择</option>
              {(providers ?? []).map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="model-name">模型</Label>
            <select
              id="model-name"
              data-testid="model-name-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={modelName}
              disabled={!providerId}
              onChange={(event) => setModelConfig({ model: event.target.value })}
            >
              <option value="">请选择</option>
              {(models ?? []).map((model) => (
                <option key={model.id} value={model.name}>
                  {model.name}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
