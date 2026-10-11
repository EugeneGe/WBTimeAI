import { useMemo, useState } from "react";

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
import { useDeleteMemory, useMemories } from "@/hooks/useMemory";
import { toApiError } from "@/lib/api";
import type { MemoryResponse } from "@/types";

/** 作用域类型选项（↔ `scope_type`）。 */
const SCOPE_TYPES = ["", "user", "agent", "project", "workspace", "conversation"] as const;
/** 记忆类别选项（↔ `kind`）。 */
const KINDS = ["", "SHORT_TERM", "LONG_TERM", "PROJECT", "AGENT", "USER"] as const;

/**
 * Memory 视图（W6 / T2-35；设计 §2.7 / 裁定 §2.4 F-d / F-h）。
 *
 * - 按 `scope_type` / `scope_id` / `kind` **浏览**记忆；
 * - 逐条**删除**（`DELETE /memory/{id}`）；
 * - 展示**来源 Run**（`source_run_id`）。
 *
 * 🔴 SQLite 后端下检索退化为最近 / 关键词排序（无向量）——页内给出提示。
 */
export function MemoryView() {
  const [scopeType, setScopeType] = useState<string>("");
  const [scopeId, setScopeId] = useState<string>("");
  const [kind, setKind] = useState<string>("");
  const [feedback, setFeedback] = useState<string | null>(null);

  const params = useMemo(
    () => ({
      scope_type: scopeType || null,
      scope_id: scopeId || null,
      kind: kind || null,
    }),
    [scopeType, scopeId, kind],
  );

  const { data: memories, isLoading } = useMemories(params);
  const deleteMemory = useDeleteMemory();

  const handleDelete = (memory: MemoryResponse): void => {
    deleteMemory.mutate(memory.id, {
      onSuccess: () => setFeedback("记忆已删除"),
      onError: (error) => setFeedback(toApiError(error).message),
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Memory</h1>
        {feedback ? (
          <span className="text-xs text-muted-foreground" data-testid="memory-feedback">
            {feedback}
          </span>
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>按 scope 过滤</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="space-y-2">
            <Label htmlFor="memory-scope-type">作用域类型</Label>
            <select
              id="memory-scope-type"
              data-testid="memory-scope-type"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={scopeType}
              onChange={(event) => setScopeType(event.target.value)}
            >
              {SCOPE_TYPES.map((item) => (
                <option key={item || "all"} value={item}>
                  {item || "全部"}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="memory-scope-id">作用域标识</Label>
            <Input
              id="memory-scope-id"
              data-testid="memory-scope-id"
              value={scopeId}
              onChange={(event) => setScopeId(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="memory-kind">记忆类别</Label>
            <select
              id="memory-kind"
              data-testid="memory-kind"
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              {KINDS.map((item) => (
                <option key={item || "all"} value={item}>
                  {item || "全部"}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>记忆列表</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-xs text-muted-foreground" data-testid="memory-backend-hint">
            当前后端若不支持语义召回，已按最近 / 关键词排序展示。
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>类别</TableHead>
                <TableHead>作用域</TableHead>
                <TableHead>可见性</TableHead>
                <TableHead>内容</TableHead>
                <TableHead>重要度</TableHead>
                <TableHead>来源 Run</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : (memories ?? []).length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={7}
                    className="text-muted-foreground"
                    data-testid="memory-empty"
                  >
                    暂无记忆
                  </TableCell>
                </TableRow>
              ) : (
                (memories ?? []).map((memory) => (
                  <TableRow key={memory.id} data-testid={`memory-row-${memory.id}`}>
                    <TableCell>
                      <Badge variant="outline">{memory.kind}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {memory.scope_type}
                      {memory.scope_id ? `:${memory.scope_id}` : ""}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{memory.visibility}</Badge>
                    </TableCell>
                    <TableCell className="max-w-xs truncate">{memory.content}</TableCell>
                    <TableCell className="text-xs">{memory.importance.toFixed(2)}</TableCell>
                    <TableCell
                      className="font-mono text-xs text-muted-foreground"
                      data-testid={`memory-source-${memory.id}`}
                    >
                      {memory.source_run_id || "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid={`memory-delete-${memory.id}`}
                        disabled={deleteMemory.isPending}
                        onClick={() => handleDelete(memory)}
                      >
                        删除
                      </Button>
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
