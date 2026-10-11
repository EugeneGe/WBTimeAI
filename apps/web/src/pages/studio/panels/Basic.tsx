import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useStudioAgent, useUpdateStudioAgent } from "@/hooks/useAgentStudio";
import { toApiError } from "@/lib/api";
import type { AgentStudioPanelProps } from "@/types";

/** Agent 状态字面量（↔ `agent.status`）。 */
const STATUSES = ["DRAFT", "ACTIVE", "ARCHIVED"] as const;

/**
 * Basic 面板（W8 / T2-41；设计 §2.13）。
 *
 * Agent 基础元数据（名称 / 描述 / 状态）**读取 → 编辑 → 更新**（↔ `PUT /agents/{id}`）。
 * 创建（C）与列表（R）在 Studio 主框架头部；本面板负责更新（U）。
 *
 * 🔴 动作级守卫经 {@link RequirePermission}（`can()`，后端下发 capability 集）。
 */
export function Basic({ agent, onFeedback }: AgentStudioPanelProps) {
  const { data: detail } = useStudioAgent(agent?.id ?? null);
  const updateAgent = useUpdateStudioAgent();

  const target = detail ?? agent;

  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const effectiveName = name ?? target?.name ?? "";
  const effectiveDescription = description ?? target?.description ?? "";
  const effectiveStatus = status ?? target?.status ?? "DRAFT";

  const handleSave = (): void => {
    if (!target) {
      onFeedback("请先选择或创建 Agent");
      return;
    }
    if (!effectiveName.trim()) {
      onFeedback("请填写 Agent 名称");
      return;
    }
    updateAgent.mutate(
      {
        id: target.id,
        payload: {
          name: effectiveName.trim(),
          description: effectiveDescription || null,
          status: effectiveStatus,
        },
      },
      {
        onSuccess: () => onFeedback("基础信息已保存"),
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4" data-testid="panel-basic">
      <Card>
        <CardHeader>
          <CardTitle>基础信息</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="basic-name">名称</Label>
            <Input
              id="basic-name"
              data-testid="basic-name-input"
              value={effectiveName}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="basic-description">描述</Label>
            <textarea
              id="basic-description"
              data-testid="basic-description-input"
              className="min-h-[72px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={effectiveDescription}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="basic-status">状态</Label>
            <select
              id="basic-status"
              data-testid="basic-status-select"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={effectiveStatus}
              onChange={(event) => setStatus(event.target.value)}
            >
              {STATUSES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="text-xs text-muted-foreground" data-testid="basic-agent-id">
            Agent：{target?.id ?? "—"}
          </div>
          <RequirePermission code="agent:update">
            <Button
              size="sm"
              data-testid="basic-save"
              onClick={handleSave}
              disabled={updateAgent.isPending}
            >
              保存基础信息
            </Button>
          </RequirePermission>
        </CardContent>
      </Card>
    </div>
  );
}
