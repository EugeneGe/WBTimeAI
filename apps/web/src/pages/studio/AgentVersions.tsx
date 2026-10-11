import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  usePublishAgentDraft,
  useStudioAgent,
  useStudioAgentVersions,
} from "@/hooks/useAgentStudio";
import { toApiError } from "@/lib/api";
import { createEmptyAgentStudioDraft, type AgentStudioDraft } from "@/types";

/**
 * Agent 版本管理与发布（W8 / T2-41；设计 §2.13）。
 *
 * **一次发布 = 一个新 `agent_version`**（不可变快照），并切换
 * `agent.current_version_id`。复用 `agentService.listVersions` / `publish`（经 Studio hooks）。
 */
export function AgentVersions() {
  const { agentId } = useParams<{ agentId: string }>();
  const id = agentId ?? null;

  const { data: agent } = useStudioAgent(id);
  const { data: versions, isLoading } = useStudioAgentVersions(id);
  const publishDraft = usePublishAgentDraft();

  const [systemPrompt, setSystemPrompt] = useState("");
  const [modelName, setModelName] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);

  const handlePublish = (): void => {
    if (!id) {
      setFeedback("缺少 Agent 标识");
      return;
    }
    const draft: AgentStudioDraft = {
      ...createEmptyAgentStudioDraft(),
      systemPrompt,
      modelConfig: modelName ? { model: modelName } : {},
    };
    publishDraft.mutate(
      { id, draft },
      {
        onSuccess: (created) => {
          setFeedback(`已发布版本 ${created.version}`);
          setSystemPrompt("");
          setModelName("");
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4" data-testid="agent-versions">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">版本管理</h1>
        <div className="flex items-center gap-2">
          {feedback ? (
            <span className="text-xs text-muted-foreground" data-testid="versions-feedback">
              {feedback}
            </span>
          ) : null}
          <Link
            className="text-xs text-primary underline-offset-4 hover:underline"
            to="/studio"
            data-testid="versions-back"
          >
            ← 返回 Studio
          </Link>
        </div>
      </div>

      <p className="text-sm text-muted-foreground" data-testid="versions-agent">
        Agent：{agent?.name ?? id ?? "—"}
      </p>

      <RequirePermission code="agent:publish">
        <Card>
          <CardHeader>
            <CardTitle>发布新版本</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="versions-prompt">System Prompt</Label>
              <textarea
                id="versions-prompt"
                data-testid="versions-prompt-input"
                className="min-h-[120px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
                value={systemPrompt}
                onChange={(event) => setSystemPrompt(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="versions-model">模型</Label>
              <Input
                id="versions-model"
                data-testid="versions-model-input"
                value={modelName}
                placeholder="例如：gpt-4o-mini"
                onChange={(event) => setModelName(event.target.value)}
              />
            </div>
            <Button
              size="sm"
              data-testid="versions-publish"
              onClick={handlePublish}
              disabled={publishDraft.isPending}
            >
              发布新版本
            </Button>
          </CardContent>
        </Card>
      </RequirePermission>

      <Card>
        <CardHeader>
          <CardTitle>版本列表</CardTitle>
        </CardHeader>
        <CardContent>
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
                  <TableCell colSpan={4} className="text-muted-foreground">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : (versions ?? []).length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground"
                    data-testid="versions-empty"
                  >
                    暂无版本
                  </TableCell>
                </TableRow>
              ) : (
                (versions ?? []).map((version) => (
                  <TableRow key={version.id} data-testid={`version-row-${version.version}`}>
                    <TableCell className="font-mono text-xs">{version.version}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{version.status}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {version.created_at ?? "—"}
                    </TableCell>
                    <TableCell>
                      {version.id === agent?.current_version_id ? <Badge>当前版本</Badge> : null}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
