import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  /**
   * 整体禁用（B10）：为 `true` 时四个下拉 / Scope 文本域与提交按钮全部不可交互。
   * 缺省 `false`（保持既有行为）。
   */
  disabled?: boolean;
  /**
   * 卡底说明文案（M03-04）：**传了才**在 `CardContent` 末尾渲染一行 11px 说明。
   * 缺省 `undefined`（保持无页脚，如智能体详情页的调用）。
   */
  footerNote?: string;
}

/** 权限动作选项。 */
const ACTIONS: readonly ToolAction[] = ["EXECUTE", "READ", "WRITE"];

/** 权限效果选项（ALLOW / DENY）。 */
const EFFECTS: readonly ToolEffect[] = ["ALLOW", "DENY"];

/**
 * Tool 权限配置表单（W7 / T1-34）。
 *
 * 维度：**agent × tool × effect × scope**（`effect ∈ {ALLOW, DENY}`，`scope` 为 JSON）。
 *
 * D-UI WS-F：四处下拉改为 `ui/select` 原语（键盘可达），行为/文案/testid 保留；
 * 空串占位（radix `SelectItem` 不接受空 value）改由 `SelectValue` 的 `placeholder` 呈现。
 */
export function ToolPermissionForm({
  agents,
  tools,
  defaultAgentId,
  onGranted,
  disabled = false,
  footerNote,
}: ToolPermissionFormProps) {
  const [agentId, setAgentId] = useState(defaultAgentId ?? "");
  const [toolId, setToolId] = useState("");
  const [action, setAction] = useState<ToolAction>("EXECUTE");
  const [effect, setEffect] = useState<ToolEffect>("ALLOW");
  const [scopeText, setScopeText] = useState("{}");
  const [feedback, setFeedback] = useState<string | null>(null);
  const grant = useGrantToolPermission();

  const handleSubmit = (): void => {
    // 整体禁用时直接短路（按钮已 disabled，此处为防御式兜底）。
    if (disabled) {
      return;
    }
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
          <Select value={agentId || undefined} onValueChange={setAgentId} disabled={disabled}>
            <SelectTrigger id="permission-agent" data-testid="permission-agent-select">
              <SelectValue placeholder="请选择" />
            </SelectTrigger>
            <SelectContent>
              {agents.map((agent) => (
                <SelectItem key={agent.id} value={agent.id}>
                  {agent.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="permission-tool">Tool</Label>
          <Select value={toolId || undefined} onValueChange={setToolId} disabled={disabled}>
            <SelectTrigger id="permission-tool" data-testid="permission-tool-select">
              <SelectValue placeholder="请选择" />
            </SelectTrigger>
            <SelectContent>
              {tools.map((tool) => (
                <SelectItem key={tool.id ?? tool.name} value={tool.id ?? tool.name}>
                  {tool.display_name || tool.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="permission-action">动作</Label>
            <Select
              value={action}
              onValueChange={(value) => setAction(value as ToolAction)}
              disabled={disabled}
            >
              <SelectTrigger id="permission-action" data-testid="permission-action-select">
                <SelectValue placeholder="请选择" />
              </SelectTrigger>
              <SelectContent>
                {ACTIONS.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="permission-effect">效果</Label>
            <Select
              value={effect}
              onValueChange={(value) => setEffect(value as ToolEffect)}
              disabled={disabled}
            >
              <SelectTrigger id="permission-effect" data-testid="permission-effect-select">
                <SelectValue placeholder="请选择" />
              </SelectTrigger>
              <SelectContent>
                {EFFECTS.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="permission-scope">Scope（JSON）</Label>
          <textarea
            id="permission-scope"
            data-testid="permission-scope-input"
            disabled={disabled}
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
          disabled={grant.isPending || disabled}
        >
          保存权限
        </Button>
        {footerNote ? (
          <p
            className="text-[11px] text-muted-foreground"
            data-testid="tool-permission-footer-note"
          >
            {footerNote}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
