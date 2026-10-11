import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
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
  const { data: memories, isLoading } = useMemories({ scope_type: draft.memoryScope || null });
  const deleteMemory = useDeleteMemory();

  const handleDelete = (memory: MemoryResponse): void => {
    deleteMemory.mutate(memory.id, {
      onSuccess: () => onFeedback("记忆已删除"),
      onError: (error) => onFeedback(toApiError(error).message),
    });
  };

  return (
    <div className="space-y-4" data-testid="panel-memory">
      <Card>
        <CardHeader>
          <CardTitle>记忆作用域</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Label htmlFor="panel-memory-scope">scope_type</Label>
          <select
            id="panel-memory-scope"
            data-testid="memory-scope-select"
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={draft.memoryScope}
            onChange={(event) => onDraftChange({ memoryScope: event.target.value })}
          >
            {SCOPE_TYPES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>记忆列表</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>类别</TableHead>
                <TableHead>内容</TableHead>
                <TableHead>来源 Run</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : (memories ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    暂无记忆
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
                          删除
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
