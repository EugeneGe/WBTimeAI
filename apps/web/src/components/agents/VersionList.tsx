import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAgentVersions, usePublishAgent } from "@/hooks/useAgents";
import { useTools } from "@/hooks/useTools";
import { toApiError } from "@/lib/api";
import type { AgentVersionResponse } from "@/types";

/** 版本列表与发布面板选项。 */
export interface VersionListProps {
  /** 目标 Agent。 */
  agentId: string;
  /** 当前生效版本（`agent.current_version_id`）。 */
  currentVersionId?: string | null;
}

/**
 * Agent 版本管理与发布（W7 / T1-33）。
 *
 * **一次发布 = 一个新版本**，且发布即切换 `agent.current_version_id`（不可变快照）。
 */
export function VersionList({ agentId, currentVersionId }: VersionListProps) {
  const { data: versions, isLoading } = useAgentVersions(agentId);
  const { data: tools } = useTools();
  const publishAgent = usePublishAgent();

  const [systemPrompt, setSystemPrompt] = useState("");
  const [modelName, setModelName] = useState("");
  const [toolIds, setToolIds] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);

  const toggleTool = (toolId: string) => {
    setToolIds((current) =>
      current.includes(toolId) ? current.filter((id) => id !== toolId) : [...current, toolId],
    );
  };

  const handlePublish = (): void => {
    setFeedback(null);
    publishAgent.mutate(
      {
        id: agentId,
        payload: {
          system_prompt: systemPrompt,
          model_config: modelName ? { model: modelName } : {},
          tools: toolIds.map((toolId) => ({
            tool_id: toolId,
            enabled: true,
            permission_scope: {},
          })),
        },
      },
      {
        onSuccess: (version: AgentVersionResponse) => {
          setFeedback(`已发布版本 ${version.version}`);
          setSystemPrompt("");
          setToolIds([]);
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <Card data-testid="version-list">
      <CardHeader>
        <CardTitle>版本管理</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-3 border-b pb-4">
          <div className="space-y-2">
            <Label htmlFor="version-prompt">System Prompt（新版本）</Label>
            <textarea
              id="version-prompt"
              data-testid="version-prompt-input"
              className="h-24 w-full rounded-md border border-input bg-background p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={systemPrompt}
              onChange={(event) => setSystemPrompt(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="version-model">模型</Label>
            <Input
              id="version-model"
              data-testid="version-model-input"
              value={modelName}
              placeholder="例如：gpt-4o-mini"
              onChange={(event) => setModelName(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label>绑定 Tool</Label>
            <ul className="space-y-1">
              {(tools ?? []).map((tool) => {
                const toolId = tool.id ?? tool.name;
                return (
                  <li key={toolId} className="flex items-center gap-2 text-sm">
                    <input
                      id={`version-tool-${tool.name}`}
                      data-testid={`version-tool-${tool.name}`}
                      type="checkbox"
                      checked={toolIds.includes(toolId)}
                      onChange={() => toggleTool(toolId)}
                    />
                    <label htmlFor={`version-tool-${tool.name}`}>
                      {tool.display_name || tool.name}
                    </label>
                  </li>
                );
              })}
            </ul>
          </div>
          {feedback ? (
            <p className="text-sm text-muted-foreground" data-testid="version-feedback">
              {feedback}
            </p>
          ) : null}
          <Button size="sm" onClick={handlePublish} disabled={publishAgent.isPending}>
            发布新版本
          </Button>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>版本</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead>当前</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={4}>
                  <div className="space-y-2">
                    <Skeleton className="h-6 w-full" />
                    <Skeleton className="h-6 w-full" />
                  </div>
                </TableCell>
              </TableRow>
            ) : (versions ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-sm text-muted-foreground">
                  暂无版本
                </TableCell>
              </TableRow>
            ) : (
              (versions ?? []).map((version) => (
                <TableRow key={version.id} data-testid={`version-row-${version.version}`}>
                  <TableCell>{version.version}</TableCell>
                  <TableCell>{version.status}</TableCell>
                  <TableCell>{version.created_at ?? "—"}</TableCell>
                  <TableCell>
                    {version.id === currentVersionId ? <Badge>当前版本</Badge> : null}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
