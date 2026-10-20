import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTranslation } from "@/i18n";
import type { AgentStudioPanelProps } from "@/types";

/**
 * Prompt 面板（W8 / T2-41；设计 §2.13）。
 *
 * 编辑 **System Prompt**（↔ `agent_version.system_prompt`）与**运行时参数**
 * （如 `temperature`，写入草稿 `runtimeConfig`）。
 */
export function Prompt({ draft, onDraftChange }: AgentStudioPanelProps) {
  const { t } = useTranslation();
  const temperature =
    typeof draft.runtimeConfig.temperature === "number" ? draft.runtimeConfig.temperature : 0.7;

  const setRuntime = (patch: Record<string, unknown>): void => {
    onDraftChange({ runtimeConfig: { ...draft.runtimeConfig, ...patch } });
  };

  return (
    <div className="space-y-4" data-testid="panel-prompt">
      <Card>
        <CardHeader>
          <CardTitle>System Prompt</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="prompt-textarea">{t("studio.panel.prompt.instruction")}</Label>
            <textarea
              id="prompt-textarea"
              data-testid="prompt-textarea"
              className="min-h-[160px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
              value={draft.systemPrompt}
              onChange={(event) => onDraftChange({ systemPrompt: event.target.value })}
              placeholder={t("studio.panel.prompt.instructionPlaceholder")}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="prompt-temperature">temperature</Label>
            <Input
              id="prompt-temperature"
              data-testid="prompt-temperature-input"
              type="number"
              step="0.1"
              min="0"
              max="2"
              value={temperature}
              onChange={(event) => {
                const parsed = Number(event.target.value);
                setRuntime({ temperature: Number.isFinite(parsed) ? parsed : 0.7 });
              }}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
