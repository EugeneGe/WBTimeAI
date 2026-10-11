import { useState } from "react";

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
  useCreateDocument,
  useCreateKnowledgeBase,
  useDocuments,
  useKnowledgeBases,
  useSearchKnowledge,
} from "@/hooks/useKnowledge";
import { toApiError } from "@/lib/api";
import type { KnowledgeBaseResponse, SearchResponse } from "@/types";

/** Document 索引进度映射（`status` → 百分比；供进度条展示）。 */
function statusPercent(status: string): number {
  switch (status) {
    case "PENDING":
      return 10;
    case "PARSING":
      return 35;
    case "CHUNKING":
      return 60;
    case "EMBEDDING":
      return 85;
    case "READY":
    case "FAILED":
      return 100;
    default:
      return 0;
  }
}

/**
 * Knowledge Manager（W6 / T2-35；设计 §2.6 / §2.12）。
 *
 * - 知识库列表 + 创建；
 * - 文档列表：展示 `document.status` **索引进度**（可开轮询）；
 * - 检索试跑：命中 + **引用可回溯**（`source` / `chunk_id`）+ 检索路 `mode`
 *   （SQLite 下提示「已使用关键字检索」）。
 */
export function KnowledgeManager() {
  const { data: bases, isLoading } = useKnowledgeBases();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [newKbName, setNewKbName] = useState("");
  const createKb = useCreateKnowledgeBase();

  const effectiveBases = bases ?? [];
  const effectiveId = selectedId ?? effectiveBases[0]?.id ?? null;

  const handleCreateKb = (): void => {
    if (!newKbName.trim()) {
      setFeedback("请填写知识库名");
      return;
    }
    createKb.mutate(
      { name: newKbName.trim() },
      {
        onSuccess: (base: KnowledgeBaseResponse) => {
          setNewKbName("");
          setSelectedId(base.id);
          setFeedback("知识库已创建");
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Knowledge Manager</h1>
        {feedback ? (
          <span className="text-xs text-muted-foreground" data-testid="knowledge-feedback">
            {feedback}
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        {/* 左：知识库列表 + 新建 */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>知识库</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2" data-testid="kb-list">
                {isLoading ? (
                  <li className="text-sm text-muted-foreground">加载中…</li>
                ) : effectiveBases.length === 0 ? (
                  <li className="text-sm text-muted-foreground">暂无知识库</li>
                ) : (
                  effectiveBases.map((base) => (
                    <li key={base.id}>
                      <button
                        type="button"
                        data-testid={`kb-item-${base.name}`}
                        onClick={() => setSelectedId(base.id)}
                        className={
                          "w-full rounded-md border p-3 text-left transition-colors hover:bg-accent " +
                          (effectiveId === base.id ? "border-primary" : "")
                        }
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium">{base.name}</span>
                          <Badge variant="outline">{base.status}</Badge>
                        </div>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>新建知识库</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="kb-name">名称</Label>
                <Input
                  id="kb-name"
                  data-testid="kb-name-input"
                  value={newKbName}
                  onChange={(event) => setNewKbName(event.target.value)}
                />
              </div>
              <Button
                size="sm"
                data-testid="kb-create-submit"
                onClick={handleCreateKb}
                disabled={createKb.isPending}
              >
                创建
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* 右：文档 + 检索试跑 */}
        <div>
          {effectiveId ? (
            <KbWorkspace key={effectiveId} knowledgeBaseId={effectiveId} onFeedback={setFeedback} />
          ) : (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                选择或创建知识库以查看文档 / 检索试跑
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

/** 单个知识库的工作区（文档进度 + 登记 + 检索试跑）。 */
function KbWorkspace({
  knowledgeBaseId,
  onFeedback,
}: {
  knowledgeBaseId: string;
  onFeedback: (message: string) => void;
}) {
  const [poll, setPoll] = useState(false);
  const { data: documents } = useDocuments(knowledgeBaseId, { poll });
  const createDoc = useCreateDocument();
  const search = useSearchKnowledge();

  const [docTitle, setDocTitle] = useState("");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);

  const handleRegisterDoc = (): void => {
    if (!docTitle.trim()) {
      onFeedback("请填写文档标题");
      return;
    }
    createDoc.mutate(
      { knowledgeBaseId, payload: { title: docTitle.trim(), source_type: "text" } },
      {
        onSuccess: () => {
          setDocTitle("");
          onFeedback("文档已登记（PENDING，等待索引）");
        },
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  const handleSearch = (): void => {
    if (!query.trim()) {
      onFeedback("请填写检索词");
      return;
    }
    search.mutate(
      { query: query.trim(), knowledge_base_id: knowledgeBaseId, top_k: 5 },
      {
        onSuccess: (response) => setResult(response),
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>文档（索引进度）</CardTitle>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              data-testid="doc-poll-toggle"
              checked={poll}
              onChange={(event) => setPoll(event.target.checked)}
            />
            自动刷新进度
          </label>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>标题</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>状态（进度）</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(documents ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-muted-foreground">
                    暂无文档
                  </TableCell>
                </TableRow>
              ) : (
                (documents ?? []).map((document) => (
                  <TableRow key={document.id} data-testid={`doc-row-${document.title}`}>
                    <TableCell className="font-medium">{document.title}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {document.source_type}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Badge
                          variant={document.status === "READY" ? "default" : "secondary"}
                          data-testid={`doc-status-${document.title}`}
                        >
                          {document.status}
                        </Badge>
                        <div className="h-1.5 w-24 overflow-hidden rounded bg-muted">
                          <div
                            className={
                              "h-full " +
                              (document.status === "FAILED" ? "bg-destructive" : "bg-primary")
                            }
                            style={{ width: `${statusPercent(document.status)}%` }}
                            data-testid={`doc-progress-${document.title}`}
                          />
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          <div className="mt-4 space-y-2">
            <Label htmlFor="doc-title">登记文档（2b 仅登记元数据）</Label>
            <div className="flex gap-2">
              <Input
                id="doc-title"
                data-testid="doc-title-input"
                value={docTitle}
                onChange={(event) => setDocTitle(event.target.value)}
              />
              <Button
                size="sm"
                data-testid="doc-create-submit"
                onClick={handleRegisterDoc}
                disabled={createDoc.isPending}
              >
                登记
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>检索试跑</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              data-testid="search-query-input"
              placeholder="输入检索词…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Button
              size="sm"
              data-testid="search-submit"
              onClick={handleSearch}
              disabled={search.isPending}
            >
              检索
            </Button>
          </div>

          {result ? (
            <div className="space-y-2" data-testid="search-result">
              {result.mode !== "semantic" ? (
                <p className="text-xs text-muted-foreground" data-testid="search-mode-hint">
                  当前后端不支持语义检索，已使用关键字检索
                </p>
              ) : null}
              {result.hits.length === 0 ? (
                <p className="text-sm text-muted-foreground">无命中</p>
              ) : (
                <ul className="space-y-2">
                  {result.hits.map((hit) => (
                    <li
                      key={hit.chunk_id}
                      className="rounded-md border p-3"
                      data-testid={`search-hit-${hit.chunk_id}`}
                    >
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>score {hit.score.toFixed(3)}</span>
                        <span data-testid={`search-hit-source-${hit.chunk_id}`}>
                          引用：{hit.source}
                        </span>
                      </div>
                      <p className="mt-1 text-sm">{hit.content}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
