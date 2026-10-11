import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useGrantToolPermission } from "@/hooks/useTools";
import { toApiError } from "@/lib/api";
import type {
  AgentResponse,
  ToolAction,
  ToolEffect,
  ToolPermissionResponse,
  ToolResponse,
} from "@/types";

/** Tool 权限表单选项。 */
export interface ToolPermissionFormProps {
  /** 可选 Agent 列表。 */
  agents: AgentResponse[];
  /** 可选 Tool 列表。 */
  tools: ToolResponse[];
  /** 默认选中的 Agent（如详情页）。 */
  defaultAgentId?: string;
  /** 授予成功回调。 */
  onGranted?: (permission: ToolPermissionResponse) => void;
}

/** 权限动作选项。 */
const ACTIONS: readonly ToolAction[] = ["EXECUTE", "READ", "WRITE"];

/** 权限效果选项（ALLOW / DENY）。 */
const EFFECTS: readonly ToolEffect[] = ["ALLOW", "DENY"];

/**
 * Tool 权限配置表单（W7 / T1-34）。
 *
 * 维度：**agent × tool × effect × scope**（`effect ∈ {ALLOW, DENY}`，`scope` 为 JSON）。
 */
export function ToolPermissionForm({
  agents,
  tools,
  defaultAgentId,
  onGranted,
}: ToolPermissionFormProps) {
  const [agentId, setAgentId] = useState(defaultAgentId ?? "");
  const [toolId, setToolId] = useState("");
  const [action, setAction] = useState<ToolAction>("EXECUTE");
  const [effect, setEffect] = useState<ToolEffect>("ALLOW");
  const [scopeText, setScopeText] = useState("{}");
  const [feedback, setFeedback] = useState<string | null>(null);
  const grant = useGrantToolPermission();

  const handleSubmit = (): void => {
    if (!agentId || !toolId) {
      setFeedback("请选择 Agent 与 Tool");
      return;
    }
    let scope: Record<string, unknown>;
    try {
      scope = JSON.parse(scopeText || "{}") as Record<string, unknown>;
    } catch {
      setFeedback("scope 必须是合法 JSON");
      return;
    }
    setFeedback(null);
    grant.mutate(
      { agent_id: agentId, tool_id: toolId, action, effect, scope },
      {
        onSuccess: (permission) => {
          setFeedback(`已${effect === "ALLOW" ? "授予" : "拒绝"}权限`);
          onGranted?.(permission);
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <Card data-testid="tool-permission-form">
      <CardHeader>
        <CardTitle>工具权限配置</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2">
          <Label htmlFor="permission-agent">Agent</Label>
          <select
            id="permission-agent"
            data-testid="permission-agent-select"
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={agentId}
            onChange={(event) => setAgentId(event.target.value)}
          >
            <option value="">请选择</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="permission-tool">Tool</Label>
          <select
            id="permission-tool"
            data-testid="permission-tool-select"
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={toolId}
            onChange={(event) => setToolId(event.target.value)}
          >
            <option value="">请选择</option>
            {tools.map((tool) => (
              <option key={tool.id ?? tool.name} value={tool.id ?? tool.name}>
                {tool.display_name || tool.name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="permission-action">动作</Label>
            <select
              id="permission-action"
              data-testid="permission-action-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={action}
              onChange={(event) => setAction(event.target.value as ToolAction)}
            >
              {ACTIONS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="permission-effect">效果</Label>
            <select
              id="permission-effect"
              data-testid="permission-effect-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={effect}
              onChange={(event) => setEffect(event.target.value as ToolEffect)}
            >
              {EFFECTS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="permission-scope">Scope（JSON）</Label>
          <textarea
            id="permission-scope"
            data-testid="permission-scope-input"
            className="h-20 w-full rounded-md border border-input bg-background p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={scopeText}
            onChange={(event) => setScopeText(event.target.value)}
          />
        </div>
        {feedback ? (
          <p className="text-sm text-muted-foreground" data-testid="permission-feedback">
            {feedback}
          </p>
        ) : null}
        <Button
          size="sm"
          data-testid="permission-submit"
          onClick={handleSubmit}
          disabled={grant.isPending}
        >
          保存权限
        </Button>
      </CardContent>
    </Card>
  );
}
