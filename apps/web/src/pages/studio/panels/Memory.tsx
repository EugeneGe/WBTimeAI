import { Badge } from "@/components/ui/badge";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RequirePermission } from "@/components/guards/RequirePermission";
import { useDeleteMemory, useMemories } from "@/hooks/useMemory";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import type { AgentStudioPanelProps, MemoryResponse } from "@/types";

/** 作用域类型选项（↔ `memory.scope_type`）。 */
const SCOPE_TYPES = ["user", "agent", "project", "workspace", "conversation"] as const;

/**
 * Memory 面板（W8 / T2-41；设计 §2.13）。
 *
 * - 配置 Agent 的**记忆作用域**（写入草稿 `memoryScope` → 发布落
 *   `runtime_config.memory_scope`）；
 * - 浏览 / 删除记忆（复用既有 Memory 服务；删除动作级守卫）。
 */
export function Memory({ draft, onDraftChange, onFeedback }: AgentStudioPanelProps) {
  const { t } = useTranslation();
  const { data: memories, isLoading } = useMemories({ scope_type: draft.memoryScope || null });
  const deleteMemory = useDeleteMemory();

  const handleDelete = (memory: MemoryResponse): void => {
    deleteMemory.mutate(memory.id, {
      onSuccess: () => onFeedback(t("studio.panel.memory.deleted")),
      onError: (error) => onFeedback(toApiError(error).message),
    });
  };

  return (
    <div className="space-y-4" data-testid="panel-memory">
      <Card>
        <CardHeader>
          <CardTitle>{t("studio.panel.memory.scopeTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Label htmlFor="panel-memory-scope">scope_type</Label>
          <Select
            value={draft.memoryScope}
            onValueChange={(value) => onDraftChange({ memoryScope: value })}
          >
            <SelectTrigger id="panel-memory-scope" data-testid="memory-scope-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SCOPE_TYPES.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("studio.panel.memory.listTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("studio.panel.memory.col.kind")}</TableHead>
                <TableHead>{t("studio.panel.memory.col.content")}</TableHead>
                <TableHead>{t("studio.panel.memory.col.sourceRun")}</TableHead>
                <TableHead className="text-right">{t("common.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    {t("common.loading")}
                  </TableCell>
                </TableRow>
              ) : (memories ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    {t("studio.panel.memory.empty")}
                  </TableCell>
                </TableRow>
              ) : (
                (memories ?? []).map((memory) => (
                  <TableRow key={memory.id} data-testid={`panel-memory-row-${memory.id}`}>
                    <TableCell>
                      <Badge variant="outline">{memory.kind}</Badge>
                    </TableCell>
                    <TableCell className="max-w-xs truncate">{memory.content}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {memory.source_run_id || "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <RequirePermission code="memory:delete">
                        <Button
                          variant="ghost"
                          size="sm"
                          data-testid={`memory-remove-${memory.id}`}
                          disabled={deleteMemory.isPending}
                          onClick={() => handleDelete(memory)}
                        >
                          {t("common.delete")}
                        </Button>
                      </RequirePermission>
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
