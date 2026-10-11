import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateAgent, usePublishAgent } from "@/hooks/useAgents";
import { useProviders, useProviderModels } from "@/hooks/useModels";
import { useTools } from "@/hooks/useTools";
import { useWorkspaces } from "@/hooks/useWorkspaces";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { AgentResponse } from "@/types";

/** 四步向导的固定顺序（设计 §2.14 / §3-#26）。 */
const STEPS = ["选择模型", "配置 Prompt", "选择 Tool", "绑定 Workspace"] as const;

/** 创建向导选项。 */
export interface CreateAgentWizardProps {
  /** 创建 + 发布成功回调。 */
  onCreated?: (agent: AgentResponse) => void;
}

/**
 * 创建 Agent 向导（W7 / T1-33）。
 *
 * 步骤顺序**固定**：选择模型 → 配置 Prompt → 选择 Tool → 绑定 Workspace。
 * 完成后：`POST /agents` 创建（DRAFT）→ `POST /agents/{id}/publish` 发布首版
 * （发布即写入 `current_version_id`）。
 */
export function CreateAgentWizard({ onCreated }: CreateAgentWizardProps) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [providerId, setProviderId] = useState("");
  const [modelName, setModelName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [toolIds, setToolIds] = useState<string[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const { data: providers } = useProviders();
  const { data: models } = useProviderModels(providerId || null);
  const { data: tools } = useTools();
  const { data: workspaces } = useWorkspaces();
  const createAgent = useCreateAgent();
  const publishAgent = usePublishAgent();

  const selectedProvider = (providers ?? []).find((provider) => provider.id === providerId) ?? null;

  const toggleTool = (toolId: string) => {
    setToolIds((current) =>
      current.includes(toolId) ? current.filter((id) => id !== toolId) : [...current, toolId],
    );
  };

  const stepValid =
    step === 0 ? Boolean(providerId && modelName) : step === 1 ? name.trim().length > 0 : true;

  const handleFinish = async (): Promise<void> => {
    setFeedback(null);
    try {
      const agent = await createAgent.mutateAsync({
        name: name.trim(),
        type: "PRIMARY",
        workspace_id: workspaceId || null,
      });
      await publishAgent.mutateAsync({
        id: agent.id,
        payload: {
          system_prompt: systemPrompt,
          model_config: {
            provider: selectedProvider?.name ?? selectedProvider?.type ?? "",
            model: modelName,
          },
          tools: toolIds.map((toolId) => ({
            tool_id: toolId,
            enabled: true,
            permission_scope: {},
          })),
        },
      });
      setDone(true);
      setFeedback("已创建并发布首版");
      onCreated?.(agent);
    } catch (error) {
      setFeedback(toApiError(error).message);
    }
  };

  const submitting = createAgent.isPending || publishAgent.isPending;

  return (
    <Card data-testid="create-agent-wizard">
      <CardHeader>
        <CardTitle>创建 Agent</CardTitle>
        <ol className="flex flex-wrap gap-2 text-xs">
          {STEPS.map((title, index) => (
            <li
              key={title}
              data-testid={`wizard-step-${index}`}
              className={cn(
                "rounded-full border px-2 py-0.5",
                index === step
                  ? "border-primary bg-primary text-primary-foreground"
                  : "text-muted-foreground",
              )}
            >
              {index + 1}. {title}
            </li>
          ))}
        </ol>
      </CardHeader>
      <CardContent className="space-y-4">
        {done ? (
          <p className="text-sm text-emerald-600" data-testid="wizard-success">
            创建完成
          </p>
        ) : null}

        {step === 0 ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="wizard-provider">模型提供方</Label>
              <select
                id="wizard-provider"
                data-testid="provider-select"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={providerId}
                onChange={(event) => {
                  setProviderId(event.target.value);
                  setModelName("");
                }}
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
              <Label htmlFor="wizard-model">模型</Label>
              <select
                id="wizard-model"
                data-testid="model-select"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={modelName}
                disabled={!providerId}
                onChange={(event) => setModelName(event.target.value)}
              >
                <option value="">请选择</option>
                {(models ?? []).map((model) => (
                  <option key={model.id} value={model.name}>
                    {model.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        ) : null}

        {step === 1 ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="wizard-name">Agent 名称</Label>
              <Input
                id="wizard-name"
                data-testid="agent-name-input"
                value={name}
                placeholder="例如：编码助手"
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="wizard-prompt">System Prompt</Label>
              <textarea
                id="wizard-prompt"
                data-testid="agent-prompt-input"
                className="h-32 w-full rounded-md border border-input bg-background p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={systemPrompt}
                onChange={(event) => setSystemPrompt(event.target.value)}
              />
            </div>
          </div>
        ) : null}

        {step === 2 ? (
          <div className="space-y-2">
            <Label>选择 Tool</Label>
            <ul className="space-y-1">
              {(tools ?? []).map((tool) => {
                const toolId = tool.id ?? tool.name;
                return (
                  <li key={toolId} className="flex items-center gap-2 text-sm">
                    <input
                      id={`wizard-tool-${tool.name}`}
                      data-testid={`tool-option-${tool.name}`}
                      type="checkbox"
                      checked={toolIds.includes(toolId)}
                      onChange={() => toggleTool(toolId)}
                    />
                    <label htmlFor={`wizard-tool-${tool.name}`}>
                      {tool.display_name || tool.name}
                      {tool.requires_sandbox ? (
                        <span className="ml-1 text-xs text-muted-foreground">（需沙箱）</span>
                      ) : null}
                    </label>
                  </li>
                );
              })}
              {(tools ?? []).length === 0 ? (
                <li className="text-sm text-muted-foreground">暂无可用工具</li>
              ) : null}
            </ul>
          </div>
        ) : null}

        {step === 3 ? (
          <div className="space-y-2">
            <Label htmlFor="wizard-workspace">绑定 Workspace</Label>
            <select
              id="wizard-workspace"
              data-testid="workspace-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={workspaceId}
              onChange={(event) => setWorkspaceId(event.target.value)}
            >
              <option value="">不绑定</option>
              {(workspaces ?? []).map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {feedback ? (
          <p className="text-sm text-muted-foreground" data-testid="wizard-feedback">
            {feedback}
          </p>
        ) : null}

        <div className="flex items-center justify-between gap-2 border-t pt-4">
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="wizard-prev"
            disabled={step === 0 || submitting}
            onClick={() => setStep((current) => Math.max(0, current - 1))}
          >
            上一步
          </Button>
          {step < STEPS.length - 1 ? (
            <Button
              type="button"
              size="sm"
              data-testid="wizard-next"
              disabled={!stepValid || submitting}
              onClick={() => setStep((current) => Math.min(STEPS.length - 1, current + 1))}
            >
              下一步
            </Button>
          ) : (
            <Button
              type="button"
              size="sm"
              data-testid="wizard-finish"
              disabled={submitting || done}
              onClick={() => {
                void handleFinish();
              }}
            >
              完成
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
